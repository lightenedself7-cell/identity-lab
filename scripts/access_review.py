#!/usr/bin/env python3
"""Mini IGA access review against an Okta org.

What a governance product (SailPoint, Saviynt, CyberArk Identity Compliance,
Okta Identity Governance) does at scale, reduced to the core idea:
  1. Collect: who has access to what (users, groups, app assignments)
  2. Detect:  risky access (orphaned, dormant, separation-of-duties conflicts)
  3. Certify: produce a campaign file a reviewer signs off line by line

Usage:
  python3 scripts/access_review.py                 # live, reads OKTA_ORG_URL + OKTA_API_TOKEN
  python3 scripts/access_review.py --demo          # offline sample data
  python3 scripts/access_review.py --dormant-days 30 --out reports/review.csv
"""
import argparse
import csv
import os
import sys
from datetime import datetime, timezone

import requests

# Toxic combinations: being in both groups is a policy violation.
SOD_RULES = [
    ("Engineering", "Finance", "Can change systems AND approve payments"),
]


# --- collection ------------------------------------------------------------
class Okta:
    def __init__(self, org_url, token):
        self.base = org_url.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"SSWS {token}", "Accept": "application/json"})

    def paged(self, path, params=None):
        url, out = f"{self.base}{path}", []
        while url:
            r = self.s.get(url, params=params, timeout=20)
            if r.status_code == 429:
                sys.exit("Rate limited by Okta (429). Wait a minute and retry.")
            r.raise_for_status()
            out.extend(r.json())
            url, params = r.links.get("next", {}).get("url"), None  # Okta paginates via Link header
        return out

    def collect(self):
        users = self.paged("/api/v1/users", {"limit": 200})
        # Default /users listing omits DEPROVISIONED users; those are exactly the ones we want to catch
        users += self.paged("/api/v1/users", {"search": 'status eq "DEPROVISIONED"', "limit": 200})
        groups = [g for g in self.paged("/api/v1/groups", {"limit": 200}) if g["type"] == "OKTA_GROUP"]
        membership = {g["profile"]["name"]: {u["id"] for u in self.paged(f"/api/v1/groups/{g['id']}/users")}
                      for g in groups}
        apps = self.paged("/api/v1/apps", {"limit": 200})
        assignments = []
        for app in apps:
            if app["status"] != "ACTIVE" or app["name"] in ("okta_enduser", "saasure", "okta_browser_plugin"):
                continue  # skip Okta's own dashboard/admin apps
            for a in self.paged(f"/api/v1/apps/{app['id']}/users", {"limit": 500}):
                assignments.append({"user_id": a["id"], "app": app["label"], "scope": a.get("scope", "USER")})
        return normalise(users), membership, assignments


def normalise(users):
    return {
        u["id"]: {
            "id": u["id"],
            "login": u["profile"]["login"],
            "status": u["status"],
            "last_login": u.get("lastLogin"),
            "created": u.get("created"),
        }
        for u in users
    }


def demo_data():
    users = normalise([
        {"id": "u1", "status": "ACTIVE", "lastLogin": _days_ago(1), "created": _days_ago(90), "profile": {"login": "alice@lab.example"}},
        {"id": "u2", "status": "ACTIVE", "lastLogin": _days_ago(2), "created": _days_ago(90), "profile": {"login": "bob@lab.example"}},
        {"id": "u3", "status": "ACTIVE", "lastLogin": _days_ago(3), "created": _days_ago(90), "profile": {"login": "carol@lab.example"}},
        {"id": "u4", "status": "DEPROVISIONED", "lastLogin": _days_ago(40), "created": _days_ago(90), "profile": {"login": "dave@lab.example"}},
        {"id": "u5", "status": "ACTIVE", "lastLogin": None, "created": _days_ago(60), "profile": {"login": "erin@lab.example"}},
    ])
    membership = {"Engineering": {"u1", "u3", "u4"}, "Finance": {"u2", "u3"}}
    assignments = [
        {"user_id": "u1", "app": "Identity Lab (OIDC)", "scope": "GROUP"},
        {"user_id": "u3", "app": "Identity Lab (OIDC)", "scope": "GROUP"},
        {"user_id": "u2", "app": "Identity Lab (SAML+SCIM)", "scope": "GROUP"},
        {"user_id": "u3", "app": "Identity Lab (SAML+SCIM)", "scope": "GROUP"},
        {"user_id": "u4", "app": "Identity Lab (OIDC)", "scope": "USER"},
        {"user_id": "u5", "app": "Identity Lab (SAML+SCIM)", "scope": "USER"},
    ]
    return users, membership, assignments


