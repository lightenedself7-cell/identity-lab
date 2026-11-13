# Lab guide: 5 hours, 7 phases

Work top to bottom. Each phase has a time box. If you blow through one, skip its "Stretch" items and keep moving.
The order matters: SCIM rides on the SAML app, and the access review needs users, groups and apps to exist.

**Laptop slow or no Docker?** Run everything in GitHub Codespaces instead: follow [CODESPACES.md](CODESPACES.md) for setup, then use this guide with the substitutions listed there.

**Rule for today:** you click everything in the Okta console yourself. When something breaks, write it in
`docs/troubleshooting-log.md` *before* you fix it. That log is your interview material.

> Okta's console labels shift between releases. If a menu name below doesn't match exactly, look one level
> up or search the admin console. Where something is unverified on the Integrator Free plan, it's marked **[unverified]**.

| Time | Phase | Done when |
|---|---|---|
| 0:00-0:30 | 1. Tenant and app running | Dashboard loads at localhost:5000 |
| 0:30-1:30 | 2. OIDC + MFA | You see your ID token claims including `groups`, after an MFA prompt |
| 1:30-2:15 | 3. SAML | You see SAML attributes on the dashboard |
| 2:15-3:15 | 4. SCIM lifecycle | Joiner, mover, leaver all show in the event log |
| 3:15-3:50 | 5. OAuth API + Postman | Folder A passes in Postman |
| 3:50-4:20 | 6. Access review | CSV with at least one High finding, remediated |
| 4:20-5:00 | 7. Publish | Repo pushed, README screenshots, troubleshooting log has 3+ entries |

---

## Phase 1: Tenant and app running (30 min)

**Okta org**
1. Sign up at https://developer.okta.com/signup/ for the **Integrator Free Plan** (Workforce Identity).
2. Your admin console URL looks like `https://integrator-1234567-admin.okta.com`. Your **org URL** is the same without `-admin`.
3. Limits to remember: 10 active users, 5 Workflows. Org deactivates after 90 days with no sign-ins.

**Groups** (Directory > Groups > Add group): `Engineering`, `Finance`

**Users** (Directory > People > Add person). For each: Password = *Set by admin*, untick *User must change password on first login*, tick *Activate now*. Login can be a fake domain like `alice@lab.example`.

| User | Groups | Purpose in the demo |
|---|---|---|
| alice@lab.example | Engineering | Happy path, OIDC |
| bob@lab.example | Finance | SAML user |
| carol@lab.example | Engineering + Finance | Separation-of-duties violation |
| dave@lab.example | Engineering | The leaver |

**App**
```bash
unzip identity-lab.zip && cd identity-lab
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # paste into SCIM_BEARER_TOKEN
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # paste into FLASK_SECRET_KEY
# set OKTA_ORG_URL in .env
# for now set COMPOSE_PROFILES=quick; you switch to the named tunnel in Phase 4
docker compose up --build -d
docker compose logs -f app        # leave this open in a second terminal for the whole lab
```
Open http://localhost:5000. You should see the dashboard with three red pills.

