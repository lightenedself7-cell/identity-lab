"""Replays the calls Okta makes during provisioning, plus API token checks."""
import time

import pytest
from authlib.jose import JsonWebKey, jwt

from app import config, create_app
from app.store import Store

TOKEN = "test-scim-token"
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/scim+json"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCIM_BEARER_TOKEN", TOKEN)
    app = create_app(store=Store(str(tmp_path / "scim.json")), testing=True)
    return app.test_client()


def okta_user(username="alice@lab.example"):
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": username,
        "name": {"givenName": "Alice", "familyName": "Ng"},
        "emails": [{"primary": True, "value": username, "type": "work"}],
        "displayName": "Alice Ng",
        "active": True,
        "password": "should-not-be-stored",
    }


def test_rejects_missing_or_wrong_token(client):
    assert client.get("/scim/v2/Users").status_code == 401
    assert client.get("/scim/v2/Users", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_accepts_raw_header_value(client):
    # OIN "SCIM 2.0 Test App (Header Auth)" may send the raw token
    assert client.get("/scim/v2/Users", headers={"Authorization": TOKEN}).status_code == 200


def test_okta_user_lifecycle(client):
    # 1. Okta checks whether the user exists
    r = client.get('/scim/v2/Users?filter=userName eq "alice@lab.example"&startIndex=1&count=100', headers=H)
    assert r.status_code == 200 and r.json["totalResults"] == 0
    # 2. create
    r = client.post("/scim/v2/Users", json=okta_user(), headers=H)
    assert r.status_code == 201
    assert r.headers["Content-Type"] == "application/scim+json"
    uid = r.json["id"]
    assert "password" not in r.json
    # 3. duplicate -> 409
    assert client.post("/scim/v2/Users", json=okta_user(), headers=H).status_code == 409
    # 4. filter is case-insensitive
    r = client.get('/scim/v2/Users?filter=userName eq "ALICE@lab.example"', headers=H)
    assert r.json["totalResults"] == 1
    # 5. profile update via PUT
    updated = okta_user() | {"displayName": "Alice Ng-Smith"}
    r = client.put(f"/scim/v2/Users/{uid}", json=updated, headers=H)
    assert r.json["displayName"] == "Alice Ng-Smith"
    # 6. deactivate via PATCH (Okta's shape: value object, no path)
    patch = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "replace", "value": {"active": False}}],
    }
    r = client.patch(f"/scim/v2/Users/{uid}", json=patch, headers=H)
    assert r.json["active"] is False
    # 7. reactivate with a path
    patch["Operations"] = [{"op": "replace", "path": "active", "value": True}]
    assert client.patch(f"/scim/v2/Users/{uid}", json=patch, headers=H).json["active"] is True
    assert client.get("/scim/v2/Users/does-not-exist", headers=H).status_code == 404


def test_okta_group_push(client):
    uid = client.post("/scim/v2/Users", json=okta_user(), headers=H).json["id"]
    uid2 = client.post("/scim/v2/Users", json=okta_user("bob@lab.example"), headers=H).json["id"]
    r = client.post("/scim/v2/Groups", json={"displayName": "Engineering", "members": []}, headers=H)
    gid = r.json["id"]
    add = {"Operations": [{"op": "add", "path": "members", "value": [{"value": uid, "display": "alice"}, {"value": uid2}]}]}
    assert len(client.patch(f"/scim/v2/Groups/{gid}", json=add, headers=H).json["members"]) == 2
    remove = {"Operations": [{"op": "remove", "path": f'members[value eq "{uid2}"]'}]}
    members = client.patch(f"/scim/v2/Groups/{gid}", json=remove, headers=H).json["members"]
    assert [m["value"] for m in members] == [uid]
    rename = {"Operations": [{"op": "replace", "value": {"id": gid, "displayName": "Platform Eng"}}]}
    assert client.patch(f"/scim/v2/Groups/{gid}", json=rename, headers=H).json["displayName"] == "Platform Eng"
    r = client.get("/scim/v2/Groups?excludedAttributes=members", headers=H)
    assert "members" not in r.json["Resources"][0]
    assert client.delete(f"/scim/v2/Groups/{gid}", headers=H).status_code == 204


def test_dashboard_renders_with_events(client):
    client.post("/scim/v2/Users", json=okta_user(), headers=H)
    r = client.get("/")
    assert r.status_code == 200 and b"user.created" in r.data


# --- protected API --------------------------------------------------------
ISS = "https://integrator-test.okta.com/oauth2/default"


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    key = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "k1"})
    pub = JsonWebKey.import_key_set({"keys": [key.as_dict(is_private=False) | {"kid": "k1"}]})
    monkeypatch.setattr(config, "OKTA_ISSUER", ISS)
    app = create_app(store=Store(str(tmp_path / "s.json")), testing=True)
    app.config["TEST_JWKS"] = pub
    return app.test_client(), key


def mint(key, **over):
    now = int(time.time())
    claims = {"iss": ISS, "aud": "api://default", "exp": now + 300, "iat": now,
              "sub": "0oaClient", "cid": "0oaClient", "scp": ["reports.read"]} | over
    return jwt.encode({"alg": "RS256", "kid": "k1"}, claims, key).decode()


def test_api_valid_token(api_client):
    c, key = api_client
    r = c.get("/api/reports", headers={"Authorization": f"Bearer {mint(key)}"})
    assert r.status_code == 200 and r.json["message"] == "Access granted"


@pytest.mark.parametrize("over,status,err", [
    ({"scp": ["other.scope"]}, 403, "insufficient_scope"),
    ({"aud": "api://wrong"}, 401, "invalid_token"),
    ({"iss": "https://evil.example"}, 401, "invalid_token"),
    ({"exp": int(time.time()) - 600}, 401, "invalid_token"),
])
def test_api_rejects_bad_tokens(api_client, over, status, err):
    c, key = api_client
    r = c.get("/api/reports", headers={"Authorization": f"Bearer {mint(key, **over)}"})
    assert r.status_code == status and r.json["error"] == err
    assert "WWW-Authenticate" in r.headers


def test_api_missing_token(api_client):
    c, _ = api_client
    assert c.get("/api/reports").status_code == 401


# --- SAML SP --------------------------------------------------------------
def test_saml_routes(tmp_path, monkeypatch):
    from app import saml_sp
    if not saml_sp.SAML_AVAILABLE:
        pytest.skip("python3-saml not installed")
    import subprocess
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(tmp_path / "k"),
                    "-out", str(tmp_path / "c"), "-days", "1", "-subj", "/CN=idp"], check=True, capture_output=True)
    cert = "".join((tmp_path / "c").read_text().splitlines()[1:-1])
    monkeypatch.setattr(config, "SAML_IDP_METADATA_URL", "https://idp.example.com/metadata")
    monkeypatch.setitem(saml_sp._idp_cache, "idp", {"idp": {
        "entityId": "http://idp.example.com",
        "singleSignOnService": {"url": "https://idp.example.com/sso",
                                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"},
        "x509cert": cert}})
    c = create_app(store=Store(str(tmp_path / "s.json")), testing=True).test_client()
    r = c.get("/saml/login")
    assert r.status_code == 302 and r.headers["Location"].startswith("https://idp.example.com/sso?SAMLRequest=")
    assert c.post("/saml/acs", data={"SAMLResponse": "bm90LXNhbWw="}).status_code == 400
    assert b"EntityDescriptor" in c.get("/saml/metadata").data
