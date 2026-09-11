"""Transactional central persistence. Worker access is a restricted HTTP RPC boundary."""

from contextlib import contextmanager
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import time
import uuid
from .types import TERMINAL, Stale, Stopped


def uid():
    return uuid.uuid4().hex


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Store:
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
            CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, data TEXT);
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
        return json.loads(row[0])

    def _put(self, db, job):
        db.execute("INSERT OR REPLACE INTO jobs VALUES(?,?)", (job["id"], canonical(job)))

    def _event(self, db, job_id, kind, data):
        db.execute(
            "INSERT INTO events(job_id,kind,at,data) VALUES(?,?,?,?)",
            (job_id, kind, time.time(), canonical(data)),
        )

    def create_job(self, inputs, model_mode="simulated", timeout=900):
        from .roles import get_role

        inputs = get_role(inputs.get("role_id", "invoice_correction")).normalize(inputs)
        with self.db() as db:
            release = json.loads(db.execute("SELECT data FROM kv WHERE key='release'").fetchone()[0])
            job = dict(
                inputs,
                id=uid(),
                status="queued",
                effective_mode=inputs["selected_mode"],
                controller="script",
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
        }
        if set(updates) - allowed:
            raise ValueError("Worker cannot change authorization or pinned version")
        with self.db() as db:
            job = self._job(db, job_id)
            if job["status"] in TERMINAL:
                raise Stopped(job["status"])
            job.update(updates)
            if job["status"] in TERMINAL:
                self._invalidate(db, job_id)
            self._put(db, job)
            return job

    def event(self, job_id, kind, data):
        with self.db() as db:
            self._event(db, job_id, kind, data)

    def conversation(self, job_id):
        from .conversation import Conversation

        return Conversation(self).read(job_id)

    def ask_staff(self, job_id, question):
        from .conversation import Conversation

        return Conversation(self).ask(job_id, question)

    def events(self, job_id, after=0):
        with self.db() as db:
            return [
                dict(seq=r["seq"], kind=r["kind"], at=r["at"], data=json.loads(r["data"]))
                for r in db.execute(
                    "SELECT * FROM events WHERE job_id=? AND seq>? ORDER BY seq", (job_id, after)
                )
            ]

    def lease(self):
        with self.db() as db:
            return json.loads(db.execute("SELECT data FROM lease WHERE id=1").fetchone()[0])

    def _set_lease(self, db, lease):
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
                job["organization_id"] == scope["organization_id"] and job["role_id"] in scope["role_ids"]
            )

        with self.db() as db:
            lease = json.loads(db.execute("SELECT data FROM lease WHERE id=1").fetchone()[0])
            if lease["job_id"]:
                job = self._job(db, lease["job_id"])
                if job["status"] not in TERMINAL:
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
            job.update(status="running", started_at=time.time())
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
        from .types import KnowledgeDocument
        from .roles import get_role

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
            lease = json.loads(db.execute("SELECT data FROM lease WHERE id=1").fetchone()[0])
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
            lease = json.loads(db.execute("SELECT data FROM lease WHERE id=1").fetchone()[0])
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
            lease = json.loads(db.execute("SELECT data FROM lease WHERE id=1").fetchone()[0])
            if job["status"] in TERMINAL or lease["job_id"] != job_id:
                raise Stopped("Job does not own this desktop")
            if expected_epoch is not None and expected_epoch != lease["epoch"]:
                raise Stale("Stale handoff")
            if lease["inflight"]:
                raise Stale("An action is in flight; retry handoff after it is reconciled")
            self._invalidate(db, job_id)
            lease.update(owner=owner, epoch=lease["epoch"] + 1, expires=time.time() + 30)
            self._set_lease(db, lease)
            job.update(
                controller=owner, effective_mode="strict" if owner != "script" else job["selected_mode"]
            )
            self._put(db, job)
            self._event(db, job_id, "control_transferred", dict(owner=owner, epoch=lease["epoch"]))
            return lease

    def mode(self, job_id, mode):
        if mode not in {"strict", "auto"}:
            raise ValueError("Invalid mode")
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
            if job["pending_mode"]:
                job.update(selected_mode=job["pending_mode"], pending_mode=None)
                self._put(db, job)
            job["effective_mode"] = "strict" if job["controller"] != "script" else job["selected_mode"]
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
                "SELECT data FROM approvals WHERE invocation=? ORDER BY rowid DESC", (invocation,)
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
            lease = json.loads(db.execute("SELECT data FROM lease WHERE id=1").fetchone()[0])
            self._check(job, lease, owner, epoch)
            if owner == "staff" or lease["inflight"]:
                raise Stale("Desktop is not available for window recovery")
            lease["inflight"] = invocation
            self._set_lease(db, lease)
            self._event(db, job_id, "window_recovery_started", {"invocation": invocation})

    def begin_action(self, job_id, owner, epoch, invocation, action, approval_id=None):
        with self.db() as db:
            job = self._job(db, job_id)
            lease = json.loads(db.execute("SELECT data FROM lease WHERE id=1").fetchone()[0])
            self._check(job, lease, owner, epoch)
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
            elif owner == "assistant" or job["effective_mode"] == "strict":
                raise Stale("Approval required by shared execution layer")
            lease["inflight"] = invocation
            self._set_lease(db, lease)
            self._event(db, job_id, "action_started", dict(invocation=invocation, action=action, owner=owner))

    def finish_action(self, job_id, invocation, result, approval_id=None, cache=True):
        with self.db() as db:
            if cache:
                db.execute(
                    "INSERT OR REPLACE INTO invocations VALUES(?,?,?)",
                    (invocation, job_id, canonical(result)),
                )
            lease = json.loads(db.execute("SELECT data FROM lease WHERE id=1").fetchone()[0])
            if lease["inflight"] == invocation:
                lease["inflight"] = None
                self._set_lease(db, lease)
            if approval_id:
                a = json.loads(
                    db.execute("SELECT data FROM approvals WHERE id=?", (approval_id,)).fetchone()[0]
                )
                a.update(status="executed", observed_result=result)
                db.execute("UPDATE approvals SET data=? WHERE id=?", (canonical(a), approval_id))
            self._event(db, job_id, "action_result", dict(invocation=invocation, result=result))

    def result(self, invocation):
        with self.db() as db:
            r = db.execute("SELECT result FROM invocations WHERE id=?", (invocation,)).fetchone()
            return json.loads(r[0]) if r else None

    def accept(self, job_id):
        with self.db() as db:
            job = self._job(db, job_id)
            if job["status"] != "completed":
                raise ValueError("Only verified completed jobs can be accepted")
            job["accepted"] = True
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
