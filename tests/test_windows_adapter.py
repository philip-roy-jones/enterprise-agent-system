import httpx
import pytest
from enterprise.config import Settings
from enterprise.types import Recovery, Stale
from enterprise.windows_adapter import WindowsBridge


def test_native_bridge_requires_explicit_private_token():
    with pytest.raises(ValueError, match="EAS_WINDOWS_TOKEN"):
        WindowsBridge(Settings(windows_token=""))


@pytest.mark.parametrize(
    "status,reason,exception",
    [
        (401, "Authorization required", PermissionError),
        (403, "Wrong scoped invoice", PermissionError),
        (409, "Application revision changed before execution", Stale),
        (409, "DemoBooks must be the foreground application", Recovery),
    ],
)
def test_native_bridge_classifies_restrictions(status, reason, exception):
    bridge = WindowsBridge(Settings(windows_token="synthetic-test-token"))
    bridge.client.close()
    bridge.client = httpx.Client(
        base_url="http://native.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json={"error": reason})),
    )
    with pytest.raises(exception):
        bridge.call("/action", {"name": "click", "args": {"target": "save"}})
    bridge.client.close()


def test_window_recovery_reserves_control_and_never_mutates_accounting(store, job):
    from enterprise.windows_adapter import WindowsAdapter
    from enterprise.types import Stale

    class Bridge:
        focused = False
        calls = []

        def call(self, path, data=None):
            self.calls.append(path)
            if path == "/activate":
                with pytest.raises(Stale):
                    store.transfer(job["id"], "staff")
                self.focused = True
            return {"foreground": self.focused}

    adapter = object.__new__(WindowsAdapter)
    adapter.store, adapter.bridge = store, Bridge()
    lease = store.lease()
    adapter.prepare_observation(job["id"], "script", lease["epoch"])
    assert adapter.bridge.calls == ["/window", "/activate", "/window"]
    assert store.lease()["inflight"] is None
    assert store.get_job(job["id"])["mutation"] == "not_attempted"
    assert store.approvals(job["id"]) == []
    store.transfer(job["id"], "staff")
    adapter.bridge.focused = False
    with pytest.raises(Stale):
        adapter.prepare_observation(job["id"], "script", lease["epoch"])
    assert adapter.bridge.calls.count("/activate") == 1


@pytest.mark.parametrize("condition", ["minimized", "offscreen"])
def test_unavailable_window_is_restored_even_if_reported_as_foreground(store, job, condition):
    from enterprise.windows_adapter import WindowsAdapter

    class Bridge:
        minimized = True
        calls = []

        def call(self, path, data=None):
            self.calls.append(path)
            if path == "/activate":
                self.minimized = False
            return {
                "foreground": True,
                "minimized": self.minimized if condition == "minimized" else False,
                "onscreen": not self.minimized if condition == "offscreen" else True,
            }

    adapter = object.__new__(WindowsAdapter)
    adapter.store, adapter.bridge = store, Bridge()
    lease = store.lease()
    adapter.prepare_observation(job["id"], "script", lease["epoch"])
    assert adapter.bridge.calls == ["/window", "/activate", "/window"]
    assert not adapter.bridge.minimized
