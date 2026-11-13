"""identity-lab: a target app for testing Okta OIDC, SAML, SCIM and OAuth flows."""
from flask import Flask, render_template, session
from werkzeug.middleware.proxy_fix import ProxyFix

from . import api, config, oidc, saml_sp, scim
from .store import Store


def create_app(store=None, testing=False):
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY
    app.config["TESTING"] = testing
    app.config["STORE"] = store or Store()
    # Behind the Cloudflare tunnel, trust X-Forwarded-* so generated URLs are https
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    oidc.init_oidc(app)
    app.register_blueprint(oidc.bp)
    app.register_blueprint(saml_sp.bp)
    app.register_blueprint(scim.bp)
    app.register_blueprint(api.bp)

    @app.get("/")
    def index():
        st = app.config["STORE"]
        return render_template(
            "index.html",
            user=session.get("user"),
            users=st.list("Users"),
            groups=st.list("Groups"),
            events=st.data["events"][:25],
            oidc_ready=bool(config.OIDC_CLIENT_ID),
            saml_ready=bool(config.SAML_IDP_METADATA_URL) and saml_sp.SAML_AVAILABLE,
            scim_ready=bool(config.SCIM_BEARER_TOKEN),
            user_name=lambda uid: (st.get("Users", uid) or {}).get("userName", uid),
        )

    @app.post("/admin/reset")
    def reset():
        app.config["STORE"].reset()
        return "", 204

    return app
