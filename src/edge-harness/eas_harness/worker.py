import logging
import platform
import sqlite3
import time
from langgraph.checkpoint.sqlite import SqliteSaver
from eas_harness.config import Settings
from eas_harness.execution import ExecutionLayer
from eas_harness.coordinator import Coordinator
from eas_harness.roles import get_role
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
        allow_unbound=bool(job.get("conversation_request")) and job.get("execution_engine") == "agent-led-1",
    )
    if any(normalized[field] != job.get(field) for field in (*role.input_model.model_fields, "record_id")):
        raise PermissionError("Job inputs differ from the validated role inputs")
    return role


def run_worker(settings=None, once=False):
    settings = settings or Settings()
    log.info("Worker started on %s; desktop adapter=%s", platform.system(), settings.desktop_adapter)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = RemoteStore(settings.backend_url, settings.worker_token)
    admission_store = (
        None if settings.executor_url else RemoteStore(settings.backend_url, settings.admission_token)
    )
    adapter = None
    active_role = None
    graph = None
    worker_id = uid()
    graph_db = (
        None
        if settings.executor_url
        else sqlite3.connect(settings.data_dir / "worker-checkpoints.sqlite", check_same_thread=False)
    )
    assist_db = (
        None
        if settings.executor_url
        else sqlite3.connect(settings.data_dir / "assistant-checkpoints.sqlite", check_same_thread=False)
    )
    from eas_harness.maintenance import maintain

    next_maintenance = 0
    try:
        while True:
            job = store.claim(worker_id)
            if not job:
                if admission_store and time.monotonic() >= next_maintenance:
                    try:
                        maintain(settings, admission_store, worker_id)
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
                engine = job.get("execution_engine")
                if engine != "agent-led-1":
                    raise Stopped(
                        "Historical graph-first requests cannot execute; submit a new skill-based request"
                    )
                if (role_id, engine) != active_role:
                    if adapter:
                        adapter.close()
                    if settings.executor_url:
                        from eas_harness.executor import RemoteExecutionLayer

                        layer = RemoteExecutionLayer(settings, store)
                        adapter = layer.adapter
                    else:
                        adapter = role.adapter_factory(settings, store)
                        layer = ExecutionLayer(store, adapter, role.operations)
                    if settings.executor_url:
                        from eas_harness.context_broker import RemoteCheckpointer

                        assist_saver = RemoteCheckpointer(layer, "agent")
                        graph_saver = RemoteCheckpointer(layer, "workflow")
                    else:
                        assist_saver, graph_saver = SqliteSaver(assist_db), SqliteSaver(graph_db)
                    graph = Coordinator(settings, store, layer, assist_saver, graph_saver)
                    active_role = (role_id, engine)
                if store.lease()["owner"] == "staff":
                    time.sleep(0.5)
                    continue
                graph.tick(job)
            except Stale:
                # Handoffs invalidate queued actions; retry only after observing current authority.
                time.sleep(0.25)
            except (Stopped, PermissionError) as error:
                log.warning("Job %s stopped: %s", job_id, error)
                try:
                    current = store.get_job(job_id)
                except PermissionError:
                    # Revocation removes reads too. An operation denial for an
                    # otherwise authorized request still needs a terminal state.
                    active_role = None
                    continue
                if current["status"] not in TERMINAL:
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
        if graph_db:
            graph_db.close()
        if assist_db:
            assist_db.close()
