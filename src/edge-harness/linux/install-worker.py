"""Install an isolated API-based Linux worker. Run as root after draining existing work.

Input config directory: planner.env, executor.env, learner.env, application.env.
All credentials must already be scoped to this uniquely enrolled worker.
"""

import argparse
import grp
import os
from pathlib import Path
import pwd
import shutil
import subprocess

COMPONENTS = {
    "planner": "eas-planner",
    "executor": "eas-executor",
    "learner": "eas-learner",
    "application": "eas-campaign",
}
ROOT = Path("/opt/enterprise-agent-system")
CONFIG = Path("/etc/enterprise-agent-system")
STATE = Path("/var/lib/enterprise-agent-system")


def run(*args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Repository source root")
    parser.add_argument("--config", type=Path, required=True, help="Private staged component configuration")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Root is required to provision service accounts and protected files")
    for component in COMPONENTS:
        if not (args.config / (component + ".env")).is_file():
            raise ValueError("Missing component configuration: " + component)
        status = subprocess.run(["systemctl", "is-active", "eas-" + component], capture_output=True)
        if status.returncode == 0:
            raise ValueError("Drain and stop the existing worker before reinstalling")
    for user in COMPONENTS.values():
        try:
            entry = pwd.getpwnam(user)
            if entry.pw_uid == 0 or entry.pw_shell not in {"/usr/sbin/nologin", "/sbin/nologin"}:
                raise ValueError("Refusing to reuse an interactive service account")
        except KeyError:
            run(
                "useradd",
                "--system",
                "--user-group",
                "--no-create-home",
                "--shell",
                "/usr/sbin/nologin",
                user,
            )
    try:
        grp.getgrnam("eas-learning")
    except KeyError:
        run("groupadd", "--system", "eas-learning")
    for user in ("eas-executor", "eas-learner"):
        run("usermod", "--append", "--groups", "eas-learning", user)
    for folder in (ROOT, CONFIG, STATE):
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o755)
    for component, user in COMPONENTS.items():
        destination = CONFIG / (component + ".env")
        shutil.copyfile(args.config / destination.name, destination)
        shutil.chown(destination, "root", user)
        destination.chmod(0o640)
        folder = STATE / component
        folder.mkdir(exist_ok=True)
        shutil.chown(folder, user, user)
        folder.chmod(0o700)
    queue = STATE / "learning-ipc"
    queue.mkdir(exist_ok=True)
    shutil.chown(queue, "root", "eas-learning")
    queue.chmod(0o750)
    for name, owner, mode in (("requests", "eas-executor", 0o2750), ("responses", "eas-learner", 0o2770)):
        folder = queue / name
        folder.mkdir(exist_ok=True)
        shutil.chown(folder, owner, "eas-learning")
        folder.chmod(mode)
    code = ROOT / "code"
    code.mkdir(exist_ok=True)
    for name in ("shared", "edge-harness", "campaign-desk"):
        destination = code / name
        if destination.exists():
            # Source is replaceable; retained state lives outside this tree.
            shutil.rmtree(destination)
        shutil.copytree(
            args.source / "src" / ("test-software/" + name if name == "campaign-desk" else name),
            destination,
            ignore=shutil.ignore_patterns(".env*", "__pycache__", "*.egg-info", "build", "bin", "obj"),
        )
    run("python3", "-m", "venv", str(ROOT / "venv"))
    run(
        str(ROOT / "venv/bin/pip"),
        "install",
        "-c",
        str(args.source / "requirements.lock"),
        str(code / "shared"),
        str(code / "edge-harness"),
        str(code / "campaign-desk"),
    )
    run("chown", "-R", "root:root", str(ROOT))
    run("chmod", "-R", "go-w", str(ROOT))
    entrypoint = code / "edge-harness/windows/run-component.py"
    for component, user in COMPONENTS.items():
        command = (
            f"{ROOT}/venv/bin/python -m campaign_desk.app"
            if component == "application"
            else f"{ROOT}/venv/bin/python {entrypoint} {component} --env {CONFIG}/{component}.env"
        )
        writes = [str(STATE / component)]
        if component == "executor":
            writes += [str(queue / "requests"), str(queue / "responses")]
        if component == "learner":
            writes += [str(queue / "responses")]
        denied = [str(CONFIG / (c + ".env")) for c in COMPONENTS if c != component]
        denied += [str(STATE / c) for c in COMPONENTS if c != component]
        unit = f"""[Unit]
Description=Enterprise Agent System {component}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
Group={user}
EnvironmentFile={CONFIG}/{component}.env
Environment=PYTHONDONTWRITEBYTECODE=1
WorkingDirectory={STATE}/{component}
ExecStart={command}
Restart=on-failure
RestartSec=5
UMask=0027
NoNewPrivileges=yes
CapabilityBoundingSet=
AmbientCapabilities=
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectProc=invisible
ProcSubset=pid
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictNamespaces=yes
RestrictRealtime=yes
LockPersonality=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths={" ".join(writes)}
InaccessiblePaths={" ".join(denied)}
SocketBindDeny=any
TasksMax=64
MemoryMax=1G

[Install]
WantedBy=multi-user.target
"""
        if component in {"planner", "learner"}:
            unit = unit.replace(
                "SocketBindDeny=any",
                "SocketBindDeny=any\nSystemCallFilter=~bind\nSystemCallErrorNumber=EPERM",
            )
        if component in {"executor", "application"}:
            port = 8767 if component == "executor" else 8770
            unit = unit.replace("SocketBindDeny=any", f"SocketBindDeny=any\nSocketBindAllow=ipv4:tcp:{port}")
        (Path("/etc/systemd/system") / ("eas-" + component + ".service")).write_text(unit)
    if (STATE / "executor/skills/registry.sqlite").exists():
        run(
            "runuser",
            "-u",
            "eas-executor",
            "--",
            "env",
            "EAS_ENV_FILE=" + str(CONFIG / "executor.env"),
            str(ROOT / "venv/bin/python"),
            "-m",
            "eas_harness.migrate",
            "--from-root",
            str(STATE / "executor"),
        )
    run("systemctl", "daemon-reload")
    for component in ("application", "learner", "executor", "planner"):
        run("systemctl", "enable", "--now", "eas-" + component)
    print(
        "Installed four isolated services. Run the access probes and live validation before claiming support."
    )


if __name__ == "__main__":
    main()
