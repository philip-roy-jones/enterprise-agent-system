"""Transactional central persistence. Worker access is a restricted HTTP RPC boundary."""

from contextlib import contextmanager
from contextvars import ContextVar

import json
import re
from pathlib import Path
import sqlite3
import time
from eas_shared.identity import canonical, uid
from eas_shared.types import TERMINAL, Stale, Stopped


from eas_server.learning import LearningStore

desktop_context = ContextVar("desktop_context", default=None)


class Store(LearningStore):
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "artifacts").mkdir(exist_ok=True)
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, job_id TEXT, invocation TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, kind TEXT, at REAL, data TEXT);
            CREATE TABLE IF NOT EXISTS invocations(id TEXT PRIMARY KEY, job_id TEXT, result TEXT);
            CREATE TABLE IF NOT EXISTS lease(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT);
            CREATE TABLE IF NOT EXISTS desktop_leases(id TEXT PRIMARY KEY, data TEXT);
            CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, data TEXT);
            CREATE TABLE IF NOT EXISTS maintenance(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS knowledge(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            """)
            db.execute(
                "INSERT OR IGNORE INTO lease VALUES(1, ?)",
                (canonical(dict(job_id=None, owner=None, epoch=0, expires=0, inflight=None)),),
            )
            db.execute(
                "INSERT OR IGNORE INTO kv VALUES('release', ?)",
                (canonical(dict(version="v1", labels=["Correction amount"], previous=None)),),
            )

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.root / "central.sqlite", timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _job(self, db, job_id):
        row = db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise ValueError("Unknown job")
        job = json.loads(row[0])
        if "skill_runs" not in job:
            job["skill_runs"] = job.get("workflow_runs", {})
        return job

    def _put(self, db, job):
        newly_terminal = False
        if job["status"] in TERMINAL and not job.get("ended_at"):
            previous = db.execute("SELECT data FROM jobs WHERE id=?", (job["id"],)).fetchone()
            if not previous or json.loads(previous[0])["status"] not in TERMINAL:
                job["ended_at"] = time.time()
                newly_terminal = True
                job["elapsed_seconds"] = (
                    round(max(0, job["ended_at"] - job["started_at"]), 2) if job.get("started_at") else 0
                )
        db.execute("INSERT OR REPLACE INTO jobs VALUES(?,?)", (job["id"], canonical(job)))
        if newly_terminal:
            self.learning_terminal(db, job)

    def _event(self, db, job_id, kind, data):
        db.execute(
            "INSERT INTO events(job_id,kind,at,data) VALUES(?,?,?,?)",
            (job_id, kind, time.time(), canonical(data)),
        )

    def create_job(self, inputs, model_mode="simulated", timeout=900, *, staff_id="staff", ongoing=False):
        from eas_server.roles import get_role

        role = get_role(inputs.get("role_id", "invoice_correction"))
        inputs = role.normalize(inputs, allow_unbound=ongoing)
        if inputs.get("selected_mode", "strict") != "strict":
            raise ValueError("Auto mode has been removed; staff approval is required")
        inputs["selected_mode"] = "strict"
        inputs["staff_id"] = staff_id
        request_fields = (
            "conversation_id",
            "staff_id",
            "task",
            "organization_id",
            "role_id",
            "inputs",
            "permissions",
        )
        request_payload = {k: inputs.get(k) for k in request_fields}
        with self.db() as db:
            if inputs.get("request_id"):
                for row in db.execute(
                    "SELECT data FROM jobs WHERE json_extract(data,'$.request_id')=?", (inputs["request_id"],)
                ):
                    previous = json.loads(row[0])
                    if any(
                        previous.get("request_payload", previous).get(k) != inputs.get(k)
                        for k in request_fields
                    ):
                        raise ValueError("Request identity reused with different inputs")
                    return previous
            if (
                ongoing
                and db.execute(
                    "SELECT 1 FROM jobs WHERE json_extract(data,'$.conversation_id')=? AND json_extract(data,'$.status') NOT IN ('completed','failed','denied','cancelled','rejected')",
                    (inputs["conversation_id"],),
                ).fetchone()
            ):
                raise Stale("A request is already active in this conversation")
            if not inputs.get("conversation_id"):
                inputs["conversation_id"] = uid()
            inputs["request_id"] = inputs.get("request_id") or uid()
            release = json.loads(db.execute("SELECT data FROM kv WHERE key='release'").fetchone()[0])
            job = dict(
                inputs,
                id=uid(),
                status="queued",
                effective_mode=inputs["selected_mode"],
                controller="script",
                execution_engine="agent-led-1",
                conversation_request=ongoing,
                request_payload=request_payload,
                created_at=time.time(),
                started_at=None,
                timeout=timeout,
                graph_version=release["version"],
                amount_labels=release["labels"],
                completed=[],
                expected=None,
                mutation="not_attempted",
                model_mode=model_mode,
                app_version="demobooks-windows-1"
                if inputs.get("application") == "DemoBooks Desktop (Windows)"
                else "mock-1",
                accepted=False,
                model_calls=0,
                tokens=0,
                recoveries=0,
                fallback_count=0,
                checkpoint=None,
                elapsed_seconds=0,
                pending_mode=None,
            )
            self._put(db, job)
            self._event(db, job["id"], "job_created", job)
            return job

    def bind_record(self, job_id, record_id):
        """Resolve an unbound chat request only inside its exact approved tool call."""
        from eas_server.roles import get_role

        with self.db() as db:
            job = self._job(db, job_id)
            record_field = get_role(job["role_id"]).record_field
            lease = self._lease(db, job)
            self._check(job, lease, "assistant", lease["epoch"])
            row = db.execute(
                "SELECT data FROM approvals WHERE job_id=? AND invocation=? ORDER BY rowid DESC LIMIT 1",
                (job_id, lease["inflight"]),
            ).fetchone()
            approval = json.loads(row[0]) if row else {}
            if (
                not job.get("conversation_request")
                or "read" not in job["permissions"]
                or approval.get("status") != "executing"
                or approval.get("name") != "select_record"
                or approval.get("epoch") != lease["epoch"]
                or approval.get("corrected_arguments", approval.get("arguments")) != {record_field: record_id}
            ):
                raise PermissionError("Selecting a record requires approval of that exact tool call")
            if job.get("record_id") is not None and job["record_id"] != record_id:
                raise PermissionError("An active request cannot switch records")
            if job.get("record_id") is None:
                normalized = get_role(job["role_id"]).normalize(
                    {
                        **job,
                        record_field: record_id,
                        "inputs": {**job["inputs"], record_field: record_id},
                    }
                )
                job.update({k: normalized[k] for k in ("inputs", record_field, "record_id")})
                self._put(db, job)
                self._event(
                    db, job_id, "record_selected", {record_field: record_id, "invocation": lease["inflight"]}
                )
            value = {"data": {"company_id": job["company_id"], record_field: job[record_field]}}
            # Scope and the consumed approval/result are one commit. Losing the
            # RPC response cannot lose a staff correction or strand the lease.
            self._finish_action(
                db,
                job_id,
                lease["inflight"],
                {"value": value, "after": approval["observation"]},
                approval["id"],
            )
            return value

    def get_job(self, job_id):
        with self.db() as db:
            return self._job(db, job_id)

    def list_jobs(self):
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM jobs ORDER BY rowid DESC")]

    def update_job(self, job_id, updates):
        allowed = {
            "status",
            "effective_mode",
            "controller",
            "completed",
            "expected",
            "mutation",
            "model_calls",
            "tokens",
            "recoveries",
            "fallback_count",
            "checkpoint",
            "error",
            "elapsed_seconds",
            "assistance_thread",
            "assistant_report",
            "operation_failures",
            "model_guidance_revision",
            "model_binding",
            "result_kind",
            "skill_runs",
            "execution_state",
            "verified_report",
            "skill_reads",
            "operation_trace",
            "record_lookup",
        }
        if set(updates) - allowed:
            raise ValueError("Worker cannot change authorization or pinned version")
        with self.db() as db:
            job = self._job(db, job_id)
            if job["status"] in TERMINAL:
                raise Stopped(job["status"])
            if "effective_mode" in updates and updates["effective_mode"] != "strict":
                raise ValueError("Only Strict approval is supported")
            job.update(updates)
            if job["status"] in TERMINAL:
                self._invalidate(db, job_id)
            self._put(db, job)
            return job

    def event(self, job_id, kind, data):
        with self.db() as db:
            self._event(db, job_id, kind, data)

    def conversation(self, job_id):
        from eas_server.conversation import Conversation

        return Conversation(self).read(job_id)

    def ask_staff(self, job_id, question):
        from eas_server.conversation import Conversation

        return Conversation(self).ask(job_id, question)

    def events(self, job_id, after=0):
        with self.db() as db:
            return [
                dict(seq=r["seq"], kind=r["kind"], at=r["at"], data=json.loads(r["data"]))
                for r in db.execute(
                    "SELECT * FROM events WHERE job_id=? AND seq>? ORDER BY seq", (job_id, after)
                )
            ]

    def _lease(self, db, job=None):
        desktop = (job or {}).get("desktop_id") or desktop_context.get()
        if desktop:
            empty = dict(job_id=None, owner=None, epoch=0, expires=0, inflight=None, desktop_id=desktop)
            db.execute("INSERT OR IGNORE INTO desktop_leases VALUES(?,?)", (desktop, canonical(empty)))
            return json.loads(
                db.execute("SELECT data FROM desktop_leases WHERE id=?", (desktop,)).fetchone()[0]
            )
        legacy = json.loads(db.execute("SELECT data FROM lease WHERE id=1").fetchone()[0])
        # Local test/admin inspection may address a sole desktop; HTTP callers bind
        # their own context before reaching this method.
        rows = db.execute("SELECT data FROM desktop_leases").fetchall()
        return json.loads(rows[0][0]) if len(rows) == 1 and not legacy.get("job_id") else legacy

    def lease(self):
        with self.db() as db:
            return self._lease(db)

    def _set_lease(self, db, lease):
        if lease.get("desktop_id"):
            db.execute(
                "INSERT OR REPLACE INTO desktop_leases VALUES(?,?)", (lease["desktop_id"], canonical(lease))
            )
        else:
            db.execute("UPDATE lease SET data=? WHERE id=1", (canonical(lease),))

    def _invalidate(self, db, job_id):
        for row in db.execute("SELECT id,data FROM approvals WHERE job_id=?", (job_id,)).fetchall():
            a = json.loads(row["data"])
            if a["status"] in {"pending", "approved", "corrected"}:
                a["status"] = "stale"
                db.execute("UPDATE approvals SET data=? WHERE id=?", (canonical(a), row["id"]))

    def claim(self, worker_id, scope=None):
        def authorized(job):
            return scope is None or (
                job["organization_id"] == scope["organization_id"]
                and job["role_id"] in scope["role_ids"]
                and ("predicate" not in scope or scope["predicate"](job))
            )

        with self.db() as db:
            lease = self._lease(db)
            if lease["job_id"]:
                job = self._job(db, lease["job_id"])
                if job["status"] in TERMINAL and lease.get("inflight"):
                    # Cancellation cannot release a desktop while its effect is
                    # still in flight. A matching receipt or reconciliation must
                    # finish before another request can acquire this desktop.
                    return None
                if job["status"] not in TERMINAL:
                    if (
                        job.get("selected_mode") != "strict"
                        or job.get("effective_mode") != "strict"
                        or job.get("pending_mode") == "auto"
                    ):
                        job.update(status="cancelled", error="Auto mode retired; submit a new Strict request")
                        self._invalidate(db, job["id"])
                        self._put(db, job)
                        self._event(db, job["id"], "approval_policy_migrated", {"policy": "strict"})
                        return None
                    if not authorized(job):
                        return None
                    if lease.get("worker_id") != worker_id and lease["expires"] > time.time():
                        return None
                    if lease.get("worker_id") != worker_id:
                        lease.update(epoch=lease["epoch"] + 1, inflight=None)
                        self._invalidate(db, job["id"])
                        self._event(
                            db,
                            job["id"],
                            "worker_restarted",
                            {"message": "Reacquired control; reconcile external state"},
                        )
                    lease.update(worker_id=worker_id, expires=time.time() + 30)
                    self._set_lease(db, lease)
                    return job
            jobs = (
                json.loads(row[0])
                for row in db.execute(
                    "SELECT data FROM jobs WHERE json_extract(data,'$.status')='queued' ORDER BY rowid"
                )
            )
            job = next((job for job in jobs if authorized(job)), None)
            if job is None:
                return None
            if (
                job.get("selected_mode") != "strict"
                or job.get("effective_mode") != "strict"
                or job.get("pending_mode") == "auto"
            ):
                job.update(status="cancelled", error="Auto mode retired; submit a new Strict request")
                self._put(db, job)
                self._event(db, job["id"], "approval_policy_migrated", {"policy": "strict"})
                return None
            job.update(status="running", execution_state="running", started_at=time.time())
            if lease.get("desktop_id"):
                job["desktop_id"] = lease["desktop_id"]
            lease.update(
                job_id=job["id"],
                owner="script",
                worker_id=worker_id,
                epoch=lease["epoch"] + 1,
                expires=time.time() + 30,
                inflight=None,
            )
            self._set_lease(db, lease)
            self._put(db, job)
            return job

    def add_knowledge(self, document):
        from eas_shared.types import KnowledgeDocument
        from eas_server.roles import get_role

        document = KnowledgeDocument.model_validate(document).model_dump()
        if document["role_id"] and (
            not document["department_id"]
            or get_role(document["role_id"]).department_id != document["department_id"]
        ):
            raise ValueError("Role knowledge must specify its matching department")
        record = dict(document, id=uid(), revision=1, created_at=time.time())
        with self.db() as db:
            db.execute("INSERT INTO knowledge VALUES(?,?)", (record["id"], canonical(record)))
        return record

    def search_knowledge(self, job_id, query):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
            raise ValueError("Knowledge query must contain 1 to 500 characters")
        terms = set(re.findall(r"\w+", query.casefold()))
        if not terms:
            raise ValueError("Knowledge query must contain a search term")
        with self.db() as db:
            job = self._job(db, job_id)
            if "read" not in job["permissions"]:
                raise PermissionError("Knowledge access requires read permission")
            lease = self._lease(db)
            self._check(job, lease, "assistant", lease["epoch"])
            row = db.execute(
                "SELECT data FROM approvals WHERE job_id=? AND invocation=? ORDER BY rowid DESC LIMIT 1",
                (job_id, lease["inflight"]),
            ).fetchone()
            approval = json.loads(row[0]) if row else {}
            if (
                approval.get("status") != "executing"
                or approval.get("name") != "search_knowledge"
                or approval.get("corrected_arguments", approval.get("arguments")) != {"query": query}
            ):
                raise PermissionError("Knowledge retrieval requires approval of this exact search")
            rows = db.execute(
                """SELECT data FROM knowledge
                   WHERE json_extract(data,'$.organization_id')=?
                   AND (json_extract(data,'$.department_id') IS NULL OR json_extract(data,'$.department_id')=?)
                   AND (json_extract(data,'$.role_id') IS NULL OR json_extract(data,'$.role_id')=?)
                   AND (json_extract(data,'$.company_id') IS NULL OR json_extract(data,'$.company_id')=?)""",
                (job["organization_id"], job["department_id"], job["role_id"], job.get("company_id")),
            ).fetchall()
            matches = []
            for row in rows:
                document = json.loads(row[0])
                words = set(re.findall(r"\w+", (document["title"] + " " + document["content"]).casefold()))
                score = len(terms & words)
                if score:
                    matches.append((score, document))
            documents = [doc for _, doc in sorted(matches, key=lambda item: (-item[0], item[1]["id"]))[:3]]
            result = {"query": query, "documents": documents}
            self._event(
                db,
                job_id,
                "knowledge_retrieved",
                {
                    "query": query,
                    "documents": [{"id": d["id"], "revision": d["revision"]} for d in documents],
                },
            )
            return result

    def check(self, job_id, owner, epoch):
        with self.db() as db:
            job = self._job(db, job_id)
            lease = self._lease(db, job)
            self._check(job, lease, owner, epoch)
            return job

    def _check(self, job, lease, owner, epoch):
        if job["status"] in TERMINAL:
            raise Stopped(job["status"])
        if job["started_at"] and time.time() - job["started_at"] > job["timeout"]:
            raise Stopped("Execution time budget exceeded")
        if (
            lease["job_id"] != job["id"]
            or lease["owner"] != owner
            or lease["epoch"] != epoch
            or lease["expires"] < time.time()
        ):
            raise Stale("Desktop ownership changed or lease expired")

    def transfer(self, job_id, owner, expected_epoch=None):
        if owner not in {"script", "assistant", "staff"}:
            raise ValueError("Unknown controller")
        with self.db() as db:
            job = self._job(db, job_id)
            lease = self._lease(db, job)
            if job["status"] in TERMINAL or lease["job_id"] != job_id:
                raise Stopped("Job does not own this desktop")
            if expected_epoch is not None and expected_epoch != lease["epoch"]:
                raise Stale("Stale handoff")
            if lease["inflight"]:
                raise Stale("An action is in flight; retry handoff after it is reconciled")
            self._invalidate(db, job_id)
            lease.update(owner=owner, epoch=lease["epoch"] + 1, expires=time.time() + 30)
            self._set_lease(db, lease)
            job.update(controller=owner, effective_mode="strict")
            self._put(db, job)
            self._event(db, job_id, "control_transferred", dict(owner=owner, epoch=lease["epoch"]))
            return lease

    def mode(self, job_id, mode):
        if mode != "strict":
            raise ValueError("Auto mode has been removed; staff approval is required")
        with self.db() as db:
            job = self._job(db, job_id)
            if job["status"] in TERMINAL:
                raise Stopped("Job has ended")
            job["pending_mode"] = mode
            self._put(db, job)
            self._event(db, job_id, "mode_requested", {"mode": mode})
            return job

    def boundary(self, job_id):
        with self.db() as db:
            job = self._job(db, job_id)
            job.update(selected_mode="strict", effective_mode="strict", pending_mode=None)
            self._put(db, job)
            return job

    def stop(self, job_id, status="cancelled"):
        with self.db() as db:
            job = self._job(db, job_id)
            if job["status"] in TERMINAL:
                return job
            job.update(status=status, error=status)
            self._put(db, job)
            self._invalidate(db, job_id)
            self._event(db, job_id, status, {})
            return job

    def proposal(self, job_id, invocation, proposal):
        with self.db() as db:
            for row in db.execute(
                "SELECT data FROM approvals WHERE job_id=? AND invocation=? ORDER BY rowid DESC",
                (job_id, invocation),
            ):
                a = json.loads(row[0])
                if a["status"] in {"pending", "approved", "corrected", "executing"}:
                    return a
            a = dict(
                proposal,
                id=uid(),
                job_id=job_id,
                invocation=invocation,
                status="pending",
                created_at=time.time(),
                decision=None,
                executed_action=None,
                observed_result=None,
            )
            db.execute("INSERT INTO approvals VALUES(?,?,?,?)", (a["id"], job_id, invocation, canonical(a)))
            self._event(db, job_id, "approval_requested", a)
            return a

    def approvals(self, job_id):
        with self.db() as db:
            return [
                json.loads(r[0])
                for r in db.execute("SELECT data FROM approvals WHERE job_id=? ORDER BY rowid", (job_id,))
            ]

    def decide(self, approval_id, decision, actor="staff"):
        with self.db() as db:
            row = db.execute("SELECT data FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if not row:
                raise ValueError("Unknown approval")
            a = json.loads(row[0])
            job = self._job(db, a["job_id"])
            if a["status"] != "pending" or job["status"] in TERMINAL:
                raise Stale("Decision already submitted, stale, or job ended")
            if decision["decision"] == "correct" and a["kind"] != "tool":
                raise ValueError("Only tool arguments can be corrected")
            a["decision"] = dict(decision, actor=actor, at=time.time())
            a["status"] = {"approve": "approved", "correct": "corrected", "reject": "rejected"}[
                decision["decision"]
            ]
            if a["status"] == "corrected":
                if not isinstance(decision.get("arguments"), dict):
                    raise ValueError("Corrected arguments required")
                a["corrected_arguments"] = decision["arguments"]
            db.execute("UPDATE approvals SET data=? WHERE id=?", (canonical(a), approval_id))
            self._event(db, job["id"], "staff_decision", a)
            if a["status"] == "rejected":
                job["status"] = "rejected"
                self._put(db, job)
                self._invalidate(db, job["id"])
            return a

    def stale_approval(self, approval_id):
        with self.db() as db:
            a = json.loads(db.execute("SELECT data FROM approvals WHERE id=?", (approval_id,)).fetchone()[0])
            a["status"] = "stale"
            db.execute("UPDATE approvals SET data=? WHERE id=?", (canonical(a), approval_id))
            self._event(db, a["job_id"], "stale_proposal", {"approval_id": approval_id})

    def begin_window_recovery(self, job_id, owner, epoch, invocation):
        """Reserve non-business setup of the assigned window before capturing a preview."""
        with self.db() as db:
            job = self._job(db, job_id)
            lease = self._lease(db, job)
            self._check(job, lease, owner, epoch)
            if owner == "staff" or lease["inflight"]:
                raise Stale("Desktop is not available for window recovery")
            lease["inflight"] = invocation
            self._set_lease(db, lease)
            self._event(db, job_id, "window_recovery_started", {"invocation": invocation})

    def finish_window_recovery(self, job_id, invocation, result):
        with self.db() as db:
            job = self._job(db, job_id)
            lease = self._lease(db, job)
            started = db.execute(
                "SELECT 1 FROM events WHERE job_id=? AND kind='window_recovery_started' AND json_extract(data,'$.invocation')=?",
                (job_id, invocation),
            ).fetchone()
            if (
                not started
                or lease.get("inflight") != invocation
                or type(result.get("recovered")) is not bool
            ):
                raise PermissionError("No matching window recovery is in progress")
            lease["inflight"] = None
            self._set_lease(db, lease)
            self._event(
                db,
                job_id,
                "window_recovery_finished",
                {"invocation": invocation, "recovered": result["recovered"]},
            )

    def begin_action(self, job_id, owner, epoch, invocation, action, approval_id=None, *, authorization=None):
        with self.db() as db:
            job = self._job(db, job_id)
            lease = self._lease(db, job)
            self._check(job, lease, owner, epoch)
            if authorization:
                authorization(db, job, lease)
            if lease["inflight"] and lease["inflight"] != invocation:
                raise Stale("Another desktop operation is in flight")
            if approval_id:
                a = json.loads(
                    db.execute("SELECT data FROM approvals WHERE id=?", (approval_id,)).fetchone()[0]
                )
                if a["status"] not in {"approved", "corrected"} or a["epoch"] != epoch:
                    raise Stale("Approval unavailable or consumed")
                if a["invocation"] != invocation or a["job_id"] != job_id:
                    raise Stale("Approval invocation mismatch")
                expected_arguments = a.get("corrected_arguments", a["arguments"])
                if (
                    action.get("name") != a["name"]
                    or action.get("arguments") != expected_arguments
                    or action.get("observation_revision") != a["observation"]["revision"]
                ):
                    raise Stale("Executable action differs from approved proposal")
                a.update(status="executing", executed_action=action)
                db.execute("UPDATE approvals SET data=? WHERE id=?", (canonical(a), approval_id))
            else:
                raise Stale("Approval required by shared execution layer")
            lease["inflight"] = invocation
            self._set_lease(db, lease)
            self._event(db, job_id, "action_started", dict(invocation=invocation, action=action, owner=owner))

    def finish_action(self, job_id, invocation, result, approval_id=None, cache=True):
        with self.db() as db:
            self._finish_action(db, job_id, invocation, result, approval_id, cache)

    def _finish_action(self, db, job_id, invocation, result, approval_id=None, cache=True):
        if cache:
            db.execute(
                "INSERT OR REPLACE INTO invocations VALUES(?,?,?)",
                (invocation, job_id, canonical(result)),
            )
        lease = self._lease(db, self._job(db, job_id))
        if lease["inflight"] == invocation:
            lease["inflight"] = None
            self._set_lease(db, lease)
        if approval_id:
            a = json.loads(db.execute("SELECT data FROM approvals WHERE id=?", (approval_id,)).fetchone()[0])
            a.update(status="executed", observed_result=result)
            db.execute("UPDATE approvals SET data=? WHERE id=?", (canonical(a), approval_id))
        self._event(db, job_id, "action_result", dict(invocation=invocation, result=result))

    def result(self, invocation):
        with self.db() as db:
            r = db.execute("SELECT result FROM invocations WHERE id=?", (invocation,)).fetchone()
            return json.loads(r[0]) if r else None

    def conclude(self, job_id):
        """Completion classification follows execution receipts, never planner assertions."""
        job = self.get_job(job_id)
        approvals = self.approvals(job_id)
        executed = {a["name"] for a in approvals if a["status"] == "executed"}
        if any(a["status"] in {"pending", "approved", "corrected", "executing"} for a in approvals):
            raise Stale("Outstanding business operation")
        if "complete" in executed:
            kind = "verified_work"
        elif "review_discovery" in executed:
            kind = "reviewed_outcome"
        elif job.get("record_lookup"):
            kind = "record_unavailable"
        elif not executed - {"select_record", "capture_screen", "share_screenshot"}:
            kind = "conversation"
        else:
            raise PermissionError("Business completion requires verified execution or staff outcome review")
        if any(
            r["state"] not in {"completed", "record_unavailable"} for r in job.get("skill_runs", {}).values()
        ):
            raise Stale("Workflow is not finished")
        with self.db() as db:
            current = self._job(db, job_id)
            if current["status"] in TERMINAL:
                raise Stopped(current["status"])
            current.update(
                status="completed",
                execution_state="completed",
                result_kind=kind,
                evidence_status="executor_reported" if executed else "conversation",
            )
            self._invalidate(db, job_id)
            self._put(db, current)
        return current

    def accept(self, job_id):
        with self.db() as db:
            job = self._job(db, job_id)
            if job["status"] != "completed":
                raise ValueError("Only verified completed jobs can be accepted")
            assessments = {}
            for row in db.execute(
                "SELECT data FROM events WHERE job_id=? AND kind='action_assessment' ORDER BY seq", (job_id,)
            ):
                assessment = json.loads(row[0])
                assessments[assessment["invocation"]] = assessment["outcome"]
            if "incorrect" in assessments.values():
                raise ValueError("Resolve reported incorrect operations before accepting this episode")
            job["accepted"] = True
            job["evidence_status"] = "staff_accepted"
            reviewed = db.execute(
                "SELECT 1 FROM approvals WHERE job_id=? AND json_extract(data,'$.name')='review_discovery' AND json_extract(data,'$.status')='executed'",
                (job_id,),
            ).fetchone()
            if (
                job.get("operation_trace")
                and (job.get("verified_report") or job["mutation"] == "confirmed_succeeded")
            ) or (job.get("result_kind") == "reviewed_outcome" and reviewed):
                item = dict(
                    id=job_id,
                    kind="learn",
                    job_id=job_id,
                    organization_id=job["organization_id"],
                    role_id=job["role_id"],
                    status="queued",
                    created_at=time.time(),
                    related_job_ids=self.related_learning_jobs(db, job),
                )
                db.execute("INSERT OR IGNORE INTO maintenance VALUES(?,?)", (job_id, canonical(item)))
            self._put(db, job)
            self._event(db, job_id, "staff_accepted", {})
            return job

    def relevant_episodes(self, job_id, reason=""):
        job = self.get_job(job_id)
        return [
            dict(episode_id=j["id"], task=j["task"], version=j["graph_version"], expected=j["expected"])
            for j in self.list_jobs()
            if j["id"] != job_id
            and j.get("organization_id", "acme") == job.get("organization_id", "acme")
            and j.get("department_id", "finance") == job.get("department_id", "finance")
            and j.get("role_id", "invoice_correction") == job.get("role_id", "invoice_correction")
            and j.get("company_id") == job.get("company_id")
            and j["task"] == job["task"]
            and j["accepted"]
            and j["graph_version"] == job["graph_version"]
            and j.get("app_version", "mock-1") == job.get("app_version", "mock-1")
            and (
                not reason
                or any(
                    e["kind"] == "recovery_required" and e["data"].get("reason") == reason
                    for e in self.events(j["id"])
                )
            )
        ][:3]

    def get_value(self, key):
        with self.db() as db:
            r = db.execute("SELECT data FROM kv WHERE key=?", (key,)).fetchone()
            return json.loads(r[0]) if r else None

    def put_value(self, key, value):
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (key, canonical(value)))
