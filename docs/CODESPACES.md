# Run the lab in GitHub Codespaces (no Docker, no local install)

Everything runs in a cloud VM. Your laptop only needs a browser.
Free tier for personal accounts: 120 compute hours/month (about 60 hours on a 2-core machine). Without a payment method on file, usage stops at the limit instead of being charged.
**Stop the codespace when you're done** (github.com/codespaces > ... > Stop) so it doesn't burn hours while idle.

## Setup (15 min)

1. github.com/new: name `identity-lab`, **Public**, tick *Add a README*, Create.
2. On the repo page: **Code > Codespaces > Create codespace on main**. VS Code opens in the browser.
3. Drag `identity-lab.zip` from your computer into the Explorer panel on the left. Then in the terminal:
   ```bash
   unzip -q identity-lab.zip && cp -r identity-lab/. . && rm -rf identity-lab identity-lab.zip
   pip install -r requirements.txt
   cp .env.example .env
   pytest -q                                   # 12 passed
   ```
4. Fill in `.env` (`FLASK_SECRET_KEY`, `SCIM_BEARER_TOKEN`, `OKTA_ORG_URL` once you have it). Leave `BASE_URL` empty: it auto-detects the codespace URL.
5. Start the app (keep this terminal open, it's your log):
   ```bash
   gunicorn -b 0.0.0.0:5000 --threads 4 --access-logfile - run:app
   ```
6. **Ports** tab > port 5000 > right-click > **Port Visibility > Public**. Okta needs to reach it for SCIM.
7. Print your URL: `python -c "from app import config; print(config.BASE_URL)"`. It looks like `https://<name>-5000.app.github.dev`. Open it to see the dashboard.

After any `.env` change: Ctrl+C the gunicorn terminal and start it again.

## Differences from LAB-GUIDE.md

| LAB-GUIDE says | In Codespaces, use |
|---|---|
| `http://localhost:5000` (all Okta redirect URIs, SAML ACS and Audience) | your codespace URL, e.g. `https://<name>-5000.app.github.dev` |
| SCIM base URL via Cloudflare tunnel | `https://<name>-5000.app.github.dev/scim/v2`. **Skip the tunnel section.** |
| `docker compose up` / `logs app` | the gunicorn terminal |
| `docker compose run --rm app python scripts/access_review.py ...` | `python scripts/access_review.py ...` (export the vars first: `set -a; source .env; set +a`) |
| Postman `app_url` = localhost | your codespace URL |

The codespace URL stays the same as long as you keep using **this** codespace (stop and restart is fine). Deleting it and creating a new one gives you a new URL, and every Okta URL then has to be updated.

## Security note
A public port exposes the whole app, including the dashboard, to anyone who has the URL. That's acceptable for a lab with fake `@lab.example` users. Don't put real data in it, and set the port back to Private, or stop the codespace, when you're not using it.

## Committing
Source Control panel (left sidebar) > message > Commit > Sync. Check that `.env` is **not** in the list of changes (it's git-ignored).
