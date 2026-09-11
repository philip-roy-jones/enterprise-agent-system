import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx
import pytest
from enterprise.shared.config import Settings
from enterprise.server.store import Store
from enterprise.shared.types import JobInput


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path)


@pytest.fixture
def job(store):
    job = store.create_job(JobInput(invoice_id="INV-1042").model_dump())
    store.claim("test-worker")
    return job


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("integration")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = dict(
        os.environ,
        EAS_DATA_DIR=str(data_dir),
        EAS_BACKEND_URL=url,
        EAS_MODEL_MODE="simulated",
        EAS_STAFF_TOKEN="test-staff",
        EAS_WORKER_TOKEN="test-worker",
        EAS_DEVELOPER_TOKEN="test-developer",
        EAS_HEADLESS="true",
        EAS_DESKTOP_ADAPTER="browser",
        EAS_JOB_TIMEOUT_SECONDS="120",
    )
    root = Path(__file__).resolve().parents[1]
    backend_log = open(data_dir / "backend.log", "w")
    worker_log = open(data_dir / "worker.log", "w")
    backend = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "enterprise.server.backend:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        env=env,
        cwd=root,
        stdout=backend_log,
        stderr=backend_log,
    )
    client = httpx.Client(base_url=url, headers={"Authorization": "Bearer test-staff"}, timeout=15)
    for _ in range(100):
        try:
            if client.get("/api/health").is_success:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    else:
        backend.terminate()
        pytest.fail((data_dir / "backend.log").read_text())
    worker = subprocess.Popen(
        [sys.executable, "-m", "enterprise.cli", "worker"],
        env=env,
        cwd=root,
        stdout=worker_log,
        stderr=worker_log,
    )
    context = dict(
        client=client,
        store=Store(data_dir),
        worker=worker,
        env=env,
        root=root,
        url=url,
        data_dir=data_dir,
        worker_log=worker_log,
        settings=Settings(
            data_dir=data_dir,
            backend_url=url,
            staff_token="test-staff",
            worker_token="test-worker",
            developer_token="test-developer",
        ),
    )

    def check_processes(request):
        for name, process in (("backend", backend), ("worker", context["worker"])):
            code = process.poll()
            if code is not None:
                pytest.fail(
                    f"Integration {name} exited with code {code}\n"
                    + (data_dir / f"{name}.log").read_text()[-8000:]
                )

    client.event_hooks["request"].append(check_processes)
    yield context
    context["worker"].terminate()
    context["worker"].wait(timeout=15)
    backend.terminate()
    backend.wait(timeout=15)
    client.close()
    worker_log.close()
    backend_log.close()


@pytest.fixture
def browser_server(server):
    client = server["client"]
    for job in client.get("/api/jobs").json():
        if job["status"] not in {"completed", "failed", "denied", "rejected", "cancelled"}:
            client.post(f"/api/jobs/{job['id']}/cancel")
    server["store"].put_value("release", {"version": "v1", "labels": ["Correction amount"], "previous": None})
    client.post(
        "/api/mock/scenario",
        json={
            "view": "dashboard",
            "invoice_id": None,
            "company_id": "ACME",
            "dialog": None,
            "variant": "standard",
            "amount_label": None,
            "reordered": False,
            "interrupt_save": False,
            "reject_save": False,
            "unsaved": False,
            "delay_seconds": 0,
        },
    ).raise_for_status()
    yield server


def wait_for(client, job_id, predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/jobs/{job_id}").json()
        if predicate(data):
            return data
        if data["job"]["status"] in {"failed", "denied", "cancelled", "rejected"}:
            raise AssertionError(data["job"])
        time.sleep(0.1)
    raise AssertionError(
        f"Timed out: {data['job']}; approvals: {[(a['name'], a['status']) for a in data['approvals']]}"
    )


def pending(client, job_id):
    data = wait_for(client, job_id, lambda d: any(a["status"] == "pending" for a in d["approvals"]))
    return next(a for a in data["approvals"] if a["status"] == "pending")


@pytest.fixture(params=["src", "legacy"])
def candidate(tmp_path, request):
    import json
    from enterprise.development.improve import sha

    folder = tmp_path / "proposal"
    checkout = folder / "checkout"
    package = checkout / ("src/enterprise/workflows/finance" if request.param == "src" else "enterprise")
    package.mkdir(parents=True)
    for parent in [package, *package.parents]:
        if parent in {checkout, checkout / "src"}:
            break
        (parent / "__init__.py").write_text("")
    source = package / "procedures.py"
    source.write_text(
        'GRAPH_VERSION="v2"\nAMOUNT_LABELS=("Correction amount","Adjusted total")\ndef resolve_amount_label(labels):\n    return next((l for l in AMOUNT_LABELS if l in labels),None)\n'
    )
    (checkout / ".gitignore").write_text("__pycache__/\n")
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "-qm",
            "Checked test candidate",
        ],
        check=True,
    )
    commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    (folder / "proposal.patch").write_text("Synthetic fixture patch")
    (folder / "checks.txt").write_text("Synthetic fixture checks passed")
    manifest = {
        "checkout": str(checkout),
        "commit": commit,
        "source_sha": sha(source),
        "patch_sha": sha(folder / "proposal.patch"),
        "checks_sha": sha(folder / "checks.txt"),
        "checks_passed": True,
        "review": "pending",
        "approved_commit": None,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder
