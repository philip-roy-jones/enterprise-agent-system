import pytest
from fastapi.testclient import TestClient
from enterprise.server.backend import create_app
from enterprise.shared.config import Settings
from enterprise.server.evaluation import assess_action, assessment_metrics
from enterprise.shared.types import JobInput


def finished_action(store, job_id, invocation="operation"):
    store.event(job_id, "action_started", {"invocation": invocation, "action": {"name": "prepare"}})
    store.event(job_id, "action_result", {"invocation": invocation, "result": {"prepared": True}})


def test_unassessed_actions_are_not_reported_as_verified_correct(store, job):
    finished_action(store, job["id"])
    assert assessment_metrics(store.events(job["id"])) == {
        "incorrect_actions_reported": 0,
        "assessed_actions": 0,
        "unassessed_actions": 1,
    }
    report = {
        "invocation": "operation",
        "outcome": "incorrect",
        "explanation": "The note was entered in the wrong field",
    }
    assess_action(store, job["id"], report)
    assess_action(store, job["id"], report)
    assert assessment_metrics(store.events(job["id"]))["incorrect_actions_reported"] == 1
    assert sum(e["kind"] == "action_assessment" for e in store.events(job["id"])) == 1
    assess_action(
        store,
        job["id"],
        dict(report, outcome="correct", explanation="Reviewed the evidence and corrected my assessment"),
    )
    assert assessment_metrics(store.events(job["id"])) == {
        "incorrect_actions_reported": 0,
        "assessed_actions": 1,
        "unassessed_actions": 0,
    }


def test_assessment_cannot_claim_an_unexecuted_or_foreign_operation(store, job):
    other = store.create_job(JobInput(invoice_id="INV-1043").model_dump())
    finished_action(store, other["id"])
    with pytest.raises(ValueError, match="belonging to this job"):
        assess_action(
            store, job["id"], {"invocation": "operation", "outcome": "correct", "explanation": "Wrong job"}
        )


def test_reported_error_revokes_acceptance_and_blocks_teaching(store, job):
    finished_action(store, job["id"])
    store.update_job(job["id"], {"status": "completed"})
    store.accept(job["id"])
    assess_action(
        store,
        job["id"],
        {"invocation": "operation", "outcome": "incorrect", "explanation": "Observed an error"},
    )
    assert not store.get_job(job["id"])["accepted"]
    with pytest.raises(ValueError, match="incorrect operations"):
        store.accept(job["id"])


def test_only_staff_can_assess_and_metrics_separate_model_modes(tmp_path):
    settings = Settings(data_dir=tmp_path)
    app = create_app(settings)
    store = app.state.store
    job = store.create_job(JobInput(invoice_id="INV-1042").model_dump(), "simulated")
    finished_action(store, job["id"])
    payload = {"invocation": "operation", "outcome": "incorrect", "explanation": "Test assessment"}
    with TestClient(app) as c:
        assert (
            c.post(
                f"/api/jobs/{job['id']}/assessments",
                json=payload,
                headers={"Authorization": f"Bearer {settings.worker_token}"},
            ).status_code
            == 403
        )
        c.headers["Authorization"] = f"Bearer {settings.staff_token}"
        assert c.post(f"/api/jobs/{job['id']}/assessments", json=payload).status_code == 200
        metrics = c.get("/api/metrics").json()
        assert metrics["simulated"]["incorrect_actions_reported"] == 1
        assert metrics["live"]["incorrect_actions_reported"] == 0


@pytest.mark.parametrize("status", ["cancelled", "failed", "denied", "rejected", "completed"])
def test_terminal_timing_includes_unsuccessful_runs_and_does_not_grow_later(store, job, monkeypatch, status):
    started = store.get_job(job["id"])["started_at"]
    monkeypatch.setattr("enterprise.server.store.time.time", lambda: started + 12.5)
    if status == "cancelled":
        result = store.stop(job["id"])
    else:
        result = store.update_job(job["id"], {"status": status})
    assert result["elapsed_seconds"] == 12.5
    assert result["ended_at"] == started + 12.5
    monkeypatch.setattr("enterprise.server.store.time.time", lambda: started + 100)
    if status == "completed":
        assert store.accept(job["id"])["elapsed_seconds"] == 12.5
    else:
        assert store.stop(job["id"])["elapsed_seconds"] == 12.5
