import pytest
from enterprise.execution import ExecutionLayer
from enterprise.types import Observation, Paused, Stale


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
        layer.run(job["id"], "test", "validate", {}, lambda a: adapter.calls.append(a))
    approval = store.approvals(job["id"])[0]
    store.decide(approval["id"], {"decision": "approve"})
    adapter.revision = "changed"
    with pytest.raises(Paused):
        layer.run(job["id"], "test", "validate", {}, lambda a: adapter.calls.append(a))
    assert adapter.calls == []
    assert store.approvals(job["id"])[0]["status"] == "stale"


def test_auto_mode_cannot_release_already_queued_node(store, job):
    adapter = FakeAdapter()
    layer = ExecutionLayer(store, adapter)
    with pytest.raises(Paused):
        layer.run(job["id"], "test", "validate", {}, lambda a: adapter.calls.append(a))
    store.mode(job["id"], "auto")
    with pytest.raises(Paused):
        layer.run(job["id"], "test", "validate", {}, lambda a: adapter.calls.append(a))
    assert adapter.calls == []


def test_shared_layer_replays_completed_result_without_executing_twice(store, job):
    adapter = FakeAdapter()
    layer = ExecutionLayer(store, adapter)
    store.mode(job["id"], "auto")
    first = layer.run(job["id"], "test", "validate", {}, lambda a: adapter.calls.append(a) or {"ok": True})
    second = layer.run(job["id"], "test", "validate", {}, lambda a: adapter.calls.append(a))
    assert first == second and len(adapter.calls) == 1


def test_changed_arguments_cannot_reuse_approval(store, job):
    adapter = FakeAdapter()
    layer = ExecutionLayer(store, adapter)
    with pytest.raises(Paused):
        layer.run(job["id"], "test", "validate", {"record": "original"}, lambda a: adapter.calls.append(a))
    a = store.approvals(job["id"])[0]
    store.decide(a["id"], {"decision": "approve"})
    with pytest.raises(Paused):
        layer.run(job["id"], "test", "validate", {"record": "different"}, lambda a: adapter.calls.append(a))
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
