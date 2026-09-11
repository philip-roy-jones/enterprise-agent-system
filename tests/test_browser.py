import subprocess
import sys
import time
import pytest
from enterprise.demo import drive
from enterprise.store import canonical
from enterprise.procedures import AMOUNT_LABELS
from conftest import pending, wait_for

pytestmark = pytest.mark.browser


def create(client, mode="auto", invoice="INV-1042", **extra):
    r = client.post("/api/jobs", json={"invoice_id": invoice, "selected_mode": mode, **extra})
    r.raise_for_status()
    return r.json()["id"]


def test_strict_gates_every_executable_node(browser_server):
    c = browser_server["client"]
    job = create(c, "strict")
    a = pending(c, job)
    time.sleep(0.4)
    data = c.get("/api/jobs/" + job).json()
    assert not any(e["kind"] == "action_started" for e in data["events"])
    assert a["name"] == "validate"
    result = drive(c, job)
    assert [a["name"] for a in result["approvals"] if a["status"] == "executed"] == [
        "validate",
        "establish",
        "compare",
        "prepare",
        "save",
        "verify",
        "complete",
    ]
    assert result["job"]["model_calls"] == 0


def test_unmatched_request_enters_fallback_without_a_create_workflow_step(browser_server):
    c = browser_server["client"]
    job = create(c, "auto", task="Inspect this invoice and explain what needs attention without saving")
    approval = pending(c, job)
    assert approval["kind"] == "tool" and approval["name"] == "observe_app"
    data = c.get("/api/jobs/" + job).json()
    assert data["job"]["effective_mode"] == "strict"
    assert not data["job"]["completed"]
    trigger = next(e["data"]["trigger"] for e in data["events"] if e["kind"] == "fallback_started")
    assert trigger == "missing_procedure"
    result = drive(c, job)
    assert result["job"]["mutation"] == "not_attempted"
    assert result["job"]["effective_mode"] == "auto"
    assert result["job"]["assistant_report"]
    assert result["approvals"][-1]["name"] == "review_discovery"
    assert not any(d["operation_id"] == job for d in c.get("/api/mock/state").json()["drafts"])


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
def test_auto_navigation_and_known_recovery(browser_server, scenario):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json=scenario).raise_for_status()
    job = create(c)
    result = drive(c, job)
    assert result["approvals"] == []
    assert result["job"]["fallback_count"] == 0
    draft = next(d for d in c.get("/api/mock/state").json()["drafts"] if d["operation_id"] == job)
    assert draft["invoice_id"] == "INV-1042" and draft["amount"] == 128000


@pytest.mark.parametrize("mode", ["auto", "strict"])
@pytest.mark.parametrize(
    "scenario",
    [
        {"dialog": "unfamiliar"},
        {"dialog": "unsaved", "unsaved": True, "view": "invoice", "invoice_id": "INV-1044"},
        {"variant": "renamed"},
    ],
)
def test_fallback_strict_tools_and_mode_restoration(browser_server, mode, scenario):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json=scenario).raise_for_status()
    job = create(c, mode)
    result = drive(c, job, correction=True)
    tool_approvals = [a for a in result["approvals"] if a["kind"] == "tool" and a["status"] == "executed"]
    assert tool_approvals and tool_approvals[0]["name"] == "observe_app"
    assert all(a["decision"] for a in tool_approvals)
    assert result["job"]["effective_mode"] == mode
    assert result["job"]["fallback_count"] == 1
    assert len([d for d in c.get("/api/mock/state").json()["drafts"] if d["operation_id"] == job]) == 1


def test_mode_switch_does_not_release_pending_tool(browser_server):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json={"dialog": "unfamiliar"})
    job = create(c)
    a = pending(c, job)
    assert a["kind"] == "tool" and a["name"] == "observe_app"
    c.post(f"/api/jobs/{job}/mode", json={"mode": "auto"})
    time.sleep(0.7)
    d = c.get("/api/jobs/" + job).json()
    assert next(x for x in d["approvals"] if x["id"] == a["id"])["status"] == "pending"
    assert d["job"]["effective_mode"] == "strict"
    drive(c, job)


