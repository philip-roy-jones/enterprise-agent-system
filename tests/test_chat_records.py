"""Natural-language target proposals retain exact, stateful business authority."""

import time
import pytest
from eas_shared.types import JobInput, Recovery, Stopped
from eas_harness.execution import ExecutionLayer
from eas_harness.errors import Paused
from conftest import pending
from test_agent_led import finish


class NoDesktop:
    def observe(self):
        raise AssertionError("Resolving chat scope must not read or activate the desktop")


@pytest.fixture
def unbound(store):
    payload = JobInput(
        task="Report invoice INV-1043", conversation_id="record-chat", request_id="record-request"
    ).model_dump()
    job = store.create_job(payload, ongoing=True)
    store.claim("record-worker")
    store.transfer(job["id"], "assistant", store.lease()["epoch"])
    return job, payload


def select(layer, job, invoice="INV-1043", invocation="select"):
    return layer.run(
        job["id"],
        invocation,
        "select_record",
        {"invoice_id": invoice},
        lambda args: layer.store.bind_record(job["id"], args["invoice_id"]),
        kind="tool",
    )


def test_record_binding_requires_exact_approved_call_and_is_retry_safe(store, unbound):
    job, payload = unbound
    layer = ExecutionLayer(store, NoDesktop())
    assert job["invoice_id"] is None and job["record_id"] is None
    with pytest.raises(PermissionError):
        store.bind_record(job["id"], "INV-1043")
    with pytest.raises(Recovery, match="No record is selected"):
        layer.run(job["id"], "click", "click", {"target": "invoice-INV-1043"}, lambda _: {}, kind="tool")
    with pytest.raises(Paused):
        select(layer, job)
    approval = store.approvals(job["id"])[0]
    assert approval["inputs"]["record_id"] == "INV-1043" and not approval["observation"]["screenshot"]
    store.decide(
        approval["id"],
        {"decision": "correct", "arguments": {"invoice_id": "INV-1044"}},
        actor="simulated-staff",
    )
    with pytest.raises(PermissionError):
        store.bind_record(job["id"], "INV-1044")  # Approved, but not executing yet.
    result = select(layer, job)
    assert result["value"]["data"]["invoice_id"] == "INV-1044"
    assert select(layer, job) == result
    assert store.create_job(payload, ongoing=True)["id"] == job["id"]
    current = store.get_job(job["id"])
    assert current["record_id"] == current["invoice_id"] == current["inputs"]["invoice_id"] == "INV-1044"
    assert current["request_payload"]["inputs"]["invoice_id"] is None
    with pytest.raises(PermissionError):
        select(layer, current, "INV-1042", "retarget")
    with pytest.raises(ValueError, match="cannot change authorization"):
        store.update_job(job["id"], {"invoice_id": "INV-1042"})
    with pytest.raises(ValueError, match="different inputs"):
        store.create_job({**payload, "task": "A different request"}, ongoing=True)


def test_denied_selection_has_no_record_or_desktop_effect(store, unbound):
    job, _ = unbound
    layer = ExecutionLayer(store, NoDesktop())
    with pytest.raises(Paused):
        select(layer, job)
    store.decide(store.approvals(job["id"])[0]["id"], {"decision": "reject"}, actor="simulated-staff")
    with pytest.raises(Stopped):
        select(layer, job)
    assert store.get_job(job["id"])["record_id"] is None


def test_binding_rpc_cannot_substitute_approved_record(store, unbound):
    job, _ = unbound
    layer = ExecutionLayer(store, NoDesktop())
    with pytest.raises(Paused):
        select(layer, job)
    approval = store.approvals(job["id"])[0]
    store.decide(approval["id"], {"decision": "approve"}, actor="simulated-staff")
    store.begin_action(
        job["id"],
        "assistant",
        store.lease()["epoch"],
        "select",
        {
            "name": "select_record",
            "arguments": {"invoice_id": "INV-1043"},
            "observation_revision": approval["observation"]["revision"],
        },
        approval["id"],
    )
    with pytest.raises(PermissionError):
        store.bind_record(job["id"], "INV-1042")
    assert store.get_job(job["id"])["record_id"] is None


