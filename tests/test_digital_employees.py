"""Lifecycle and mentoring security checks; all humans and models are simulated."""

import io
import json
import time
from types import SimpleNamespace

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from eas_server.backend import create_app
from eas_server.config import Settings
from eas_shared.types import Observation


@pytest.fixture
def employees(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, desktop_adapter="browser", model_mode="simulated"))
    client = TestClient(app)

    def headers(actor):
        return {"Authorization": "Bearer local-" + actor + "-demo", "X-EAS-Protocol": "2"}

    return app, client, headers


def state(ctx, value, who="developer"):
    _, c, h = ctx
    return c.post(
        "/api/employees/development-desktop/state",
        headers=h(who),
        json={"state": value, "reason": "Simulated supervisor assessment"},
    )


def demonstrate(ctx):
    _, c, h = ctx
    result = c.post(
        "/api/employees/development-desktop/demonstrations",
        headers=h("developer"),
        json={
            "role_id": "invoice_correction",
            "company_id": "ACME",
            "task": "Explain how to inspect an invoice",
        },
    )
    result.raise_for_status()
    return result.json()


def capture(ctx, job):
    _, c, h = ctx
    png = io.BytesIO()
    Image.new("RGB", (30, 30), "white").save(png, format="PNG")
    artifact = c.post(
        "/api/worker-artifacts", headers={**h("worker"), "X-EAS-Job": job["id"]}, content=png.getvalue()
    )
    artifact.raise_for_status()
    response = c.post(
        "/api/employee-observation/" + job["id"],
        headers=h("worker"),
        json={
            "observation": Observation(
                revision="one",
                timestamp=time.time(),
                screenshot=artifact.json()["id"],
                state={"view": "invoice"},
            ).model_dump()
        },
    )
    response.raise_for_status()
    return artifact.json()["id"]


def test_new_employee_shadowing_and_only_supervisor_can_activate(employees):
    app, c, h = employees
    assert c.get("/api/employees", headers=h("staff")).json()[0]["state"] == "shadowing"
    assert c.post("/api/chat", headers=h("staff"), json={"task": "hello"}).status_code == 403
    assert state(employees, "active", "staff").status_code == 403
    assert state(employees, "active", "worker").status_code == 403
    assert state(employees, "active").status_code == 200
    assert c.post("/api/chat", headers=h("staff"), json={"task": "hello"}).status_code == 200
    assert (
        app.state.security.workforce.get("development-desktop")["readiness"]["kind"]
        == "supervisor_assessment"
    )


def test_shadow_cannot_claim_execute_or_forge_notes(employees):
    app, c, h = employees
    job = demonstrate(employees)
    poll = c.post("/api/employee-observation/poll", headers=h("worker"), json={})
    assert poll.json()["job"]["id"] == job["id"]
    assert c.post("/api/employee-observation/poll", headers=h("planner"), json={}).status_code == 403
    for method, args in [
        ("claim", ["worker"]),
        ("begin_window_recovery", [job["id"], "staff", 1, "window"]),
        ("check", [job["id"], "staff", 1]),
    ]:
        result = c.post("/api/worker/" + method, headers=h("worker"), json={"args": args})
        assert result.json() is None if method == "claim" else result.status_code >= 400
    assert c.post(
        "/api/employee-observation/" + job["id"],
        headers=h("worker"),
        json={"notes": {"observation": "Invented"}, "review_seq": 9999, "model_mode": "simulated"},
    ).status_code in {400, 409}
    assert not app.state.store.approvals(job["id"])


def test_demo_capture_bound_to_mentor_and_pause_revokes_it(employees):
    app, c, h = employees
    job = demonstrate(employees)
    artifact = capture(employees, job)
    assert c.get("/api/artifacts/" + artifact, headers=h("staff")).status_code == 404
    assert c.get("/api/artifacts/" + artifact, headers=h("developer")).status_code == 200
    assert c.post(
        "/api/demonstrations/" + job["id"] + "/messages", headers=h("staff"), json={"text": "Do this"}
    ).status_code in {403, 404}
    assert state(employees, "paused").status_code == 200
    assert app.state.store.get_job(job["id"])["status"] == "cancelled"
    assert (
        c.post(
            "/api/employee-observation/" + job["id"], headers=h("worker"), json={"error": "late"}
        ).status_code
        == 409
    )


def test_demo_notes_are_not_verified_agent_execution(employees, tmp_path):
    app, c, h = employees
    job = demonstrate(employees)
    capture(employees, job)
    seq = app.state.store.events(job["id"])[-1]["seq"]
    body = {
        "notes": {
            "observation": "Mentor opened a record",
            "question": "What do you verify?",
            "lesson": "Check the current record before answering",
        },
        "model_mode": "simulated",
        "review_seq": seq,
    }
    assert (
        c.post(
            "/api/employee-observation/" + job["id"],
            headers=h("worker"),
            json={"reserve_review": True, "review_seq": seq, "model_mode": "simulated"},
        ).status_code
        == 200
    )
    assert c.post("/api/employee-observation/" + job["id"], headers=h("worker"), json=body).status_code == 200
    assert c.post("/api/employee-observation/" + job["id"], headers=h("worker"), json=body).status_code == 409
    assert (
        c.post(
            "/api/demonstrations/" + job["id"] + "/finish",
            headers=h("developer"),
            json={"text": "The displayed invoice was inspected; no write demonstrated"},
        ).status_code
        == 200
    )
    from eas_harness.skill_library import SkillLibrary
    from eas_harness.maintenance import demonstration_evidence, admit

    library = SkillLibrary(tmp_path / "edge")
    with app.state.store.db() as db:
        episode = app.state.store.learning_episode(db, job["id"])
    evidence, version = demonstration_evidence(episode, library)
    assert evidence["steps"] == [] and episode["approvals"] == []
    from eas_harness.maintenance import subprocess_json

    result = subprocess_json("eas_harness.learner_process", {"evidence": evidence, "model_mode": "simulated"})
    candidate = result["result"]["candidate"]
    assert admit(library, candidate, evidence, version)["status"] == "activated"
    candidate["steps"] = ["validate", "establish", "compare", "report", "complete"]
    with pytest.raises(ValueError, match="steps or evidence"):
        admit(library, candidate, evidence, version)
    assert app.state.security.workforce.get("development-desktop")["state"] == "shadowing"


