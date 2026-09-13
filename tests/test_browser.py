"""Strict coordinator and workflow recovery through real browser processes.

Model behavior and staff decisions are simulated. Historical graph-first/Auto
expectations are superseded by the agent-led plan; authority coverage remains.
"""

import json
import subprocess
import sys
import time
import pytest
from enterprise_dev.demo import drive
from eas_shared.identity import canonical
from conftest import pending

pytestmark = pytest.mark.browser


def create(client, mode="strict", invoice="INV-1042", **extra):
    response = client.post("/api/jobs", json={"invoice_id": invoice, "selected_mode": mode, **extra})
    response.raise_for_status()
    return response.json()["id"]


def until(client, job, name=None, status=None):
    end = time.monotonic() + 75
    while time.monotonic() < end:
        data = client.get("/api/jobs/" + job).json()
        if data["job"]["status"] == status:
            return data
        for approval in data["approvals"]:
            if approval["status"] == "pending":
                if approval["name"] == name:
                    return approval
                client.post(
                    "/api/approvals/" + approval["id"],
                    json={"decision": "approve", "explanation": "Simulated staff"},
                ).raise_for_status()
        assert data["job"]["status"] not in {"failed", "denied", "cancelled", "completed", "rejected"}, data[
            "job"
        ]
        time.sleep(0.1)
    raise AssertionError(data["job"])


def test_explicit_save_rejection_requires_approved_retry(browser_server):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json={"reject_save": True}).raise_for_status()
    job = create(c)
    approval = until(c, job, "resume_workflow")
    assert c.get("/api/jobs/" + job).json()["job"]["mutation"] == "confirmed_failed"
    assert not any(d["operation_id"] == job for d in c.get("/api/mock/state").json()["drafts"])
    result = drive(c, job)
    assert result["job"]["mutation"] == "confirmed_succeeded"
    assert len([a for a in result["approvals"] if a["name"] == "save"]) == 2
    assert approval["decision"] is None


def test_strict_gates_every_executable_node(browser_server):
    c = browser_server["client"]
    job = create(c)
    a = pending(c, job)
    time.sleep(0.4)
    assert not any(e["kind"] == "action_started" for e in c.get("/api/jobs/" + job).json()["events"])
    assert a["name"] == "read_skill"
    result = drive(c, job)
    assert [a["name"] for a in result["approvals"] if a["status"] == "executed"] == [
        "read_skill",
        "run_workflow",
        "validate",
        "establish",
        "compare",
        "prepare",
        "save",
        "verify",
        "complete",
    ]
    assert result["job"]["model_calls"] > 0


def test_unmatched_request_stays_supervised_without_workflow_creation(browser_server):
    c = browser_server["client"]
    job = create(c, task="Inspect this invoice and explain what needs attention without saving")
    assert pending(c, job)["name"] == "validate"
    result = drive(c, job)
    assert result["job"]["verified_report"]
    assert result["job"]["mutation"] == "not_attempted"
    assert not result["job"].get("workflow_runs")
    assert all(a["decision"] for a in result["approvals"])


def test_guidance_does_not_release_pending_action(browser_server):
    c = browser_server["client"]
    job = create(c)
    first = pending(c, job)
    c.post(
        f"/api/jobs/{job}/messages",
        json={
            "text": "Check the current label before entering the correction.",
            "message_id": "browser-guidance",
        },
    ).raise_for_status()
    data = c.get("/api/jobs/" + job).json()
    assert not any(e["kind"] == "action_started" for e in data["events"])
    result = drive(c, job)
    assert any(
        e["kind"] == "conversation_context" and e["data"]["message_sequences"] for e in result["events"]
    )
    assert next(a for a in result["approvals"] if a["id"] == first["id"])["status"] == "stale"


@pytest.mark.parametrize(
    "scenario",
    [
        {"view": "dashboard"},
        {"view": "purchase_orders"},
        {"view": "invoice", "invoice_id": "INV-1044"},
        {"view": "invoices", "reordered": True},
        {"delay_seconds": 2},
        {"dialog": "info"},
        {"company_id": "OTHER"},
        {"variant": "layout"},
    ],
)
def test_navigation_and_recovery_remain_strict(browser_server, scenario):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json=scenario).raise_for_status()
    job = create(c)
    result = drive(c, job)
    assert all(a.get("decision") for a in result["approvals"] if a["status"] == "executed")
    draft = next(d for d in c.get("/api/mock/state").json()["drafts"] if d["operation_id"] == job)
    assert draft["invoice_id"] == "INV-1042" and draft["amount"] == 128000


