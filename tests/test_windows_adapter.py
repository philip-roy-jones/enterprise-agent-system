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
