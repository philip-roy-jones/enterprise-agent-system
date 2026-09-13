import logging
import platform
import sqlite3
import time
from langgraph.checkpoint.sqlite import SqliteSaver
from eas_harness.config import Settings
from eas_harness.execution import ExecutionLayer
from eas_harness.coordinator import Coordinator
from eas_harness.workflows.roles import get_role
from eas_harness.remote import RemoteStore
from eas_shared.identity import uid
from eas_shared.types import Stale, Stopped, TERMINAL

log = logging.getLogger(__name__)


def validate_assignment(settings, job):
    """Receiver-side authorization; dispatch is not proof of permission."""
    if (
        job.get("organization_id") != settings.worker_organization_id
        or job.get("role_id") not in settings.worker_role_ids
    ):
        raise PermissionError("Job is outside this worker's configured organization and roles")
    role = get_role(job["role_id"])
    if job.get("department_id") != role.department_id:
        raise PermissionError("Job department does not match the installed worker role")
    if not set(job.get("permissions", [])).issubset(role.permissions):
        raise PermissionError("Job permissions exceed the installed worker role")
    normalized = role.normalize(
        job,
        allow_unbound=bool(job.get("conversation_request"))
        and job.get("execution_engine") == "agent-led-1"
        and role.id == "invoice_correction",
    )
    if any(normalized[field] != job.get(field) for field in (*role.input_model.model_fields, "record_id")):
        raise PermissionError("Job inputs differ from the validated role inputs")
    return role


def run_worker(settings=None, once=False):
    settings = settings or Settings()
    log.info("Worker started on %s; desktop adapter=%s", platform.system(), settings.desktop_adapter)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = RemoteStore(settings.backend_url, settings.worker_token)
    adapter = None
    active_role = None
    graph = None
    worker_id = uid()
    graph_db = sqlite3.connect(settings.data_dir / "worker-checkpoints.sqlite", check_same_thread=False)
    assist_db = sqlite3.connect(settings.data_dir / "assistant-checkpoints.sqlite", check_same_thread=False)
    from eas_harness.maintenance import maintain

    next_maintenance = 0
    try:
        while True:
            job = store.claim(worker_id)
            if not job:
                if time.monotonic() >= next_maintenance:
                    try:
                        maintain(settings, store, worker_id)
                    except Exception:
                        log.exception("Maintenance pass failed; business authority is unchanged")
                    next_maintenance = time.monotonic() + 5
                if once:
                    return
                time.sleep(0.5)
                continue
            job_id = job["id"]
            try:
                role = validate_assignment(settings, job)
                # Paused assistants and staff takeovers may never enter an operation.
                # Enforce the total job budget before either waiting or resuming.
                lease = store.lease()
                store.check(job_id, lease["owner"], lease["epoch"])
                role_id = job.get("role_id", "invoice_correction")
                engine = job.get("execution_engine", "legacy-strict")
                if (role_id, engine) != active_role:
                    if adapter:
                        adapter.close()
                    adapter = role.adapter_factory(settings, store)
                    layer = ExecutionLayer(store, adapter, role.operations)
                    if role_id == "invoice_correction" and engine == "agent-led-1":
                        graph = Coordinator(
                            settings, store, layer, SqliteSaver(assist_db), SqliteSaver(graph_db)
                        )
                    else:
                        graph = role.graph_factory(
                            settings, store, layer, SqliteSaver(graph_db), SqliteSaver(assist_db)
                        ).graph
                    active_role = (role_id, engine)
                if store.lease()["owner"] == "staff":
                    time.sleep(0.5)
                    continue
                if isinstance(graph, Coordinator):
                    graph.tick(job)
                else:
                    config = {
                        "configurable": {"thread_id": job_id},
                        "recursion_limit": 160,
                        "max_concurrency": 4,
                    }
                    snapshot = graph.get_state(config)
                    # On every restart and resume observations come from the actual application.
                    if snapshot.next:
                        value = None  # Retry an interrupted task after a process crash.
                    elif snapshot.values:
                        value = {"job_id": job_id, "paused": False}
                    else:
                        value = {"job_id": job_id, "turn": 0, "paused": False}
                    graph.invoke(value, config, durability="sync")
            except Stale:
                # Handoffs invalidate queued actions; retry only after observing current authority.
                time.sleep(0.25)
            except (Stopped, PermissionError) as error:
                log.warning("Job %s stopped: %s", job_id, error)
                if store.get_job(job_id)["status"] not in TERMINAL:
                    store.update_job(
                        job_id,
                        {
                            "status": "denied" if isinstance(error, PermissionError) else "failed",
                            "error": str(error),
                        },
                    )
            except Exception as error:
                log.exception("Job %s failed", job_id)
                if store.get_job(job_id)["status"] not in TERMINAL:
                    store.update_job(job_id, {"status": "failed", "error": str(error)})
            if once and store.get_job(job_id)["status"] in TERMINAL:
                return
            time.sleep(0.5)
    finally:
        if adapter:
            adapter.close()
        graph_db.close()
        assist_db.close()
