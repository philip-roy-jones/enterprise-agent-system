import json
import time
import pytest
from enterprise.server.store import Store
from enterprise.shared.identity import canonical
from enterprise.shared.types import Stale, Stopped, JobInput


def proposal(store, job, invocation="one", kind="node"):
    return store.proposal(
        job["id"],
        invocation,
        {
            "kind": kind,
            "name": "observe_app",
            "arguments": {},
            "epoch": store.lease()["epoch"],
            "observation": {"revision": "current"},
            "signature": "bound",
        },
    )


def test_strict_requires_approval_even_when_ui_is_bypassed(store, job):
    with pytest.raises(Stale, match="Approval required"):
        store.begin_action(job["id"], "script", store.lease()["epoch"], "one", {})


def test_auto_never_auto_approves_assistant_tools(store, job):
    store.mode(job["id"], "auto")
    store.boundary(job["id"])
    lease = store.transfer(job["id"], "assistant")
    with pytest.raises(Stale, match="Approval required"):
        store.begin_action(job["id"], "assistant", lease["epoch"], "tool", {})
    assert store.get_job(job["id"])["effective_mode"] == "strict"


def test_mode_changes_apply_at_boundaries_and_restore(store, job):
    store.mode(job["id"], "auto")
    assert store.get_job(job["id"])["selected_mode"] == "strict"
    store.boundary(job["id"])
    store.transfer(job["id"], "assistant")
    store.mode(job["id"], "strict")
    store.boundary(job["id"])
    assert store.get_job(job["id"])["effective_mode"] == "strict"
    store.mode(job["id"], "auto")
    store.boundary(job["id"])
    store.transfer(job["id"], "script")
    assert store.get_job(job["id"])["effective_mode"] == "auto"


@pytest.mark.parametrize("decision", ["approve", "correct", "reject"])
def test_duplicate_decisions_are_rejected(store, job, decision):
    a = proposal(store, job, kind="tool")
    store.decide(a["id"], {"decision": decision, "arguments": {}})
    with pytest.raises(Stale):
        store.decide(a["id"], {"decision": decision, "arguments": {}})


def test_rejection_is_terminal_and_not_fallback(store, job):
    a = proposal(store, job)
    store.decide(a["id"], {"decision": "reject"})
    with pytest.raises(Stopped):
        store.transfer(job["id"], "assistant")


def test_cancel_invalidates_pending_and_approved(store, job):
    a = proposal(store, job)
    store.decide(a["id"], {"decision": "approve"})
    store.stop(job["id"])
    assert store.approvals(job["id"])[0]["status"] == "stale"
    with pytest.raises(Stopped):
        store.check(job["id"], "script", store.lease()["epoch"])


def test_handoff_invalidates_queued_actions_and_old_epoch(store, job):
    old = store.lease()["epoch"]
    a = proposal(store, job)
    store.decide(a["id"], {"decision": "approve"})
    store.transfer(job["id"], "staff")
    store.transfer(job["id"], "script")
    assert store.approvals(job["id"])[0]["status"] == "stale"
    with pytest.raises(Stale):
        store.begin_action(
            job["id"],
            "script",
            old,
            "one",
            {"name": "observe_app", "arguments": {}, "observation_revision": "current"},
            a["id"],
        )


def test_handoff_refuses_inflight_operation(store, job):
    a = proposal(store, job)
    store.decide(a["id"], {"decision": "approve"})
    store.begin_action(
        job["id"],
        "script",
        store.lease()["epoch"],
        "one",
        {"name": "observe_app", "arguments": {}, "observation_revision": "current"},
        a["id"],
    )
    with pytest.raises(Stale, match="in flight"):
        store.transfer(job["id"], "staff")
    store.finish_action(job["id"], "one", {"verified": True}, a["id"])
    assert store.transfer(job["id"], "staff")["owner"] == "staff"


def test_worker_session_exclusivity_and_expired_lease(store, job):
    other = store.create_job(JobInput(invoice_id="INV-1043").model_dump())
    assert store.claim("another-worker") is None
    assert store.claim("test-worker")["id"] == job["id"]
    assert store.get_job(other["id"])["status"] == "queued"
    with store.db() as db:
        lease = json.loads(db.execute("SELECT data FROM lease").fetchone()[0])
        lease["expires"] = time.time() - 1
        db.execute("UPDATE lease SET data=?", (canonical(lease),))
    with pytest.raises(Stale):
        store.check(job["id"], "script", lease["epoch"])
    assert store.claim("replacement")["id"] == job["id"]
    assert store.lease()["epoch"] > lease["epoch"]


def test_approval_persists_across_reconnect(store, job):
    a = proposal(store, job)
    restored = Store(store.root)
    assert restored.approvals(job["id"])[0]["id"] == a["id"]
    restored.decide(a["id"], {"decision": "approve"})
    assert store.approvals(job["id"])[0]["status"] == "approved"


def test_invocation_binding_prevents_cross_operation_approval(store, job):
    a = proposal(store, job)
    store.decide(a["id"], {"decision": "approve"})
    with pytest.raises(Stale, match="mismatch"):
        store.begin_action(job["id"], "script", store.lease()["epoch"], "different", {}, a["id"])
