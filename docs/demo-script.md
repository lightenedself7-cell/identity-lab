# 10-minute demo script

Written the way a Domain Consultant runs a first technical demo: start with the customer's problem, show only what
answers it, and end on the outcome. Rewrite the lines in your own words before you rehearse.

**Setup before the call:** dashboard open, Okta admin in a second tab, Postman open on folder A, terminal ready,
carol back in Finance, dave active again (reactivate him and re-assign).

## 0:00 Frame the problem (1 min)
Typical discovery answers to play back:
- "Onboarding takes days because IT creates accounts app by app."
- "Audit found accounts still active for people who left."
- "We can't easily prove who has access to what."

"I'll show the full identity lifecycle on one app: how users sign in, how accounts get created and removed
automatically, and how you prove access is correct."

## 1:00 Authentication: OIDC with MFA (1.5 min)
- Sign in as alice. MFA prompt. Land on the dashboard.
- Point at the `groups` claim: "The app gets group membership at login, so authorization lives in the directory, not in the app."
- Try bob: denied. "Access is assignment-based. No assignment, no login."

## 2:30 Legacy apps: SAML (1 min)
- Sign in as bob through SAML. "Same identity, same policy, older protocol. Most enterprises run both."

## 3:30 Joiner, mover, leaver: SCIM (3 min)
- **Joiner:** add a user to Engineering in Okta. Wait for them to appear in the app. "No ticket, no manual account."
- **Mover:** change a department or remove a group. Show the event.
- **Leaver:** deactivate dave. Show `user.deactivated`. "This is the audit finding from earlier, closed automatically."

## 6:30 API security: OAuth client credentials (1 min)
- Postman: get a token, call the API (200), call it with no token (401).
- "Machines get identities too, with scoped, short-lived tokens instead of shared passwords."

## 7:30 Governance: access review (2 min)
- Run the access review script. Carol is flagged: Engineering + Finance is a separation-of-duties conflict.
- Remove her from Finance in Okta. The SCIM event fires. Re-run: clean.
- "Collect, detect, certify, remediate. A governance product runs this continuously across hundreds of apps; this is the core loop in miniature."

## 9:30 Close (30 sec)
- Map back to the three problems from minute 0.
- Ask: "Which of these is most painful for you today?" That's the next discovery question, not a summary.

## Likely technical questions to prepare
- Why PKCE on a confidential client? (Defense in depth against code interception. OAuth 2.1 recommends it for all clients.)
- ID token vs access token: who is each for?
- What happens to a revoked JWT access token? (Phase 5 finding)
- SCIM PUT vs PATCH: which does Okta use for what?
- What breaks if the SAML Audience doesn't match? (Phase 3 finding)
- How would this scale to 500 apps? (Group-based assignment, attribute-driven rules, governance campaigns)
