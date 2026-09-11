"""Durable staff guidance and individually approved assistant questions."""

import json
import time

from pydantic import BaseModel, ConfigDict, Field

from enterprise.shared.identity import canonical, uid
from enterprise.shared.types import Recovery, Stale, Stopped, TERMINAL


class StaffMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=4000)
    message_id: str = Field(default_factory=uid, min_length=1, max_length=128)
    reply_to: str | None = Field(default=None, max_length=128)


class Conversation:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS questions(
                id TEXT PRIMARY KEY, job_id TEXT NOT NULL, invocation TEXT NOT NULL,
                data TEXT NOT NULL, UNIQUE(job_id, invocation))""")

    def read(self, job_id, require_read=True):
        with self.store.db() as db:
            job = self.store._job(db, job_id)
            if require_read and "read" not in job["permissions"]:
                raise PermissionError("Conversation retrieval requires read permission")
            messages = [
                dict(json.loads(r["data"]), seq=r["seq"], at=r["at"])
                for r in db.execute(
                    "SELECT seq,at,data FROM events WHERE job_id=? AND kind='staff_message' ORDER BY seq DESC LIMIT 20",
                    (job_id,),
                )
            ][::-1]
            questions = [
                json.loads(r[0])
                for r in db.execute("SELECT data FROM questions WHERE job_id=? ORDER BY rowid", (job_id,))
            ]
            return {
                "messages": messages,
                "questions": questions,
                "revision": messages[-1]["seq"] if messages else 0,
            }

    def message(self, job_id, message):
        message = StaffMessage.model_validate(message).model_dump()
        if not message["text"].strip():
            raise ValueError("Message cannot be blank")
        with self.store.db() as db:
            job = self.store._job(db, job_id)
            existing = db.execute(
                "SELECT data FROM events WHERE job_id=? AND kind='staff_message' AND json_extract(data,'$.message_id')=?",
                (job_id, message["message_id"]),
            ).fetchone()
            if existing:
                if json.loads(existing[0]) != message:
                    raise Stale("Message identifier already used for different content")
                return {"ok": True, "message_id": message["message_id"]}
            if job["status"] in TERMINAL:
                raise Stopped("The job has ended")
            if message["reply_to"]:
                row = db.execute(
                    "SELECT data FROM questions WHERE id=? AND job_id=?", (message["reply_to"], job_id)
                ).fetchone()
                if not row:
                    raise ValueError("Question does not belong to this job")
                question = json.loads(row[0])
                if question["status"] != "pending":
                    raise Stale("Question already answered")
                question.update(status="answered", answer=message["text"], message_id=message["message_id"])
                db.execute(
                    "UPDATE questions SET data=? WHERE id=?", (canonical(question), question["question_id"])
                )
                self.store._event(db, job_id, "staff_answered", question)
            self.store._event(db, job_id, "staff_message", message)
            # Guidance never counts as action approval. Old queued proposals must
            # be reconsidered; already executing actions remain fenced normally.
            self.store._invalidate(db, job_id)
            return {"ok": True, "message_id": message["message_id"]}

    def ask(self, job_id, question):
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
            raise ValueError("Question must contain 1 to 2000 characters")
        with self.store.db() as db:
            job = self.store._job(db, job_id)
            if "read" not in job["permissions"]:
                raise PermissionError("Questions require read permission")
            lease = json.loads(db.execute("SELECT data FROM lease WHERE id=1").fetchone()[0])
            self.store._check(job, lease, "assistant", lease["epoch"])
            row = db.execute(
                "SELECT data FROM approvals WHERE job_id=? AND invocation=? ORDER BY rowid DESC LIMIT 1",
                (job_id, lease["inflight"]),
            ).fetchone()
            approval = json.loads(row[0]) if row else {}
            if (
                approval.get("status") != "executing"
                or approval.get("name") != "ask_staff"
                or approval.get("corrected_arguments", approval.get("arguments")) != {"question": question}
            ):
                raise PermissionError("Publishing a question requires approval of that exact tool call")
            existing = db.execute(
                "SELECT data FROM questions WHERE job_id=? AND invocation=?", (job_id, lease["inflight"])
            ).fetchone()
            if existing:
                return json.loads(existing[0])
            if db.execute(
                "SELECT 1 FROM questions WHERE job_id=? AND json_extract(data,'$.status')='pending'",
                (job_id,),
            ).fetchone():
                raise Recovery(
                    "unfamiliar", "Wait for the outstanding staff answer before asking another question"
                )
            record = {
                "question_id": uid(),
                "question": question,
                "status": "pending",
                "created_at": time.time(),
            }
            db.execute(
                "INSERT INTO questions VALUES(?,?,?,?)",
                (record["question_id"], job_id, lease["inflight"], canonical(record)),
            )
            self.store._event(db, job_id, "assistant_question", dict(record, text=question))
            return record
