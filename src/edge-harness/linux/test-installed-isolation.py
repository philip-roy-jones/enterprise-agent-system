"""Root operator probe: actual installed accounts, copied unit restrictions and positive controls."""

import configparser
import json
from pathlib import Path
import subprocess
import uuid


def main():
    executor_pid = subprocess.check_output(
        ["systemctl", "show", "eas-executor", "--property=MainPID", "--value"], text=True
    ).strip()
    if executor_pid == "0":
        raise RuntimeError("Executor must be running for a meaningful process access probe")
    for path in (
        "/etc/enterprise-agent-system/executor.env",
        "/etc/enterprise-agent-system/application.env",
        "/var/lib/enterprise-agent-system/application/campaigns.json",
    ):
        if not Path(path).is_file():
            raise RuntimeError("Required probe target is missing")
    # The target exists and is readable to the root operator.
    if not (Path("/proc") / executor_pid / "environ").exists():
        raise RuntimeError("Executor process target is missing")
    results = []
    for component in ("planner", "learner"):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        parser.read("/etc/systemd/system/eas-" + component + ".service")
        command = [
            "systemd-run",
            "--quiet",
            "--wait",
            "--pipe",
            "--collect",
            "--unit=eas-probe-" + uuid.uuid4().hex,
        ]
        for key, value in parser["Service"].items():
            if key not in {"Type", "ExecStart", "Restart", "RestartSec"}:
                command += ["--property=" + key + "=" + value]
        command += [
            "/opt/enterprise-agent-system/venv/bin/python",
            "/opt/enterprise-agent-system/code/edge-harness/linux/probe-isolation.py",
            component,
            executor_pid,
        ]
        run = subprocess.run(command, capture_output=True, text=True)
        if run.returncode:
            raise RuntimeError(
                "Installed-account probe could not complete; inspect the protected service logs"
            )
        results.append(json.loads(run.stdout))
    current_pid = subprocess.check_output(
        ["systemctl", "show", "eas-executor", "--property=MainPID", "--value"], text=True
    ).strip()
    if current_pid != executor_pid:
        raise RuntimeError("Executor restarted during probes; results are inconclusive")
    print(json.dumps({"results": results, "passed": all(r["passed"] for r in results)}, indent=2))
    if not all(r["passed"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
