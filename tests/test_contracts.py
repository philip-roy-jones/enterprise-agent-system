from dataclasses import replace
import time

import pytest
from pydantic import ValidationError

from enterprise.adapter import BrowserAdapter
from enterprise.execution import ExecutionLayer
from enterprise.operations import OPERATIONS
from enterprise.types import Paused, Recovery
from test_execution import FakeAdapter, node_args


def layer_for(store, job, name="validate", **settings):
    store.mode(job["id"], "auto")
    return ExecutionLayer(store, FakeAdapter(), {name: replace(OPERATIONS[name], **settings)})


def test_invalid_inputs_never_reach_proposal_or_operation(store, job):
    layer = layer_for(store, job)
    with pytest.raises(ValidationError):
        layer.run(
            job["id"],
            "bad",
            "validate",
            node_args(job, execute_code="untrusted"),
            lambda a: pytest.fail("Executed invalid inputs"),
        )
    assert not store.approvals(job["id"])
    assert not any(e["kind"] == "action_started" for e in store.events(job["id"]))


def test_operation_result_must_satisfy_its_contract(store, job):
    layer = layer_for(store, job)
    with pytest.raises(Recovery) as error:
        layer.run(job["id"], "bad-output", "validate", node_args(job), lambda a: {"validated": False})
    assert error.value.kind == "code_failure"
    assert store.result("bad-output") is None
    assert store.lease()["inflight"] is None


def test_public_adapter_operation_rejects_invalid_inputs_before_touching_app():
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    adapter.ready = lambda: pytest.fail("Invalid argument reached the app")
    with pytest.raises(ValidationError):
        adapter.ensure_company(42)


def test_deadline_revokes_later_effects_without_abandoning_a_thread(store, job):
    layer = layer_for(store, job, timeout_seconds=0.01)
    effects = []

    def slow(args):
        time.sleep(0.02)
        layer.adapter.fence()
        effects.append("forbidden late action")
        return {"validated": True}

    with pytest.raises(Recovery, match="deadline"):
        layer.run(job["id"], "expired", "validate", node_args(job), slow)
    assert not effects and store.result("expired") is None
    assert store.lease()["inflight"] is None
    with pytest.raises(PermissionError):
        layer.adapter.fence()


def test_retry_allowance_routes_to_assistance_after_exhaustion(store, job):
    layer = layer_for(store, job, retry_limit=1)
    attempts = []

    def unavailable(args):
        attempts.append(1)
        raise Recovery("temporary", "Page loading")

    kinds = []
    for attempt in range(2):
        with pytest.raises(Recovery) as error:
            layer.run(job["id"], f"attempt-{attempt}", "validate", node_args(job), unavailable)
        kinds.append(error.value.kind)
    assert kinds == ["temporary", "unfamiliar"] and len(attempts) == 2


def test_retry_in_strict_mode_needs_a_new_approval(store, job):
    layer = ExecutionLayer(store, FakeAdapter())

    def unavailable(args):
        raise Recovery("temporary", "Page loading")

    with pytest.raises(Paused):
        layer.run(job["id"], "first", "validate", node_args(job), unavailable)
    store.decide(store.approvals(job["id"])[0]["id"], {"decision": "approve"})
    with pytest.raises(Recovery):
        layer.run(job["id"], "first", "validate", node_args(job), unavailable)
    with pytest.raises(Paused):
        layer.run(job["id"], "retry", "validate", node_args(job), unavailable)
    assert store.approvals(job["id"])[-1]["status"] == "pending"


def test_unverified_save_output_never_becomes_confirmed_success(store, job):
    layer = layer_for(store, job, name="save_draft")
    with pytest.raises(Recovery):
        layer.run(job["id"], "save", "save_draft", {}, lambda args: {"ok": True})
    assert store.get_job(job["id"])["mutation"] == "attempted_uncertain"
    assert store.result("save") is None


def test_rejection_for_another_operation_does_not_clear_save_uncertainty(store, job):
    from enterprise.types import MutationRejected

    layer = layer_for(store, job, name="save_draft")

    def rejected(args):
        raise MutationRejected("other-job", "Application rejected another request")

    with pytest.raises(Recovery, match="does not identify"):
        layer.run(job["id"], "save", "save_draft", {}, rejected)
    assert store.get_job(job["id"])["mutation"] == "attempted_uncertain"


def test_click_contract_rejects_conflicting_target_and_coordinates():
    from enterprise.contracts import ClickInputs
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ClickInputs(target="invoices", x=50, y=60)