def test_observer_has_no_actuator_and_does_not_promote_itself(monkeypatch):
    from eas_harness.shadow import ShadowObserver

    calls = []
    job = {"id": "demo", "task": "Explain task", "shadow_frames": 0, "shadow_reviews": 0}
    events = [{"kind": "shadow_observation", "seq": 1, "data": {}}]

    class Screen:
        def __init__(self, *args):
            pass

        def close(self):
            pass

        def capture(self):
            return Observation(
                revision="one", timestamp=time.time(), screenshot="test.png", state={}
            ), "data:image/jpeg;base64,AA=="

    def infer(*args, **kwargs):
        assert kwargs["model_key"] is False
        return {
            "result": {"observation": "Simulated note", "question": "What indicates success?"},
            "usage": {},
        }

    observer = ShadowObserver(
        SimpleNamespace(model_mode="simulated", model_provider="", model_id=""),
        SimpleNamespace(job_id=None),
        Screen,
        infer,
    )

    def call(path, body):
        calls.append((path, body))
        return {"job": job, "events": events} if path.endswith("poll") else {"ok": True}

    observer.call = call
    observer.tick()
    assert all(path.startswith("/api/employee-observation") for path, _ in calls)
    assert any("notes" in body for _, body in calls)


def test_historical_policy_never_gains_autonomous_authority(employees):
    app, c, h = employees
    state(employees, "active").raise_for_status()
    job = c.post("/api/jobs", headers=h("staff"), json={"invoice_id": "INV-1042"}).json()
    job.update(execution_policy=2, selected_mode="strict", effective_mode="strict")
    with app.state.store.db() as db:
        db.execute("UPDATE jobs SET data=? WHERE id=?", (json.dumps(job), job["id"]))
    app.state.security.workforce.sync()
    assert app.state.store.get_job(job["id"])["status"] == "cancelled"


def test_failed_observer_attempts_consume_budget_and_session_expires(employees):
    app, c, h = employees
    job = demonstrate(employees)
    capture(employees, job)
    path = "/api/employee-observation/" + job["id"]
    for index in range(12):
        c.post(
            "/api/demonstrations/" + job["id"] + "/messages",
            headers=h("developer"),
            json={"text": f"Simulated explanation {index}"},
        ).raise_for_status()
        seq = app.state.store.events(job["id"])[-1]["seq"]
        body = {"reserve_review": True, "review_seq": seq, "model_mode": "simulated"}
        c.post(path, headers=h("worker"), json=body).raise_for_status()
        assert c.post(path, headers=h("worker"), json=body).status_code >= 400
        # No result is submitted: failures still count as model attempts.
    assert c.post(path, headers=h("worker"), json={**body, "review_seq": seq + 1}).status_code >= 400
    current = app.state.store.get_job(job["id"])
    assert current["shadow_reviews"] == 12
    with app.state.store.db() as db:
        current["started_at"] = time.time() - current["timeout"] - 1
        app.state.store._put(db, current)
    assert c.post("/api/employee-observation/poll", headers=h("worker"), json={}).json() is None
    assert app.state.store.get_job(job["id"])["status"] == "cancelled"


def test_finished_demonstration_flows_through_admission_and_publication(employees, tmp_path):
    from eas_harness.config import Settings as EdgeSettings
    from eas_harness.remote import RemoteStore
    from eas_harness.maintenance import maintain

    app, c, h = employees
    job = demonstrate(employees)
    capture(employees, job)
    c.post(
        "/api/demonstrations/" + job["id"] + "/messages",
        headers=h("developer"),
        json={"text": "Open the requested invoice and read only its displayed total."},
    ).raise_for_status()
    c.post(
        "/api/demonstrations/" + job["id"] + "/finish",
        headers=h("developer"),
        json={
            "text": "Simulated mentor confirms the displayed total was inspected without changing the record."
        },
    ).raise_for_status()
    remote = RemoteStore("http://testserver", "unused")
    remote.client.close()
    remote.client = TestClient(app, headers=h("admission"))
    try:
        maintain(
            EdgeSettings(data_dir=tmp_path / "published-edge", model_mode="simulated", learning_enabled=True),
            remote,
            "development-desktop",
        )
        packages = app.state.store.learning_status()["registries"]
        versions = [v for r in packages for v in r["versions"] if job["id"] in v.get("evidence_ids", [])]
        assert len(versions) == 1, app.state.store.learning_status()["queue"]
        assert versions[0]["steps"] == [] and versions[0]["active"]
        assert app.state.security.workforce.get("development-desktop")["state"] == "shadowing"
    finally:
        remote.client.close()