def test_corrected_record_commit_survives_worker_losing_the_response(store, unbound):
    job, _ = unbound
    layer = ExecutionLayer(store, NoDesktop())
    with pytest.raises(Paused):
        select(layer, job)
    approval = store.approvals(job["id"])[0]
    store.decide(
        approval["id"],
        {"decision": "correct", "arguments": {"invoice_id": "INV-1044"}},
        actor="simulated-staff",
    )
    store.begin_action(
        job["id"],
        "assistant",
        store.lease()["epoch"],
        "select",
        {
            "name": "select_record",
            "arguments": {"invoice_id": "INV-1044"},
            "observation_revision": approval["observation"]["revision"],
        },
        approval["id"],
    )
    store.bind_record(job["id"], "INV-1044")
    # The worker loses its RPC response here, before it can do any bookkeeping.
    assert store.lease()["inflight"] is None
    assert select(ExecutionLayer(store, NoDesktop()), job)["value"]["data"]["invoice_id"] == "INV-1044"
    assert store.approvals(job["id"])[0]["status"] == "executed"
    assert len([e for e in store.events(job["id"]) if e["kind"] == "record_selected"]) == 1


def completed(client, job_id):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        data = client.get("/api/jobs/" + job_id).json()
        if data["job"]["status"] == "completed":
            return data
        assert data["job"]["status"] not in {"failed", "cancelled", "rejected", "denied"}, data["job"]
        time.sleep(0.1)
    raise AssertionError(data)


@pytest.mark.parametrize(
    "task", ["Hi", "Compare the invoice with its purchase order", "Report invoice INV-1042 or INV-1043"]
)
def test_chat_without_record_clarifies_without_business_approvals(browser_server, task):
    c = browser_server["client"]
    response = c.post("/api/chat", json={"task": task})
    response.raise_for_status()
    job = response.json()["job"]
    assert job["invoice_id"] is None and job["record_id"] is None
    data = completed(c, job["id"])
    assert data["approvals"] == [] and data["job"]["result_kind"] == "conversation"
    assert not any(
        e["kind"] in {"window_recovery_started", "action_started", "observation"} for e in data["events"]
    )
    replies = [e["data"]["text"] for e in data["events"] if e["kind"] == "assistant_message"]
    assert any("reply" in r if task == "Hi" else "which invoice" in r for r in replies)


def test_natural_language_record_is_correctable_and_active_chat_needs_no_selector(browser_server):
    ctx = browser_server
    c = ctx["client"]
    payload = {"task": "Report invoice INV-1043 without saving", "request_id": "natural-language-report"}
    response = c.post("/api/chat", json=payload)
    response.raise_for_status()
    job_id = response.json()["job"]["id"]
    approval = pending(c, job_id)
    assert approval["name"] == "select_record" and approval["arguments"] == {"invoice_id": "INV-1043"}
    ctx["store"].decide(
        approval["id"],
        {"decision": "correct", "arguments": {"invoice_id": "INV-1044"}},
        actor="simulated-staff",
    )
    approval = pending(c, job_id)
    assert approval["inputs"]["invoice_id"] == "INV-1044"
    assert c.post("/api/chat", json=payload).json()["job"]["id"] == job_id
    guidance = {"task": "Please continue without saving", "request_id": "natural-language-guidance"}
    r = c.post("/api/chat", json=guidance)
    r.raise_for_status()
    assert r.json()["kind"] == "guidance"
    data, _ = finish(ctx, job_id)
    assert data["job"]["verified_report"]["invoice_id"] == "INV-1044"
    assert data["job"]["mutation"] == "not_attempted"
    model_steps = [e["data"] for e in data["events"] if e["kind"] == "model_step"]
    assert any(s["record_id"] is None and "select_record" in s["available_tools"] for s in model_steps)
    assert all("select_record" not in s["available_tools"] for s in model_steps if s["record_id"])
    assert c.post("/api/chat", json=guidance).json()["kind"] == "guidance"
    assert c.post("/api/jobs", json={"task": "Report invoice INV-1043"}).status_code == 409
