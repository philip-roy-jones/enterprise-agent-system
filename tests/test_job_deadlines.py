"""Job deadlines across real worker/backend processes; model and staff are simulated."""

import time

import pytest

from conftest import pending, wait_for


@pytest.mark.parametrize("waiting", ["fallback", "takeover", "strict"])
def test_job_deadline_while_waiting(browser_server, waiting):
    client, store = browser_server["client"], browser_server["store"]
    args = {"invoice_id": "INV-1042", "selected_mode": "auto" if waiting == "fallback" else "strict"}
    if waiting == "fallback":
        args["task"] = "Inspect this invoice without changing it"
    created = client.post("/api/jobs", json=args)
    created.raise_for_status()
    job_id = created.json()["id"]
    approval = pending(client, job_id)
    assert approval["kind"] == ("tool" if waiting == "fallback" else "node")
    if waiting == "takeover":
        store.transfer(job_id, "staff", store.lease()["epoch"])

    # Advance only this synthetic job's elapsed clock; keep real polling and RPC.
    with store.db() as db:
        job = store._job(db, job_id)
        job["started_at"] = time.time() - job["timeout"] - 5
        store._put(db, job)

    after = wait_for(client, job_id, lambda data: data["job"]["status"] == "failed", timeout=5)
    assert after["job"]["error"] == "Execution time budget exceeded"
    assert after["job"]["ended_at"] >= after["job"]["started_at"] + after["job"]["timeout"]
    assert after["job"]["mutation"] == "not_attempted"
    assert all(a["status"] == "stale" for a in after["approvals"])
    assert browser_server["worker"].poll() is None

    # Expiration must free the desktop job slot for the next queued job.
    next_job = client.post("/api/jobs", json={"invoice_id": "INV-1043", "selected_mode": "strict"})
    next_job.raise_for_status()
    next_id = next_job.json()["id"]
    assert pending(client, next_id)["kind"] == "node"
    assert store.lease()["job_id"] == next_id
    client.post(f"/api/jobs/{next_id}/cancel").raise_for_status()
