"""Autonomous coordinator and workflow recovery through real browser processes.

Model behavior and staff decisions are simulated. Historical graph-first/Auto
expectations are superseded by the agent-led plan; authority coverage remains.
"""

import subprocess
import sys
import time
import pytest
from enterprise_dev.demo import drive
from conftest import wait_for

pytestmark = pytest.mark.browser


def create(client, mode="auto", invoice="INV-1042", **extra):
    response = client.post("/api/jobs", json={"invoice_id": invoice, "selected_mode": mode, **extra})
    response.raise_for_status()
    return response.json()["id"]


def until(client, job, name=None, status=None):
    end = time.monotonic() + 75
    while time.monotonic() < end:
        data = client.get("/api/jobs/" + job).json()
        if data["job"]["status"] == status:
            return data
        for record in data["approvals"]:
            if record["name"] == name:
                return record
        assert data["job"]["status"] not in {"failed", "denied", "cancelled", "completed", "rejected"}, data[
            "job"
        ]
        time.sleep(0.1)
    raise AssertionError(data["job"])


def test_explicit_save_rejection_requires_approved_retry(browser_server):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json={"reject_save": True}).raise_for_status()
    job = create(c)
    result = drive(c, job)
    assert result["job"]["mutation"] == "confirmed_succeeded"
    assert len([a for a in result["approvals"] if a["name"] == "save"]) == 2
    assert all(a["decision"] is None for a in result["approvals"])


def test_auto_authorizes_every_executable_node(browser_server):
    c = browser_server["client"]
    job = create(c)
    result = drive(c, job)
    assert [a["name"] for a in result["approvals"] if a["status"] == "executed"] == [
        "read_skill",
        "run_skill",
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
    result = drive(c, job)
    assert result["job"]["verified_report"]
    assert result["job"]["mutation"] == "not_attempted"
    assert not result["job"].get("skill_runs")
    assert all(a["authorization"] and a["decision"] is None for a in result["approvals"])


def test_chat_guidance_is_seen_by_autonomous_employee(browser_server):
    c = browser_server["client"]
    job = create(c)
    c.post(
        f"/api/jobs/{job}/messages",
        json={
            "text": "Check the current label before entering the correction.",
            "message_id": "browser-guidance",
        },
    ).raise_for_status()
    result = drive(c, job)
    assert any(
        e["kind"] == "conversation_context" and e["data"]["message_sequences"] for e in result["events"]
    )
    assert not any(e["kind"] == "staff_decision" for e in result["events"])


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
def test_navigation_and_recovery_remain_authorized(browser_server, scenario):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json=scenario).raise_for_status()
    job = create(c)
    result = drive(c, job)
    assert all(
        a.get("authorization") and not a.get("decision")
        for a in result["approvals"]
        if a["status"] == "executed"
    )
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
def test_workflow_recovery_tools_get_separate_authorizations(browser_server, scenario):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json=scenario).raise_for_status()
    job = create(c)
    result = drive(c, job, correction=True)
    names = [a["name"] for a in result["approvals"] if a["status"] == "executed"]
    assert "observe_app" in names and "resume_skill" in names
    assert result["job"]["effective_mode"] == "auto"
    assert len([d for d in c.get("/api/mock/state").json()["drafts"] if d["operation_id"] == job]) == 1


def test_strict_cannot_be_selected_for_new_work(browser_server):
    c = browser_server["client"]
    assert c.post("/api/jobs", json={"invoice_id": "INV-1042", "selected_mode": "strict"}).status_code == 422


def test_recovery_click_has_bound_observation_and_receipt(browser_server):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json={"dialog": "unfamiliar"}).raise_for_status()
    result = drive(c, create(c))
    click = next(a for a in result["approvals"] if a["name"] == "click" and a["status"] == "executed")
    assert click["observed_result"]["value"]["clicked"] == "dialog-review"
    assert click["executed_action"]["observation_revision"] == click["observation"]["revision"]
    assert click["decision"] is None and click["authorization"]


def test_pause_cancels_work_and_resumption_requires_new_request(browser_server):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json={"delay_seconds": 2}).raise_for_status()
    job = create(c)
    wait_for(c, job, lambda d: d["job"]["status"] == "running")
    r = c.post(
        "/api/employees/development-desktop/state",
        headers={"Authorization": "Bearer test-developer"},
        json={"state": "paused", "reason": "Simulated supervisor stop"},
    )
    r.raise_for_status()
    assert c.get("/api/jobs/" + job).json()["job"]["status"] == "cancelled"
    assert c.post("/api/jobs", json={"invoice_id": "INV-1042"}).status_code == 403
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        r = c.post(
            "/api/employees/development-desktop/state",
            headers={"Authorization": "Bearer test-developer"},
            json={"state": "active", "reason": "Simulated reassessment after stop"},
        )
        if r.is_success:
            break
        time.sleep(0.1)
    r.raise_for_status()
    assert c.get("/api/jobs/" + job).json()["job"]["status"] == "cancelled"


def test_permission_denial_has_no_agent_escape(browser_server):
    c = browser_server["client"]
    job = create(c, permissions=["read", "navigate"])
    d = until(c, job, status="denied")
    assert d["job"]["mutation"] == "not_attempted"
    assert not any(a["name"] == "save" for a in d["approvals"])


def test_cancel_terminates_autonomous_request(browser_server):
    c = browser_server["client"]
    job = create(c)
    c.post(f"/api/jobs/{job}/cancel").raise_for_status()
    time.sleep(0.5)
    d = c.get("/api/jobs/" + job).json()
    assert d["job"]["status"] == "cancelled"
    assert not any(a["name"] == "save" for a in d["approvals"])


def test_request_cannot_expand_employee_permissions(browser_server):
    c = browser_server["client"]
    r = c.post("/api/jobs", json={"invoice_id": "INV-1042", "permissions": ["read", "payroll_admin"]})
    assert r.status_code >= 400


def restart(ctx):
    ctx["worker"].kill()
    ctx["worker"].wait()
    with ctx["store"].db() as db:
        lease = ctx["store"]._lease(db)
        lease["expires"] = 0
        ctx["store"]._set_lease(db, lease)
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
    until(c, job, "resume_skill")
    before = c.get("/api/mock/state").json()["save_requests"]
    restart(browser_server)
    result = drive(c, job)
    assert result["job"]["mutation"] == "confirmed_succeeded"
    assert c.get("/api/mock/state").json()["save_requests"] == before