def test_screenshot_target_correction_and_separate_audit(browser_server):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json={"dialog": "unfamiliar"})
    job = create(c)
    a = pending(c, job)
    c.post("/api/approvals/" + a["id"], json={"decision": "approve"}).raise_for_status()
    data = wait_for(
        c, job, lambda d: any(a["status"] == "pending" and a["name"] == "click" for a in d["approvals"])
    )
    a = next(a for a in data["approvals"] if a["status"] == "pending")
    target = next(t for t in a["observation"]["targets"] if t["target"] == "dialog-review")
    args = {"x": target["x"], "y": target["y"]}
    c.post(
        "/api/approvals/" + a["id"],
        json={"decision": "correct", "arguments": args, "explanation": "Staff selected the reviewed control"},
    ).raise_for_status()
    result = drive(c, job)
    executed = next(x for x in result["approvals"] if x["id"] == a["id"])
    assert executed["arguments"] != args
    assert executed["corrected_arguments"] == args
    assert executed["executed_action"]["arguments"] == args
    assert executed["observed_result"]["value"]["clicked"] == "dialog-review"


def test_stale_observation_after_staff_takeover_needs_new_approval(browser_server):
    c = browser_server["client"]
    job = create(c, "strict")
    a = pending(c, job)
    c.post(f"/api/jobs/{job}/takeover").raise_for_status()
    c.post("/api/mock/scenario", json={"view": "invoices", "reordered": True}).raise_for_status()
    assert c.post("/api/approvals/" + a["id"], json={"decision": "approve"}).status_code == 409
    c.post(f"/api/jobs/{job}/release").raise_for_status()
    fresh = pending(c, job)
    assert fresh["id"] != a["id"]
    drive(c, job)


@pytest.mark.parametrize("mode", ["strict", "auto"])
def test_permission_denial_has_no_assistant_escape(browser_server, mode):
    c = browser_server["client"]
    job = create(c, mode, permissions=["read", "navigate"])
    if mode == "strict":
        a = pending(c, job)
        c.post("/api/approvals/" + a["id"], json={"decision": "approve"})
    d = wait_for(c, job, lambda d: d["job"]["status"] == "denied")
    assert d["job"]["fallback_count"] == 0


def test_assistant_cannot_correct_to_out_of_scope_action(browser_server):
    c = browser_server["client"]
    c.post("/api/mock/scenario", json={"variant": "renamed"})
    job = create(c)
    a = pending(c, job)
    c.post("/api/approvals/" + a["id"], json={"decision": "approve"})
    d = wait_for(
        c, job, lambda d: any(a["status"] == "pending" and a["name"] == "set_field" for a in d["approvals"])
    )
    a = next(a for a in d["approvals"] if a["status"] == "pending")
    c.post(
        "/api/approvals/" + a["id"],
        json={"decision": "correct", "arguments": {"field": "bank_account", "value": "hijack"}},
    )
    d = wait_for(c, job, lambda d: d["job"]["status"] == "denied")
    assert d["job"]["mutation"] == "not_attempted"


def test_restart_after_ambiguous_save_reconciles_without_second_save(browser_server):
    ctx = browser_server
    c = ctx["client"]
    c.post("/api/mock/scenario", json={"interrupt_save": True})
    job = create(c, "strict")
    while True:
        a = pending(c, job)
        if a["name"] == "resume":
            break
        c.post("/api/approvals/" + a["id"], json={"decision": "approve"}).raise_for_status()
    before = c.get("/api/mock/state").json()["save_requests"]
    assert c.get("/api/jobs/" + job).json()["job"]["mutation"] == "attempted_uncertain"
    ctx["worker"].kill()
    ctx["worker"].wait()
    # Advance only the synthetic lease clock, equivalent to waiting for the crash lease to expire.
    with ctx["store"].db() as db:
        import json

        lease = json.loads(db.execute("SELECT data FROM lease").fetchone()[0])
        lease["expires"] = 0
        db.execute("UPDATE lease SET data=?", (canonical(lease),))
    ctx["worker"] = subprocess.Popen(
        [sys.executable, "-m", "enterprise.cli", "worker"],
        env=ctx["env"],
        cwd=ctx["root"],
        stdout=ctx["worker_log"],
        stderr=ctx["worker_log"],
    )
    result = drive(c, job)
    assert result["job"]["mutation"] == "confirmed_succeeded"
    assert c.get("/api/mock/state").json()["save_requests"] == before


@pytest.mark.parametrize("invoice,variant", [("INV-1043", "renamed"), ("INV-1044", "layout")])
def test_improved_library_on_new_record(browser_server, invoice, variant):
    if len(AMOUNT_LABELS) < 2:
        pytest.skip("Candidate-only regression; improvement checkout enables reviewed labels")
    ctx = browser_server
    c = ctx["client"]
    ctx["store"].put_value("release", {"version": "v2", "labels": list(AMOUNT_LABELS), "previous": None})
    c.post("/api/mock/scenario", json={"variant": variant, "view": "invoices", "reordered": True})
    result = drive(c, create(c, invoice=invoice))
    assert result["job"]["fallback_count"] == 0
    assert result["job"]["graph_version"] == "v2"