@pytest.mark.parametrize(
    "scenario",
    [
        {"dialog": "unfamiliar"},
        {"dialog": "unsaved", "unsaved": True, "view": "invoice", "invoice_id": "INV-1044"},
        {"variant": "renamed"},
    ],
)
def test_workflow_recovery_tools_need_separate_approvals(browser_server, scenario):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json=scenario).raise_for_status()
    job = create(c)
    result = drive(c, job, correction=True)
    names = [a["name"] for a in result["approvals"] if a["status"] == "executed"]
    assert "observe_app" in names and "resume_workflow" in names
    assert result["job"]["effective_mode"] == "strict"
    assert len([d for d in c.get("/api/mock/state").json()["drafts"] if d["operation_id"] == job]) == 1


def test_auto_request_does_not_release_pending_tool(browser_server):
    c = browser_server["client"]
    job = create(c)
    a = pending(c, job)
    assert c.post(f"/api/jobs/{job}/mode", json={"mode": "auto"}).status_code == 409
    time.sleep(0.3)
    assert (
        next(x for x in c.get("/api/jobs/" + job).json()["approvals"] if x["id"] == a["id"])["status"]
        == "pending"
    )


def test_screenshot_target_correction_has_separate_audit(browser_server):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json={"dialog": "unfamiliar"})
    job = create(c)
    a = until(c, job, "click")
    target = next(t for t in a["observation"]["targets"] if t["target"] == "dialog-review")
    args = {"x": target["x"], "y": target["y"]}
    c.post(
        "/api/approvals/" + a["id"],
        json={
            "decision": "correct",
            "arguments": args,
            "explanation": "Simulated staff selected the reviewed control",
        },
    ).raise_for_status()
    result = drive(c, job)
    executed = next(x for x in result["approvals"] if x["id"] == a["id"])
    assert executed["arguments"] != args
    assert executed["executed_action"]["arguments"] == args
    assert executed["observed_result"]["value"]["clicked"] == "dialog-review"


def test_stale_observation_after_takeover_needs_new_approval(browser_server):
    c = browser_server["client"]
    job = create(c)
    a = pending(c, job)
    c.post(f"/api/jobs/{job}/takeover").raise_for_status()
    c.post("/api/mock/scenario", json={"view": "invoices", "reordered": True}).raise_for_status()
    assert c.post("/api/approvals/" + a["id"], json={"decision": "approve"}).status_code == 409
    c.post(f"/api/jobs/{job}/release").raise_for_status()
    assert pending(c, job)["id"] != a["id"]
    drive(c, job)


def test_permission_denial_has_no_agent_escape(browser_server):
    c = browser_server["client"]
    job = create(c, permissions=["read", "navigate"])
    d = until(c, job, status="denied")
    assert d["job"]["mutation"] == "not_attempted"
    assert not any(a["name"] == "save" for a in d["approvals"])


def test_rejection_terminates_nested_workflow(browser_server):
    c = browser_server["client"]
    job = create(c)
    a = until(c, job, "prepare")
    c.post("/api/approvals/" + a["id"], json={"decision": "reject"}).raise_for_status()
    d = c.get("/api/jobs/" + job).json()
    assert d["job"]["status"] == "rejected"
    time.sleep(0.5)
    assert not any(a["name"] == "save" for a in c.get("/api/jobs/" + job).json()["approvals"])


def test_correction_cannot_expand_scope(browser_server):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json={"variant": "renamed"})
    job = create(c)
    a = until(c, job, "set_field")
    response = c.post(
        "/api/approvals/" + a["id"],
        json={"decision": "correct", "arguments": {"field": "bank_account", "value": "hijack"}},
    )
    assert response.status_code == 200  # Preserve the attempted correction in the audit.
    data = until(c, job, status="denied")
    assert data["job"]["mutation"] == "not_attempted"
    assert not any(
        e["kind"] == "action_started" and e["data"]["invocation"] == a["invocation"] for e in data["events"]
    )


def restart(ctx):
    ctx["worker"].kill()
    ctx["worker"].wait()
    with ctx["store"].db() as db:
        lease = json.loads(db.execute("SELECT data FROM lease").fetchone()[0])
        lease["expires"] = 0
        db.execute("UPDATE lease SET data=?", (canonical(lease),))
    ctx["worker"] = subprocess.Popen(
        [sys.executable, "-m", "eas_harness"],
        env=ctx["env"],
        cwd=ctx["root"],
        stdout=ctx["worker_log"],
        stderr=ctx["worker_log"],
    )


def test_restart_after_ambiguous_save_never_saves_twice(browser_server):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json={"interrupt_save": True})
    job = create(c)
    until(c, job, "resume_workflow")
    before = c.get("/api/mock/state").json()["save_requests"]
    assert c.get("/api/jobs/" + job).json()["job"]["mutation"] == "attempted_uncertain"
    restart(browser_server)
    result = drive(c, job)
    assert result["job"]["mutation"] == "confirmed_succeeded"
    assert c.get("/api/mock/state").json()["save_requests"] == before
