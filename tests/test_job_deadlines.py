"""Deadlines across real processes, using a deliberately held simulated worker."""

import signal
import time
import pytest
from conftest import wait_for
from eas_server.store import desktop_context


@pytest.mark.parametrize("owner", ["script", "assistant", "staff"])
def test_job_deadline_while_waiting(browser_server, owner):
    client, store = browser_server["client"], browser_server["store"]
    worker = browser_server["worker"]
    worker.send_signal(signal.SIGSTOP)
    try:
        created = client.post("/api/jobs", json={"invoice_id": "INV-1042"})
        created.raise_for_status()
        job_id = created.json()["id"]
        token = desktop_context.set("development-desktop")
        try:
            store.claim("simulated-deadline-fixture")
            if owner != "script":
                store.transfer(job_id, owner)
            with store.db() as db:
                job = store._job(db, job_id)
                job["started_at"] = time.time() - job["timeout"] - 5
                store._put(db, job)
                lease = store._lease(db, job)
                lease["expires"] = 0
                store._set_lease(db, lease)
        finally:
            desktop_context.reset(token)
    finally:
        worker.send_signal(signal.SIGCONT)
    after = wait_for(client, job_id, lambda data: data["job"]["status"] == "failed", timeout=10)
    assert after["job"]["error"] == "Execution time budget exceeded"
    assert after["job"]["ended_at"] >= after["job"]["started_at"] + after["job"]["timeout"]
    assert after["job"]["mutation"] == "not_attempted"
    assert not after["approvals"]
    assert worker.poll() is None
    next_job = client.post("/api/jobs", json={"invoice_id": "INV-1043"})
    next_job.raise_for_status()
    next_id = next_job.json()["id"]
    wait_for(client, next_id, lambda data: data["job"]["status"] == "running")
    assert store.lease()["job_id"] == next_id
    client.post(f"/api/jobs/{next_id}/cancel").raise_for_status()
