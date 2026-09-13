import pytest
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from eas_harness.execution import ExecutionLayer
from eas_shared.types import Observation, Stale, Recovery
from eas_harness.errors import Paused
from conftest import approve_operation


def node_args(job, **extra):
    return {"company_id": job["company_id"], "invoice_id": job["invoice_id"], **extra}


class FakeAdapter:
    def __init__(self):
        self.revision = "one"
        self.calls = []

    def observe(self):
        return Observation(revision=self.revision, timestamp=1, screenshot="fixture.png", state={})


def test_stale_observation_requires_fresh_proposal(store, job):
    adapter = FakeAdapter()
    layer = ExecutionLayer(store, adapter)
    with pytest.raises(Paused):
        layer.run(job["id"], "test", "validate", node_args(job), lambda a: adapter.calls.append(a))
    approval = store.approvals(job["id"])[0]
    store.decide(approval["id"], {"decision": "approve"})
    adapter.revision = "changed"
    with pytest.raises(Paused):
        layer.run(job["id"], "test", "validate", node_args(job), lambda a: adapter.calls.append(a))
    assert adapter.calls == []
    assert store.approvals(job["id"])[0]["status"] == "stale"


def test_auto_mode_cannot_release_already_queued_node(store, job):
    adapter = FakeAdapter()
    layer = ExecutionLayer(store, adapter)
    with pytest.raises(ValueError, match="Auto mode has been removed"):
        store.mode(job["id"], "auto")
    with pytest.raises(Paused):
        layer.run(job["id"], "test", "validate", node_args(job), lambda a: adapter.calls.append(a))
    with pytest.raises(Paused):
        layer.run(job["id"], "test", "validate", node_args(job), lambda a: adapter.calls.append(a))
    assert adapter.calls == []


def test_shared_layer_replays_completed_result_without_executing_twice(store, job):
    adapter = FakeAdapter()
    layer = ExecutionLayer(store, adapter)
    first = approve_operation(
        layer,
        job["id"],
        "test",
        "validate",
        node_args(job),
        lambda a: adapter.calls.append(a) or {"validated": True},
    )
    second = layer.run(job["id"], "test", "validate", node_args(job), lambda a: adapter.calls.append(a))
    assert first == second and len(adapter.calls) == 1


def test_changed_arguments_cannot_reuse_approval(store, job):
    adapter = FakeAdapter()
    layer = ExecutionLayer(store, adapter)
    with pytest.raises(Paused):
        layer.run(
            job["id"],
            "test",
            "validate",
            node_args(job, reason="original"),
            lambda a: adapter.calls.append(a),
        )
    a = store.approvals(job["id"])[0]
    store.decide(a["id"], {"decision": "approve"})
    with pytest.raises(Paused):
        layer.run(
            job["id"],
            "test",
            "validate",
            node_args(job, reason="different"),
            lambda a: adapter.calls.append(a),
        )
    assert not adapter.calls


def test_backend_revalidates_exact_action_arguments(store, job):
    a = store.proposal(
        job["id"],
        "one",
        {
            "kind": "tool",
            "name": "set_field",
            "arguments": {"field": "amount", "value": "10"},
            "epoch": store.lease()["epoch"],
            "observation": {"revision": "one"},
        },
    )
    store.decide(a["id"], {"decision": "approve"})
    with pytest.raises(Stale, match="differs"):
        store.begin_action(
            job["id"],
            "script",
            store.lease()["epoch"],
            "one",
            {
                "name": "set_field",
                "arguments": {"field": "amount", "value": "1000"},
                "observation_revision": "one",
            },
            a["id"],
        )


def test_code_failure_releases_control_and_records_diagnostics_for_fallback(store, job):
    adapter = FakeAdapter()
    layer = ExecutionLayer(store, adapter)

    def broken_procedure(args):
        raise KeyError("changed_control")

    with pytest.raises(Recovery) as caught:
        approve_operation(layer, job["id"], "broken", "prepare", node_args(job), broken_procedure)
    assert caught.value.kind == "code_failure"
    assert store.lease()["inflight"] is None
    assert store.result("broken") is None
    diagnostic = next(e["data"] for e in store.events(job["id"]) if e["kind"] == "procedure_failure")
    assert diagnostic["error_type"] == "KeyError"
    assert diagnostic["operation"] == "prepare"


def test_parallel_graph_tasks_serialize_desktop_access(store, job):
    layer = ExecutionLayer(store, FakeAdapter())
    ready = threading.Barrier(2)
    active = 0
    maximum = 0

    def execute(args):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        time.sleep(0.03)
        active -= 1
        return {"validated": True}

    def task(index):
        ready.wait(timeout=5)
        return approve_operation(layer, job["id"], f"parallel-{index}", "validate", node_args(job), execute)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(task, range(2)))
    assert len(results) == 2 and maximum == 1
    assert store.lease()["inflight"] is None


def test_corrected_tool_arguments_cannot_change_record_scope(store, job):
    layer = ExecutionLayer(store, FakeAdapter())
    store.transfer(job["id"], "assistant")
    with pytest.raises(Paused):
        layer.run(
            job["id"],
            "scoped",
            "validate",
            node_args(job),
            lambda a: pytest.fail("Unapproved action"),
            kind="tool",
        )
    approval = store.approvals(job["id"])[0]
    store.decide(approval["id"], {"decision": "correct", "arguments": node_args(job, invoice_id="INV-1043")})
    with pytest.raises(PermissionError, match="Corrected invoice_id"):
        layer.run(
            job["id"],
            "scoped",
            "validate",
            node_args(job),
            lambda a: pytest.fail("Cross-record action"),
            kind="tool",
        )
    assert not any(e["kind"] == "action_started" for e in store.events(job["id"]))


def test_composite_operation_called_as_tool_can_make_declared_navigation(store, job):
    adapter = FakeAdapter()
    layer = ExecutionLayer(store, adapter)
    lease = store.lease()
    store.transfer(job["id"], "assistant", lease["epoch"])

    def navigate(arguments):
        # Each underlying input observes the next screen; the initial proposal
        # has already been checked. A raw click keeps its exact screen binding.
        assert adapter.approved_observation is None
        adapter.fence()
        adapter.revision = "next-screen"
        adapter.fence()
        return {"invoice_id": job["invoice_id"]}

    result = approve_operation(
        layer, job["id"], "composite", "establish", node_args(job), navigate, kind="tool"
    )
    assert result["value"]["invoice_id"] == job["invoice_id"]
    assert store.approvals(job["id"])[0]["status"] == "executed"
