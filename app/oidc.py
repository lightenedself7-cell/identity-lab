"""OIDC Authorization Code flow with PKCE against Okta's default custom authorization server."""
from urllib.parse import urlencode

from authlib.integrations.flask_client import OAuth
from flask import Blueprint, redirect, session, url_for

from . import config
from .tokens import decode_unverified

bp = Blueprint("oidc", __name__)
oauth = OAuth()


def init_oidc(app):
    oauth.init_app(app)
    if not (config.OKTA_ISSUER and config.OIDC_CLIENT_ID):
        app.logger.warning("OIDC not configured (OKTA_ORG_URL / OIDC_CLIENT_ID missing)")
        return
    oauth.register(
        "okta",
        client_id=config.OIDC_CLIENT_ID,
        client_secret=config.OIDC_CLIENT_SECRET,
        server_metadata_url=f"{config.OKTA_ISSUER}/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
    )


@bp.get("/login/oidc")
def login():
    if "okta" not in oauth._clients:
        return "OIDC is not configured. Fill OKTA_ORG_URL, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET in .env", 500
    return oauth.okta.authorize_redirect(url_for("oidc.callback", _external=True))


@bp.get("/authorization-code/callback")
def callback():
    token = oauth.okta.authorize_access_token()  # validates state, PKCE verifier, ID token signature + nonce
    session["user"] = {
        "protocol": "OIDC",
        "claims": dict(token["userinfo"]),
        "access_token_claims": decode_unverified(token["access_token"]),
        "scope": token.get("scope"),
        "expires_in": token.get("expires_in"),
    }
    session["id_token"] = token.get("id_token")
    return redirect(url_for("index"))


@bp.get("/logout")
def logout():
    id_token = session.pop("id_token", None)
    protocol = (session.get("user") or {}).get("protocol")
    session.clear()
    if protocol == "OIDC" and id_token and config.OKTA_ISSUER:
        # RP-initiated logout ends the Okta session too, otherwise the next login is silent
        params = urlencode({"id_token_hint": id_token, "post_logout_redirect_uri": config.BASE_URL + "/"})
        return redirect(f"{config.OKTA_ISSUER}/v1/logout?{params}")
    return redirect(url_for("index"))