def _days_ago(n):
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# --- detection -------------------------------------------------------------
def _age_days(ts):
    if not ts:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(ts.replace("Z", "+00:00"))).days


def review(users, membership, assignments, dormant_days):
    groups_of = {}
    for g, ids in membership.items():
        for uid in ids:
            groups_of.setdefault(uid, set()).add(g)

    rows = []
    for a in assignments:
        u = users.get(a["user_id"])
        if not u:
            continue
        findings, risk = [], "Low"
        if u["status"] in ("DEPROVISIONED", "SUSPENDED"):
            findings.append(f"Orphaned access: user is {u['status']} but still assigned")
            risk = "High"
        age = _age_days(u["last_login"])
        if u["status"] == "ACTIVE" and (age is None or age > dormant_days):
            findings.append("Dormant: never signed in" if age is None else f"Dormant: no sign-in for {age} days")
            risk = "Medium" if risk == "Low" else risk
        for g1, g2, why in SOD_RULES:
            if {g1, g2} <= groups_of.get(u["id"], set()):
                findings.append(f"SoD conflict: {g1} + {g2} ({why})")
                risk = "High"
        if a["scope"] == "USER":
            findings.append("Direct assignment (not via group): harder to govern")
        rows.append({
            "user": u["login"],
            "status": u["status"],
            "groups": ";".join(sorted(groups_of.get(u["id"], []))),
            "application": a["app"],
            "assigned_via": a["scope"],
            "last_login": u["last_login"] or "never",
            "risk": risk,
            "findings": " | ".join(findings) or "None",
            "recommended_action": "Revoke" if risk == "High" else ("Review with manager" if risk == "Medium" else "Certify"),
            "reviewer_decision": "",
            "reviewer_comment": "",
        })
    order = {"High": 0, "Medium": 1, "Low": 2}
    return sorted(rows, key=lambda r: (order[r["risk"]], r["user"]))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--demo", action="store_true", help="use built-in sample data, no Okta needed")
    p.add_argument("--dormant-days", type=int, default=30)
    p.add_argument("--out", default="reports/access_review.csv")
    args = p.parse_args()

    if args.demo:
        data = demo_data()
    else:
        org, token = os.environ.get("OKTA_ORG_URL"), os.environ.get("OKTA_API_TOKEN")
        if not (org and token):
            sys.exit("Set OKTA_ORG_URL and OKTA_API_TOKEN (or use --demo).")
        data = Okta(org, token).collect()

    rows = review(*data, dormant_days=args.dormant_days)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["user"])
        w.writeheader()
        w.writerows(rows)

    counts = {k: sum(r["risk"] == k for r in rows) for k in ("High", "Medium", "Low")}
    print(f"Reviewed {len(rows)} access entitlements across {len({r['user'] for r in rows})} users")
    print(f"High: {counts['High']}  Medium: {counts['Medium']}  Low: {counts['Low']}")
    for r in rows:
        if r["risk"] != "Low":
            print(f"  [{r['risk']:6}] {r['user']:22} {r['application']:26} {r['findings']}")
    print(f"Certification campaign written to {args.out}")


if __name__ == "__main__":
    main()
