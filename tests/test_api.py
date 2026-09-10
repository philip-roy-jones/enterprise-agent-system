from fastapi.testclient import TestClient
from enterprise.backend import create_app
from enterprise.config import Settings


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