**After every `.env` change:** `docker compose up -d --force-recreate app` (recreate only `app`, so the tunnel URL doesn't change).

---

## Phase 2: OIDC + MFA (60 min)

**Create the app**: Applications > Applications > Create App Integration > *OIDC - OpenID Connect* > *Web Application*
- App name: `Identity Lab (OIDC)`
- Grant type: Authorization Code (default)
- Sign-in redirect URI: `http://localhost:5000/authorization-code/callback`
- Sign-out redirect URI: `http://localhost:5000/`
- Assignments: *Limit access to selected groups* > `Engineering`
- Save. Copy **Client ID** and **Client secret** into `.env`. Recreate the app container.
- In the app's General tab, if you see *Require PKCE as additional verification*, tick it. (The app sends PKCE regardless.)

**Add a groups claim**: Security > API > Authorization Servers > `default` > Claims > Add Claim
- Name `groups`, Include in token type *ID Token / Always*, Value type *Groups*, Filter *Matches regex* `.*`, Include in *Any scope*

**Test**
1. Sign in with OIDC as alice. You should see ID token claims (including `groups`) and access token claims.
2. Log out, then sign in as **bob**. Okta should refuse because bob isn't assigned. Read the error. **Log entry #1.**
3. Compare the `aud` of the ID token (your client ID) with the access token (`api://default`). Know why they differ: the ID token is for the app, the access token is for an API.

**MFA**: Security > Authentication Policies > Add a policy `Require MFA`
- Add rule: *User must authenticate with* = *Any 2 factor types*. Add Okta Verify as an authenticator if prompted (Security > Authenticators).
- Applications tab of the policy > add `Identity Lab (OIDC)`.
- Sign in as alice in a private window, enroll Okta Verify on your phone, finish sign-in.

**Stretch:** add a second rule so Finance needs MFA every time and Engineering is remembered for 12 hours. That's an "adaptive" story.

---

## Phase 3: SAML (45 min)

**Create the app**: Create App Integration > *SAML 2.0*
- App name: `Identity Lab (SAML+SCIM)`
- Single sign-on URL: `http://localhost:5000/saml/acs` (tick *Use this for Recipient URL and Destination URL*)
- Audience URI (SP Entity ID): `http://localhost:5000/saml/metadata`
- Name ID format: *EmailAddress*. Application username: *Email*
- Attribute statements: `firstName` = `user.firstName`, `lastName` = `user.lastName`, `email` = `user.email`
- Group attribute statement: `groups`, *Matches regex*, `.*`
- Feedback page: *internal app*. Finish.

**Wire it up**
- Sign On tab > copy the **Metadata URL** into `SAML_IDP_METADATA_URL`. Recreate the container.
- Assignments tab > Assign to Groups > `Finance`.

**Test**: sign in with SAML as bob. You should see NameID and attributes.

**Break it on purpose** (5 min, worth it): change the Audience URI in Okta to `http://localhost:5000/wrong`, sign in, read the error on the page and in `docker compose logs app`. Change it back. **Log entry #2.**

**Stretch:** install the *SAML-tracer* browser extension and look at the raw assertion: Issuer, Signature, Audience, Recipient, NotOnOrAfter.

---

## Phase 4: SCIM lifecycle (60 min)

**Get a public URL: named tunnel on your Cloudflare domain (recommended, 15 min)**

Gives you a stable `https://scim-lab.<yourdomain>` that survives restarts.
Dashboard menu names move around; if these don't match, search "Tunnels" in the Cloudflare dashboard.
1. Cloudflare dashboard > Zero Trust > Networks > Tunnels > Create a tunnel > *Cloudflared*. Name it `identity-lab`.
2. On the install screen, choose *Docker* and copy only the long token after `--token`. Put it in `.env` as `TUNNEL_TOKEN`. Leave `COMPOSE_PROFILES=named`.
3. Add a public hostname: subdomain `scim-lab`, your domain, **Path** `scim/.*`, Service type `HTTP`, URL `app:5000`.
   The path restriction means only the SCIM API is reachable from the internet. Your dashboard and login pages stay on localhost.
4. Run `docker compose up -d`, then `docker compose logs tunnel-named`, and look for "Registered tunnel connection".
5. `curl https://scim-lab.<yourdomain>/scim/v2/ServiceProviderConfig` should return JSON. `curl https://scim-lab.<yourdomain>/` should **not** show your dashboard.

**Fallback: quick tunnel (no setup, URL changes on every restart)**: set `COMPOSE_PROFILES=quick` in `.env`, then:
```bash
docker compose up -d
docker compose logs tunnel | grep trycloudflare
```
If you restart the tunnel, paste the new URL into Okta's SCIM connector base URL.

In the steps below, `<your-url>` means `scim-lab.<yourdomain>` or your trycloudflare host.

**Turn on provisioning** on `Identity Lab (SAML+SCIM)`:
1. General tab > App Settings > Edit > Provisioning: **SCIM** > Save. **[unverified on Integrator Free]**
   *If there's no SCIM option:* add the OIN app **"SCIM 2.0 Test App (Header Auth)"** instead, and paste `Bearer <your token>` as the header value. The app accepts both formats.
2. Provisioning tab > Integration > Edit
   - SCIM connector base URL: `https://<your-url>.trycloudflare.com/scim/v2`
   - Unique identifier field for users: `userName`
   - Supported provisioning actions: *Push New Users*, *Push Profile Updates*, *Push Groups*
   - Authentication Mode: *HTTP Header*, Authorization: your `SCIM_BEARER_TOKEN`
   - **Test Connector Configuration** (should be green), then Save
3. Provisioning tab > To App > Edit: enable *Create Users*, *Update User Attributes*, *Deactivate Users* > Save

**Joiner**: Assignments > Assign to Groups > `Engineering`. Watch the dashboard (refreshes every 10s): alice, carol and dave appear.
If bob (assigned before provisioning was on) is missing, open his assignment and save it again to re-trigger it. **Log entry #3 if this happens.**

**Push groups**: Push Groups tab > + Push Groups > Find by name > `Engineering`, then `Finance`.

**Mover**: change alice's last name in Directory > People. Then remove carol from Finance. Watch `user.updated` and `group.member_removed`.
Put carol back in Finance afterwards: you need her for Phase 6.

**Leaver**: Directory > People > dave > More Actions > Deactivate. Watch `user.deactivated`.

**Where to look when nothing happens**: Reports > System Log, search `provision`. Then `docker compose logs app` for the HTTP status Okta got. Also check the Okta admin Dashboard > Tasks for failed provisioning tasks.

---

## Phase 5: OAuth API + Postman (35 min)

**Okta side**
1. Security > API > Authorization Servers > `default` > Scopes > Add Scope `reports.read`
2. Same server > Access Policies: open the default rule and check that *Client Credentials* is an allowed grant type. If not, add a rule that allows it.
3. Applications > Create App Integration > *API Services* > `Reports Client`. If it defaults to public/private key auth, switch Client authentication to *Client secret*. Copy the ID and secret.
4. Security > API > Tokens > Create token `access-review`. Copy it once (Okta won't show it again) into `.env` as `OKTA_API_TOKEN`.

**Postman**: Import `postman/identity-lab.postman_collection.json` and `postman/identity-lab.postman_environment.json`. Select the *Identity Lab* environment and fill it in.
- Folder A, in order. After step 7 (revoke), re-run 6 (inactive) and then 3 (**still 200**). Be able to explain why: the API validates the JWT locally against the JWKS, so it can't see revocation until the token expires. The fixes are short token lifetimes or introspection on sensitive calls. This is a strong interview answer.
- Folder B: Management API calls with your SSWS token.
- Folder C: hit SCIM directly, the same way Okta does.

---

## Phase 6: Access review, mini IGA (30 min)

```bash
docker compose run --rm app python scripts/access_review.py --demo --out reports/demo.csv   # sanity check
docker compose run --rm app python scripts/access_review.py --out reports/access_review.csv
```
Expect carol flagged **High (SoD)**. Dave may show as **orphaned access**. If he doesn't, Okta already cleaned up his assignments on deactivation: write down which, since that's a real product behaviour worth knowing.

**Close the loop:**
1. Open the CSV and fill `reviewer_decision` for the High rows (Revoke / Certify).
2. Remediate in Okta: remove carol from Finance.
3. SCIM pushes the removal to the app (`group.member_removed`).
4. Re-run the review: carol's finding is gone.

This is the Collect > Detect > Certify > Remediate cycle that IGA products automate at scale.

### 6B. Real campaign in Okta Identity Governance (20 min, if available)
Your org shows Identity Governance > Access Certifications. **[unverified]** Exact options on the Integrator Free plan aren't known.
1. Identity Governance > Access Certifications > **Create campaign**. If the button is greyed out, hover it to read why. It may need at least one app to exist first.
2. Choose a resource campaign on `Identity Lab (SAML+SCIM)` (or a group campaign on `Finance`). Reviewer: yourself (the admin). Short duration.
3. Launch it. Open the review as the reviewer and **Revoke** carol's access with a comment ("SoD: Engineering + Finance").
4. Check the outcome: carol's assignment is removed in Okta, and SCIM shows the change in the app's event log.
5. Screenshot the campaign results. Now you can show both: the script (how detection logic works) and the product (how a governance tool runs it as a process with reviewers and an audit trail).

---

## Phase 7: Publish (40 min)

1. Screenshots into `docs/img/`: dashboard after SCIM, OIDC claims, SAML attributes, Postman folder A results, access review terminal output.
2. Fill in at least 3 real entries in `docs/troubleshooting-log.md`.
3. Push:
```bash
git init && git add . && git status     # confirm .env and data/ are NOT listed
git commit -m "Okta identity lab: OIDC, SAML, SCIM, OAuth API, access review"
gh repo create identity-lab --public --source . --push     # or create it on github.com and push
```
4. Rehearse `docs/demo-script.md` once out loud, with a timer.
