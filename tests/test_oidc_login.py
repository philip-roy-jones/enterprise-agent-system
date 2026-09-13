"""Controlled identity-provider fixture. This is not a live SSO evaluation."""

import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from eas_server.backend import create_app
from eas_server.config import Settings


def test_oidc_code_flow_binds_browser_nonce_and_one_time_state(tmp_path, monkeypatch):
    issuer, audience = "https://identity.example", "enterprise-agent-system"
    registry = tmp_path / "identities.json"
    registry.write_text(
        json.dumps(
            {
                "principals": [
                    {
                        "id": "alice",
                        "name": "Alice",
                        "kind": "human",
                        "issuer": issuer,
                        "subject": "subject-alice",
                        "grants": [],
                    }
                ]
            }
        )
    )
    app = create_app(
        Settings(
            data_dir=tmp_path,
            auth_mode="oidc",
            identity_file=str(registry),
            public_url="https://console.example",
            oidc_issuer=issuer,
            oidc_audience=audience,
            oidc_jwks_url=issuer + "/keys",
            oidc_authorization_url=issuer + "/authorize",
            oidc_token_url=issuer + "/token",
        )
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app.state.security.jwks = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key())
    )
    client = TestClient(app, base_url="https://console.example", follow_redirects=False)
    start = client.get("/api/auth/login")
    params = parse_qs(urlsplit(start.headers["location"]).query)
    assert start.status_code == 303 and params["code_challenge_method"] == ["S256"]
    assert "Secure" in start.headers["set-cookie"] and "HttpOnly" in start.headers["set-cookie"]
    exchanges = []

    def exchange(url, **kwargs):
        import base64
        import hashlib

        data = kwargs["data"]
        exchanges.append(data)
        assert (
            base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode()).digest())
            .rstrip(b"=")
            .decode()
            == params["code_challenge"][0]
        )
        claims = {
            "iss": issuer,
            "aud": audience,
            "sub": "subject-alice",
            "exp": int(time.time()) + 60,
            "iat": int(time.time()),
            "nonce": params["nonce"][0],
        }
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"id_token": jwt.encode(claims, key, algorithm="RS256")},
        )

    monkeypatch.setattr("eas_server.oidc.httpx.post", exchange)
    callback = "/api/auth/callback?state=" + params["state"][0] + "&code=fixture-code"
    # Another browser cannot attach its own callback to Alice's login attempt.
    stranger = TestClient(app, base_url="https://console.example")
    assert stranger.get(callback).status_code == 401 and not exchanges
    assert client.get(callback).status_code == 303
    me = client.get("/api/me").json()
    assert me["id"] == "alice" and me["csrf"]
    assert client.get(callback).status_code == 401 and len(exchanges) == 1
    assert client.delete("/api/session").status_code == 403
    assert client.delete("/api/session", headers={"X-EAS-CSRF": me["csrf"]}).status_code == 200
    assert client.get("/api/me").status_code == 401
