"""Central config, loaded from environment (.env via docker compose)."""
import os

try:  # load .env when running without Docker (Codespaces, plain python)
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass


def _default_base_url():
    # GitHub Codespaces exposes port 5000 at https://<name>-5000.<domain>
    name = os.environ.get("CODESPACE_NAME")
    domain = os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
    if name and domain:
        return f"https://{name}-5000.{domain}"
    return "http://localhost:5000"


def _env(name, default=None):
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else value


OKTA_ORG_URL = _env("OKTA_ORG_URL", "").rstrip("/")          # https://integrator-1234567.okta.com
OKTA_ISSUER = _env("OKTA_ISSUER") or (f"{OKTA_ORG_URL}/oauth2/default" if OKTA_ORG_URL else "")

# Phase 2: OIDC web app
OIDC_CLIENT_ID = _env("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = _env("OIDC_CLIENT_SECRET", "")

# Phase 3: SAML app (metadata URL from the Okta SAML app "Sign On" tab)
SAML_IDP_METADATA_URL = _env("SAML_IDP_METADATA_URL", "")

# Phase 4: SCIM bearer token (you invent this, paste the same value into Okta)
SCIM_BEARER_TOKEN = _env("SCIM_BEARER_TOKEN", "")

# Phase 5: protected API
API_AUDIENCE = _env("API_AUDIENCE", "api://default")
API_REQUIRED_SCOPE = _env("API_REQUIRED_SCOPE", "reports.read")

BASE_URL = (_env("BASE_URL") or _default_base_url()).rstrip("/")
SECRET_KEY = _env("FLASK_SECRET_KEY", "dev-only-change-me")
DATA_DIR = _env("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
