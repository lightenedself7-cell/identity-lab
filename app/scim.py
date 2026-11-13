"""SCIM 2.0 service provider (RFC 7643 / 7644), scoped to what Okta sends.

Okta lifecycle calls this endpoint handles:
  GET    /Users?filter=userName eq "x"     -> does the user already exist?
  POST   /Users                              -> create
  GET    /Users/{id}                         -> read back
  PUT    /Users/{id}                         -> profile update (Okta default)
  PATCH  /Users/{id}  active=false           -> deactivate
  GET    /Groups?filter=displayName eq "x"
  POST   /Groups, PATCH /Groups/{id} members add/remove, PUT, DELETE
"""
import re
from functools import wraps

from flask import Blueprint, current_app, jsonify, request

from . import config

bp = Blueprint("scim", __name__, url_prefix="/scim/v2")

SCHEMA_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
SCHEMA_GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCHEMA_LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCHEMA_ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"
SCHEMA_PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


def store():
    return current_app.config["STORE"]


def scim_response(body, status=200):
    resp = jsonify(body)
    resp.status_code = status
    resp.headers["Content-Type"] = "application/scim+json"
    return resp


def scim_error(status, detail, scim_type=None):
    body = {"schemas": [SCHEMA_ERROR], "status": str(status), "detail": detail}
    if scim_type:
        body["scimType"] = scim_type
    return scim_response(body, status)


