import pytest
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from eas_harness.execution import ExecutionLayer
from eas_shared.types import Observation, Stale, Recovery
from conftest import approve_operation, staged_authorization


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
    with staged_authorization(store):
        layer.run(job["id"], "test", "validate", node_args(job), lambda a: adapter.calls.append(a))
    adapter.revision = "changed"
    with pytest.raises(Stale):
        layer.run(job["id"], "test", "validate", node_args(job), lambda a: adapter.calls.append(a))
    assert adapter.calls == []
    assert store.approvals(job["id"])[0]["status"] == "stale"


def test_historical_policy_cannot_run_under_auto(store, job):
    with store.db() as db:
        historical = store._job(db, job["id"])
        historical["execution_policy"] = 2
        store._put(db, historical)
    from eas_shared.types import Stopped

    with pytest.raises(Stopped):
        ExecutionLayer(store, FakeAdapter()).run(
            job["id"], "test", "validate", node_args(job), lambda _: pytest.fail("Historical work executed")
        )


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
    with staged_authorization(store):
        layer.run(
            job["id"],
            "test",
            "validate",
            node_args(job, reason="original"),
            lambda a: adapter.calls.append(a),
        )
    with pytest.raises(Stale):
        layer.run(
            job["id"],
            "test",
            "validate",
            node_args(job, reason="different"),
            lambda a: adapter.calls.append(a),
        )
    assert not adapter.calls


def test_backend_revalidates_exact_action_arguments(store, job):
    a = store.authorize_operation(
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


def test_model_arguments_cannot_change_record_scope(store, job):
    layer = ExecutionLayer(store, FakeAdapter())
    store.transfer(job["id"], "assistant")
    with pytest.raises(PermissionError, match="invoice_id"):
        layer.run(
            job["id"],
            "scoped",
            "validate",
            node_args(job, invoice_id="INV-1043"),
            lambda _: pytest.fail("Cross-record action"),
            kind="tool",
        )
    assert not store.approvals(job["id"])


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
