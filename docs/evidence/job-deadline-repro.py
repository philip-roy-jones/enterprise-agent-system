"""Focused original-prompt audit probes; all jobs, staff and models are simulated."""

import json
import time
from pathlib import Path
import pytest
from conftest import pending


@pytest.mark.parametrize("waiting", ["fallback", "takeover"])
def test_job_deadline_while_waiting(browser_server, waiting):
    ctx = browser_server
    c, store = ctx["client"], ctx["store"]
    args = {"invoice_id": "INV-1042", "selected_mode": "auto" if waiting == "fallback" else "strict"}
    if waiting == "fallback":
        args["task"] = "Inspect this invoice without changing it"
    created = c.post("/api/jobs", json=args)
    created.raise_for_status()
    job_id = created.json()["id"]
    approval = pending(c, job_id)
    if waiting == "fallback":
        assert approval["kind"] == "tool"
    else:
        lease = store.lease()
        store.transfer(job_id, "staff", lease["epoch"])
    # Advance this isolated job's elapsed clock beyond its budget. No real sleep
    # or live data is involved; worker and backend are real separate processes.
    with store.db() as db:
        job = store._job(db, job_id)
        job["started_at"] = time.time() - job["timeout"] - 5
        store._put(db, job)
    time.sleep(2)
    after = c.get("/api/jobs/" + job_id).json()
    evidence = {
        "waiting": waiting,
        "status": after["job"]["status"],
        "elapsed": time.time() - after["job"]["started_at"],
        "timeout": after["job"]["timeout"],
        "worker_alive": ctx["worker"].poll() is None,
        "pending_approvals": [a["name"] for a in after["approvals"] if a["status"] == "pending"],
    }
    Path("runtime").mkdir(exist_ok=True)
    Path("runtime/recheck-" + waiting + ".json").write_text(json.dumps(evidence, indent=2) + "\n")
    assert after["job"]["status"] == "failed", evidence
