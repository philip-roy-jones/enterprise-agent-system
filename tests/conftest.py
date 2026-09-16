import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx
import pytest
from contextlib import contextmanager
from enterprise_dev.config import Settings
from eas_server.store import Store
from eas_shared.types import JobInput


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
        EAS_MAX_MODEL_CALLS="32",
        EAS_PLANNER_TOKEN="test-planner",
    )
    root = Path(__file__).resolve().parents[1]
    # Explicit test identities. Direct ledger fixtures identify their simulated
    # approver separately; production never maps this actor implicitly.
    import json
    from eas_server.config import Settings as ServerSettings
    from eas_server.security import Security

    registry = (
        Security(
            ServerSettings(
                data_dir=data_dir,
                staff_token="test-staff",
                developer_token="test-developer",
                worker_token="test-worker",
                planner_token="test-planner",
            ),
            Store(data_dir),
        )
        .registry()
        .model_dump()
    )
    simulated = dict(
        registry["principals"][0], id="simulated-staff", name="Simulated staff", token_sha256=None
    )
    simulated["grants"] = [{**g, "own_only": False} for g in simulated["grants"]]
    registry["principals"].append(simulated)
    identity_file = data_dir / "test-identities.json"
    identity_file.write_text(json.dumps(registry))
    env["EAS_IDENTITY_FILE"] = str(identity_file)
    backend_log = open(data_dir / "backend.log", "w")
    worker_log = open(data_dir / "worker.log", "w")
    backend = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "eas_server.backend:create_app",
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
    client.post(
        "/api/employees/development-desktop/state",
        headers={"Authorization": "Bearer test-developer"},
        json={"state": "active", "reason": "Simulated supervisor activates the controlled test fixture"},
    ).raise_for_status()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        executor_port = s.getsockname()[1]
    executor_log = open(data_dir / "executor.log", "w")
    executor = subprocess.Popen(
        [sys.executable, "-m", "eas_harness.executor"],
        env={**env, "EAS_EXECUTOR_PORT": str(executor_port)},
        cwd=root,
        stdout=executor_log,
        stderr=executor_log,
    )
    env.update(EAS_EXECUTOR_URL=f"http://127.0.0.1:{executor_port}", EAS_WORKER_TOKEN="test-planner")
    worker = subprocess.Popen(
        [sys.executable, "-m", "eas_harness"],
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
        executor=executor,
        settings=Settings(
            data_dir=data_dir,
            backend_url=url,
            staff_token="test-staff",
            worker_token="test-worker",
            developer_token="test-developer",
        ),
    )

    def check_processes(request):
        for name, process in (("backend", backend), ("executor", executor), ("worker", context["worker"])):
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
    executor.terminate()
    executor.wait(timeout=15)
    executor_log.close()
    backend_log.close()


@pytest.fixture
def browser_server(server):
    client = server["client"]
    for job in client.get("/api/jobs").json():
        if job["status"] not in {"completed", "failed", "denied", "rejected", "cancelled"}:
            client.post(f"/api/jobs/{job['id']}/cancel")
    # Each test owns its skill catalog; multi-session learning stays within a test.
    deadline = time.monotonic() + 15
    while (
        any(i["status"] == "running" for i in server["store"].learning_status()["queue"])
        and time.monotonic() < deadline
    ):
        time.sleep(0.1)
    with server["store"].db() as db:
        db.execute("DELETE FROM maintenance")
    from eas_harness.skill_library import SkillLibrary

    library = SkillLibrary(server["data_dir"])
    with library.db() as db:
        for table in ("versions", "active", "changes", "processed", "dependencies"):
            db.execute("DELETE FROM " + table)
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


def approve_operation(layer, *args, **kwargs):
    """Legacy helper name; run through real policy authorization, no fake staff decision."""
    return layer.run(*args, **kwargs)


def create_active_app(settings):
    """Explicit simulated supervisor activation for tests of active execution."""
    from eas_server.backend import create_app

    app = create_app(settings)
    security = app.state.security
    security.workforce.change(
        security.get("developer"),
        "development-desktop",
        {"state": "active", "reason": "Simulated supervisor; controlled test fixture"},
    )
    return app


@contextmanager
def staged_authorization(store, *, handled=False):
    """Simulate a disconnect between authorization and begin_action, with no effects."""
    from eas_harness.errors import Paused

    original = store.begin_action
    called = []

    def disconnect(*args, **kwargs):
        called.append(True)
        raise Paused("Simulated disconnect before execution")

    store.begin_action = disconnect
    try:
        if handled:
            yield
            assert called, "Fixture did not reach the execution boundary"
        else:
            with pytest.raises(Paused):
                yield
    finally:
        store.begin_action = original
