"""Run under an installed component account and its systemd restrictions; emits no secrets."""

import json
import os
from pathlib import Path
import socket
import sys
import urllib.request
import urllib.error

component, executor_pid = sys.argv[1:]
config = Path("/etc/enterprise-agent-system")
root = Path("/opt/enterprise-agent-system")
state = Path("/var/lib/enterprise-agent-system")
checks = {}


def inaccessible(label, path, flags=os.O_RDONLY):
    try:
        descriptor = os.open(path, flags)
    except PermissionError:
        checks[label] = True
    except FileNotFoundError:
        # Root wrapper verifies this process before/after the probe. ProtectProc
        # deliberately hides other UIDs rather than exposing an access-denied path.
        checks[label] = label == "executor_memory_denied"
    except OSError:
        checks[label] = False
    else:
        os.close(descriptor)
        checks[label] = False


checks["unprivileged_uid"] = os.geteuid() != 0
for other in ("executor", "application"):
    inaccessible(other + "_credential_denied", config / (other + ".env"))
inaccessible("protected_code_write_denied", root / "code/edge-harness/eas_harness/executor.py", os.O_WRONLY)
inaccessible("application_data_denied", state / "application/campaigns.json")
inaccessible("executor_memory_denied", Path("/proc") / executor_pid / "environ")
try:
    response = urllib.request.urlopen("http://127.0.0.1:8770/campaigns/CAM-2001", timeout=5)
except urllib.error.HTTPError as error:
    checks["application_rejects_missing_credential"] = error.code == 401
else:
    response.close()
    checks["application_rejects_missing_credential"] = False
with socket.socket() as sock:
    try:
        sock.bind(("127.0.0.1", 0))
    except PermissionError:
        checks["unapproved_listener_denied"] = True
    else:
        checks["unapproved_listener_denied"] = False
own = config / (component + ".env")
with own.open() as file:
    values = dict(line.strip().split("=", 1) for line in file if "=" in line)
checks["own_configuration_readable"] = bool(values)
test = state / component / "isolation-positive-control"
test.write_text("synthetic positive control")
checks["own_runtime_writable"] = test.read_text() == "synthetic positive control"
test.unlink()
if component == "planner":
    request = urllib.request.Request(
        values["EAS_BACKEND_URL"] + "/api/worker/identity",
        headers={"Authorization": "Bearer " + values["EAS_WORKER_TOKEN"], "X-EAS-Protocol": "2"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        checks["own_server_identity_works"] = json.load(response)["kind"] == "planner"
else:
    checks["no_backend_or_application_credentials"] = not any(
        k in values
        for k in ("EAS_WORKER_TOKEN", "EAS_ADMISSION_TOKEN", "EAS_CAMPAIGN_TOKEN", "CAMPAIGN_DESK_TOKEN")
    )
print(json.dumps({"component": component, "checks": checks, "passed": all(checks.values())}))
