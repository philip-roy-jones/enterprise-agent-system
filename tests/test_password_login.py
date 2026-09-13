import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from eas_server.backend import create_app
from eas_server.config import Settings
from eas_server.security import token_hash


@pytest.fixture
def accounts(tmp_path):
    policy = tmp_path / "identities.json"
    policy.write_text(
        json.dumps(
            {
                "principals": [
                    {"id": "staff", "kind": "human", "name": "Original staff", "grants": []},
                    {
                        "id": "edge",
                        "kind": "planner",
                        "name": "Edge",
                        "worker_id": "edge-1",
                        "token_sha256": token_hash("unique-test-machine-credential"),
                        "grants": [],
                    },
                ]
            }
        )
    )
    app = create_app(
        Settings(
            data_dir=tmp_path,
            identity_file=str(policy),
            auth_mode="password",
            public_url="https://console.test",
        )
    )
    return app.state.security, TestClient(app, base_url="https://console.test"), policy


def activate(security, client, password="my long synthetic password"):
    token = security.accounts.invite("staff", "staff@example.test")
    response = client.post(
        "/api/account/setup", json={"email": "staff@example.test", "token": token, "password": password}
    )
    assert response.status_code == 200
    return token


def test_password_session_preserves_identity_csrf_and_logout(accounts):
    security, client, _ = accounts
    token = activate(security, client)
    assert client.get("/api/me").status_code == 401  # Setup does not silently sign in.
    response = client.post(
        "/api/session", json={"email": "STAFF@example.test", "password": "my long synthetic password"}
    )
    assert response.status_code == 200
    assert response.json()["principal"]["id"] == "staff"
    cookie = response.headers["set-cookie"]
    assert all(flag in cookie for flag in ("HttpOnly", "Secure", "SameSite=strict"))
    assert client.get("/api/me").json()["id"] == "staff"
    assert client.delete("/api/session").status_code == 403
    assert client.delete("/api/session", headers={"X-EAS-CSRF": response.json()["csrf"]}).status_code == 200
    assert client.get("/api/me").status_code == 401
    assert (
        client.post(
            "/api/account/setup",
            json={"email": "staff@example.test", "token": token, "password": "different long password"},
        ).status_code
        == 400
    )
    with security.store.db() as db:
        row = db.execute("SELECT * FROM staff_accounts").fetchone()
        assert row["password_hash"].startswith("$argon2id$")
        assert row["setup_hash"] is None


def test_reset_expiry_single_use_and_session_revocation(accounts):
    security, client, _ = accounts
    activate(security, client)
    client.post(
        "/api/session", json={"email": "staff@example.test", "password": "my long synthetic password"}
    )
    token = security.accounts.invite("staff", "staff@example.test")
    with security.store.db() as db:
        db.execute("UPDATE staff_accounts SET setup_expires=?", (time.time() - 1,))
    with pytest.raises(Exception, match="Setup link"):
        security.accounts.setup(token, "staff@example.test", "new synthetic password", "test")
    token = security.accounts.invite("staff", "staff@example.test")

    def attempt(_):
        try:
            return security.accounts.setup(token, "staff@example.test", "new synthetic password", "test")
        except Exception:
            return None

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(r is not None for r in results) == 1
    assert client.get("/api/me").status_code == 401
    assert (
        client.post(
            "/api/session", json={"email": "staff@example.test", "password": "my long synthetic password"}
        ).status_code
        == 401
    )


def test_login_throttle_unknown_users_and_disabled_identity(accounts):
    security, client, policy = accounts
    activate(security, client)
    wrong = {"email": "staff@example.test", "password": "incorrect"}
    assert (
        client.post("/api/session", json=wrong).json()
        == client.post("/api/session", json={**wrong, "email": "missing@example.test"}).json()
    )
    for _ in range(10):
        response = client.post("/api/session", json=wrong)
    assert response.status_code == 429
    with security.store.db() as db:
        db.execute("DELETE FROM login_limits")
    data = json.loads(policy.read_text())
    data["principals"][0]["enabled"] = False
    policy.write_text(json.dumps(data))
    assert (
        client.post(
            "/api/session", json={"email": "staff@example.test", "password": "my long synthetic password"}
        ).status_code
        == 401
    )


def test_machine_credentials_never_become_staff_sessions(accounts):
    security, client, _ = accounts
    with pytest.raises(ValueError, match="Only staff"):
        security.accounts.invite("edge", "edge@example.test")
    assert client.post("/api/session", json={"token": "unique-test-machine-credential"}).status_code == 401
    assert (
        client.get("/api/me", headers={"Authorization": "Bearer unique-test-machine-credential"}).status_code
        == 403
    )
    for path in ("/api/auth/login", "/api/auth/callback"):
        assert client.get(path).status_code != 200


def test_login_rejects_cross_origin_and_oversize_requests(accounts):
    _, client, _ = accounts
    assert client.post("/api/session", headers={"Origin": "https://evil.test"}, json={}).status_code == 403
    assert client.post("/api/session", content="email=x").status_code == 415
    assert client.post("/api/session", json={"email": "x" * 17000}).status_code == 413