def require_bearer(fn):
    """Okta 'HTTP Header' auth sends 'Authorization: Bearer <token>'.
    The OIN 'SCIM 2.0 Test App (Header Auth)' sends whatever you type, so accept both."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = config.SCIM_BEARER_TOKEN
        if not expected:
            return scim_error(500, "SCIM_BEARER_TOKEN is not set on the server")
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else header
        if token != expected:
            store().log("scim.auth_failed", f"{request.method} {request.path}")
            return scim_error(401, "Invalid or missing bearer token")
        return fn(*args, **kwargs)

    return wrapper


# --- helpers -------------------------------------------------------------
FILTER_RE = re.compile(r'^\s*(\w+(?:\.\w+)?)\s+eq\s+"([^"]*)"\s*$', re.IGNORECASE)


def apply_filter(resources, filt):
    if not filt:
        return resources
    m = FILTER_RE.match(filt)
    if not m:
        return None
    attr, value = m.group(1), m.group(2)
    out = []
    for r in resources:
        current = r
        for part in attr.split("."):
            current = current.get(part) if isinstance(current, dict) else None
        if isinstance(current, str) and current.lower() == value.lower():
            out.append(r)
    return out


def list_response(resources):
    start = max(int(request.args.get("startIndex", 1)), 1)
    count = int(request.args.get("count", 100))
    page = resources[start - 1 : start - 1 + count]
    return scim_response(
        {
            "schemas": [SCHEMA_LIST],
            "totalResults": len(resources),
            "startIndex": start,
            "itemsPerPage": len(page),
            "Resources": page,
        }
    )


def body():
    return request.get_json(force=True, silent=True) or {}


def clean_user(payload):
    user = {k: v for k, v in payload.items() if k not in ("id", "meta")}
    user["schemas"] = payload.get("schemas") or [SCHEMA_USER]
    user.setdefault("active", True)
    user.pop("password", None)  # never store passwords in a target app
    return user


# --- discovery endpoints -------------------------------------------------
@bp.get("/ServiceProviderConfig")
def service_provider_config():
    return scim_response(
        {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
            "patch": {"supported": True},
            "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
            "filter": {"supported": True, "maxResults": 200},
            "changePassword": {"supported": False},
            "sort": {"supported": False},
            "etag": {"supported": False},
            "authenticationSchemes": [
                {"type": "oauthbearertoken", "name": "Bearer token", "description": "Static bearer token"}
            ],
        }
    )


# --- Users ---------------------------------------------------------------
@bp.get("/Users")
@require_bearer
def list_users():
    users = apply_filter(store().list("Users"), request.args.get("filter"))
    if users is None:
        return scim_error(400, "Unsupported filter", "invalidFilter")
    return list_response(users)


@bp.post("/Users")
@require_bearer
def create_user():
    payload = body()
    username = payload.get("userName")
    if not username:
        return scim_error(400, "userName is required", "invalidValue")
    if apply_filter(store().list("Users"), f'userName eq "{username}"'):
        store().log("user.create_conflict", username)
        return scim_error(409, f"User {username} already exists", "uniqueness")
    user = store().create("Users", clean_user(payload))
    store().log("user.created", f"{username} (active={user['active']})")
    return scim_response(user, 201)


@bp.get("/Users/<rid>")
@require_bearer
def get_user(rid):
    user = store().get("Users", rid)
    return scim_response(user) if user else scim_error(404, "User not found")


@bp.put("/Users/<rid>")
@require_bearer
def replace_user(rid):
    existing = store().get("Users", rid)
    if not existing:
        return scim_error(404, "User not found")
    user = store().replace("Users", rid, clean_user(body()))
    action = "user.deactivated" if existing.get("active") and not user.get("active") else "user.updated"
    if not existing.get("active") and user.get("active"):
        action = "user.reactivated"
    store().log(action, user.get("userName", rid))
    return scim_response(user)


def _apply_user_patch(user, ops):
    for op in ops:
        kind = op.get("op", "").lower()
        path = op.get("path")
        value = op.get("value")
        if kind not in ("replace", "add"):
            continue
        if path:
            target = user
            parts = path.split(".")
            for p in parts[:-1]:
                target = target.setdefault(p, {})
            target[parts[-1]] = value
        elif isinstance(value, dict):
            for k, v in value.items():
                if "." in k:
                    head, tail = k.split(".", 1)
                    user.setdefault(head, {})[tail] = v
                else:
                    user[k] = v
    return user


@bp.patch("/Users/<rid>")
@require_bearer
def patch_user(rid):
    user = store().get("Users", rid)
    if not user:
        return scim_error(404, "User not found")
    was_active = user.get("active", True)
    _apply_user_patch(user, body().get("Operations", []))
    store().touch("Users", rid)
    now_active = user.get("active", True)
    if was_active and not now_active:
        store().log("user.deactivated", user["userName"])
    elif not was_active and now_active:
        store().log("user.reactivated", user["userName"])
    else:
        store().log("user.patched", user["userName"])
    return scim_response(user)


@bp.delete("/Users/<rid>")
@require_bearer
def delete_user(rid):
    user = store().get("Users", rid)
    if not user:
        return scim_error(404, "User not found")
    store().delete("Users", rid)
    store().log("user.deleted", user.get("userName", rid))
    return "", 204


# --- Groups --------------------------------------------------------------
def _user_name(uid):
    u = store().get("Users", uid)
    return u["userName"] if u else uid


@bp.get("/Groups")
@require_bearer
def list_groups():
    groups = apply_filter(store().list("Groups"), request.args.get("filter"))
    if groups is None:
        return scim_error(400, "Unsupported filter", "invalidFilter")
    if request.args.get("excludedAttributes") == "members":
        groups = [{k: v for k, v in g.items() if k != "members"} for g in groups]
    return list_response(groups)


@bp.post("/Groups")
@require_bearer
def create_group():
    payload = body()
    name = payload.get("displayName")
    if not name:
        return scim_error(400, "displayName is required", "invalidValue")
    if apply_filter(store().list("Groups"), f'displayName eq "{name}"'):
        return scim_error(409, f"Group {name} already exists", "uniqueness")
    group = {
        "schemas": [SCHEMA_GROUP],
        "displayName": name,
        "members": payload.get("members", []),
    }
    group = store().create("Groups", group)
    store().log("group.created", f"{name} ({len(group['members'])} members)")
    return scim_response(group, 201)


@bp.get("/Groups/<rid>")
@require_bearer
def get_group(rid):
    group = store().get("Groups", rid)
    return scim_response(group) if group else scim_error(404, "Group not found")


@bp.put("/Groups/<rid>")
@require_bearer
def replace_group(rid):
    if not store().get("Groups", rid):
        return scim_error(404, "Group not found")
    payload = body()
    group = {
        "schemas": [SCHEMA_GROUP],
        "displayName": payload.get("displayName"),
        "members": payload.get("members", []),
    }
    group = store().replace("Groups", rid, group)
    store().log("group.replaced", f"{group['displayName']} ({len(group['members'])} members)")
    return scim_response(group)


MEMBER_PATH_RE = re.compile(r'members\[value eq "([^"]+)"\]')


@bp.patch("/Groups/<rid>")
@require_bearer
def patch_group(rid):
    group = store().get("Groups", rid)
    if not group:
        return scim_error(404, "Group not found")
    members = {m["value"]: m for m in group.get("members", [])}
    for op in body().get("Operations", []):
        kind = op.get("op", "").lower()
        path = op.get("path") or ""
        value = op.get("value")
        if kind == "add" and path == "members":
            for m in value or []:
                members[m["value"]] = m
                store().log("group.member_added", f"{_user_name(m['value'])} -> {group['displayName']}")
        elif kind == "remove":
            match = MEMBER_PATH_RE.match(path)
            if match:
                members.pop(match.group(1), None)
                store().log("group.member_removed", f"{_user_name(match.group(1))} -x {group['displayName']}")
            elif path == "members" and value:
                for m in value:
                    members.pop(m["value"], None)
                    store().log("group.member_removed", f"{_user_name(m['value'])} -x {group['displayName']}")
        elif kind == "replace":
            if path == "members":
                members = {m["value"]: m for m in value or []}
                store().log("group.members_replaced", group["displayName"])
            elif path == "displayName" or (isinstance(value, dict) and "displayName" in value):
                new_name = value if path else value["displayName"]
                store().log("group.renamed", f"{group['displayName']} -> {new_name}")
                group["displayName"] = new_name
    group["members"] = list(members.values())
    store().touch("Groups", rid)
    return scim_response(group)


@bp.delete("/Groups/<rid>")
@require_bearer
def delete_group(rid):
    group = store().get("Groups", rid)
    if not group:
        return scim_error(404, "Group not found")
    store().delete("Groups", rid)
    store().log("group.deleted", group["displayName"])
    return "", 204
