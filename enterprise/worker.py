import logging
import sqlite3
import time
from langgraph.checkpoint.sqlite import SqliteSaver
from .adapter import ThreadedBrowserAdapter
from .config import Settings
from .execution import ExecutionLayer
from .graph import RoleGraph
from .remote import RemoteStore
from .store import uid
from .types import Stale, Stopped, TERMINAL

log = logging.getLogger(__name__)


def run_worker(settings=None, once=False):
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = RemoteStore(settings.backend_url, settings.worker_token)
    adapter = ThreadedBrowserAdapter(settings, store)
    worker_id = uid()
    graph_db = sqlite3.connect(settings.data_dir / "worker-checkpoints.sqlite", check_same_thread=False)
    assist_db = sqlite3.connect(settings.data_dir / "assistant-checkpoints.sqlite", check_same_thread=False)
    graph = RoleGraph(
        settings, store, ExecutionLayer(store, adapter), SqliteSaver(graph_db), SqliteSaver(assist_db)
    ).graph
    try:
        while True:
            job = store.claim(worker_id)
            if not job:
                if once:
                    return
                time.sleep(0.5)
                continue
            job_id = job["id"]
            try:
                if store.lease()["owner"] == "staff":
                    time.sleep(0.5)
                    continue
                config = {"configurable": {"thread_id": job_id}, "recursion_limit": 160, "max_concurrency": 1}
                snapshot = graph.get_state(config)
                # On every restart and resume observations come from the actual application.
                if snapshot.next:
                    value = None  # Retry an interrupted task after a process crash.
                elif snapshot.values:
                    value = {"job_id": job_id, "paused": False}
                else:
                    value = {"job_id": job_id, "turn": 0, "paused": False}
                graph.invoke(value, config)
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
        adapter.close()
        graph_db.close()
        assist_db.close()
