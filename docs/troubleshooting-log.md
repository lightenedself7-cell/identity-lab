# Troubleshooting log

Real issues hit while building this lab. Each entry is written so I could explain it to a customer.
Fill it in *as it happens*. Don't reconstruct it later.

| # | Symptom (exact error) | Where I looked | Root cause | Fix | How I'd explain it to a customer |
|---|---|---|---|---|---|
| 1 |  |  |  |  |  |
| 2 |  |  |  |  |  |
| 3 |  |  |  |  |  |

## Places to look, in order
1. The error text on the page (OIDC `error_description`, the SAML `reason`)
2. `docker compose logs app`: HTTP status codes Okta's SCIM calls received
3. Okta Reports > System Log (filter on the user or the app)
4. Okta Dashboard > Tasks (failed provisioning)
5. Browser dev tools Network tab, or the SAML-tracer extension
