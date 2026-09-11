from fastapi.testclient import TestClient
from enterprise.backend import create_app
from enterprise.config import Settings
import pytest


@pytest.mark.parametrize("adapter", ["windows", "windows_accessibility"])
def test_windows_backend_needs_no_desktop_connection(tmp_path, adapter):
    settings = Settings(
        data_dir=tmp_path,
        desktop_adapter=adapter,
        windows_token="",
        desktop_agent_token="",
        windows_bridge_url="http://127.0.0.1:1",
        desktop_agent_url="http://127.0.0.1:1",
    )
    client = TestClient(create_app(settings), headers={"Authorization": "Bearer local-staff-demo"})
    assert client.get("/api/health").json()["application"] == "windows_desktop"
    assert client.get("/mock").status_code == 404
    assert client.get("/api/mock/state").status_code == 404
    assert client.post("/api/mock/scenario", json={"variant": "renamed"}).status_code == 404
    assert client.post("/api/mock/action", json={"name": "save"}).status_code == 404
    assert client.post("/api/jobs", json={"invoice_id": "INV-1042"}).status_code == 200


def test_authentication_artifacts_and_worker_role(tmp_path):
    client = TestClient(create_app(Settings(data_dir=tmp_path, desktop_adapter="browser")))
    assert client.get("/api/jobs").status_code == 401
    assert client.get("/api/mock/state").status_code == 401
    assert client.get("/api/artifacts/" + "a" * 32 + ".png").status_code == 401
    worker = {"Authorization": "Bearer local-worker-demo"}
    assert client.post("/api/jobs", headers=worker, json={"invoice_id": "INV-1042"}).status_code == 403
    assert client.post("/api/worker/decide", headers=worker, json={"args": []}).status_code == 403
    assert (
        client.post("/api/mock/action", headers=worker, json={"name": "save", "args": {}}).status_code == 409
    )


def test_default_mode_and_scoped_permissions(tmp_path):
    client = TestClient(
        create_app(Settings(data_dir=tmp_path, desktop_adapter="browser")),
        headers={"Authorization": "Bearer local-staff-demo"},
    )
    job = client.post("/api/jobs", json={"invoice_id": "INV-1042"}).json()
    assert job["selected_mode"] == job["effective_mode"] == "strict"
    assert (
        client.post("/api/jobs", json={"invoice_id": "INV-1042", "permissions": ["admin"]}).status_code == 403
    )
    assert client.post("/api/jobs", json={"invoice_id": "../../secret"}).status_code == 422
