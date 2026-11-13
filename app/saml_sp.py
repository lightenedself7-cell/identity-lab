"""SAML 2.0 service provider using python3-saml (OneLogin toolkit).

Okta = IdP, this app = SP. SP-initiated flow:
  /saml/login  -> AuthnRequest (HTTP-Redirect) to Okta
  /saml/acs    <- signed Response/Assertion (HTTP-POST) from Okta
"""
from urllib.parse import urlparse

from flask import Blueprint, make_response, redirect, request, session, url_for

from . import config

bp = Blueprint("saml", __name__, url_prefix="/saml")

try:
    from onelogin.saml2.auth import OneLogin_Saml2_Auth
    from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
    from onelogin.saml2.settings import OneLogin_Saml2_Settings

    SAML_AVAILABLE = True
except ImportError:  # xmlsec not installed (e.g. running outside Docker)
    SAML_AVAILABLE = False

_idp_cache = {}


def _settings():
    if "idp" not in _idp_cache:
        _idp_cache["idp"] = OneLogin_Saml2_IdPMetadataParser.parse_remote(config.SAML_IDP_METADATA_URL)
    settings = {
        "strict": True,
        "debug": True,
        "sp": {
            "entityId": f"{config.BASE_URL}/saml/metadata",
            "assertionConsumerService": {
                "url": f"{config.BASE_URL}/saml/acs",
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        },
        "security": {"wantAssertionsSigned": True, "wantMessagesSigned": False},
    }
    return OneLogin_Saml2_IdPMetadataParser.merge_settings(settings, _idp_cache["idp"])


def _prepare_request():
    base = urlparse(config.BASE_URL)
    return {
        "https": "on" if base.scheme == "https" else "off",
        "http_host": base.netloc,
        "script_name": request.path,
        "get_data": request.args.copy(),
        "post_data": request.form.copy(),
    }


def _guard():
    if not SAML_AVAILABLE:
        return "python3-saml/xmlsec not installed. Run the app with Docker.", 500
    if not config.SAML_IDP_METADATA_URL:
        return "SAML_IDP_METADATA_URL is not set in .env", 500
    return None


@bp.get("/login")
def login():
    if (err := _guard()):
        return err
    auth = OneLogin_Saml2_Auth(_prepare_request(), _settings())
    return redirect(auth.login(return_to=url_for("index", _external=True)))


@bp.post("/acs")
def acs():
    if (err := _guard()):
        return err
    auth = OneLogin_Saml2_Auth(_prepare_request(), _settings())
    try:
        auth.process_response()
    except Exception as exc:  # malformed / non-XML SAMLResponse
        return f"SAML error: could not parse response ({exc})", 400
    errors = auth.get_errors()
    if errors:
        # The reason is the most useful debugging line in the whole lab: log it, show it.
        return f"SAML error: {errors} / reason: {auth.get_last_error_reason()}", 400
    attrs = auth.get_attributes()
    session["user"] = {
        "protocol": "SAML",
        "claims": {
            "nameId": auth.get_nameid(),
            "nameIdFormat": auth.get_nameid_format(),
            "sessionIndex": auth.get_session_index(),
            **{k: (v[0] if len(v) == 1 else v) for k, v in attrs.items()},
        },
    }
    return redirect(url_for("index"))


@bp.get("/metadata")
def metadata():
    if not SAML_AVAILABLE:
        return "python3-saml not installed", 500
    sp_only = OneLogin_Saml2_Settings(
        {
            "strict": True,
            "sp": {
                "entityId": f"{config.BASE_URL}/saml/metadata",
                "assertionConsumerService": {
                    "url": f"{config.BASE_URL}/saml/acs",
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
                },
            },
        },
        sp_validation_only=True,
    )
    resp = make_response(sp_only.get_sp_metadata(), 200)
    resp.headers["Content-Type"] = "text/xml"
    return resp
