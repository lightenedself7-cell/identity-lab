"""JWT helpers: display-only decode, and real validation for the protected API."""
import base64
import json
import time

import requests
from authlib.jose import JsonWebKey, jwt
from authlib.jose.errors import JoseError

from . import config

_jwks_cache = {"keys": None, "fetched": 0}


def decode_unverified(token):
    """For DISPLAY ONLY on the dashboard. Never use this to make an access decision."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {"note": "opaque or unparsable token"}


def _jwks():
    if _jwks_cache["keys"] is None or time.time() - _jwks_cache["fetched"] > 3600:
        meta = requests.get(f"{config.OKTA_ISSUER}/.well-known/oauth-authorization-server", timeout=10).json()
        _jwks_cache["keys"] = JsonWebKey.import_key_set(requests.get(meta["jwks_uri"], timeout=10).json())
        _jwks_cache["fetched"] = time.time()
    return _jwks_cache["keys"]


class TokenError(Exception):
    def __init__(self, status, error, description):
        super().__init__(description)
        self.status, self.error, self.description = status, error, description


def validate_access_token(token, required_scope, key_set=None, issuer=None, audience=None):
    """Local JWT validation: signature (JWKS), iss, aud, exp, then scope."""
    issuer = issuer or config.OKTA_ISSUER
    audience = audience or config.API_AUDIENCE
    try:
        claims = jwt.decode(
            token,
            key_set or _jwks(),
            claims_options={
                "iss": {"essential": True, "value": issuer},
                "aud": {"essential": True, "value": audience},
                "exp": {"essential": True},
            },
        )
        claims.validate(leeway=30)
    except JoseError as exc:
        raise TokenError(401, "invalid_token", str(exc))
    scopes = claims.get("scp") or []
    if isinstance(scopes, str):
        scopes = scopes.split()
    if required_scope not in scopes:
        raise TokenError(403, "insufficient_scope", f"token scopes {scopes} do not include {required_scope}")
    return dict(claims)
