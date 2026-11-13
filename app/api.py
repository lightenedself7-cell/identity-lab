"""A resource server protected by OAuth 2.0 access tokens (client credentials or user tokens)."""
from flask import Blueprint, current_app, jsonify, request

from . import config
from .tokens import TokenError, validate_access_token

bp = Blueprint("api", __name__, url_prefix="/api")


def _bearer_error(status, error, description):
    resp = jsonify({"error": error, "error_description": description})
    resp.status_code = status
    # RFC 6750 section 3: tell the client *why* it failed
    resp.headers["WWW-Authenticate"] = f'Bearer error="{error}", error_description="{description}"'
    return resp


@bp.get("/reports")
def reports():
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return _bearer_error(401, "invalid_request", "missing bearer token")
    try:
        claims = validate_access_token(
            header[7:], config.API_REQUIRED_SCOPE, key_set=current_app.config.get("TEST_JWKS")
        )
    except TokenError as exc:
        return _bearer_error(exc.status, exc.error, exc.description)
    return jsonify(
        {
            "message": "Access granted",
            "caller": claims.get("sub"),
            "client_id": claims.get("cid"),
            "scopes": claims.get("scp"),
            "data": [{"report": "Q3 access review", "status": "complete"}],
        }
    )


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})
