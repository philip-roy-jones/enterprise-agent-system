"""Durable maintenance scheduling and metadata, never agent execution."""

import json
import time
import re
import hashlib
from eas_shared.identity import canonical, uid
from eas_shared.types import Stale


class LearningStore:
    @staticmethod
    def learning_family(job):
        skills = sorted({r["skill_id"] for r in job.get("workflow_runs", {}).values() if r.get("skill_id")})
        task = re.sub(r"\b(?:INV|PO)-?\d+\b|\d+", "record", job["task"], flags=re.I).lower()
        return canonical(
            [
                *[job.get(k) for k in ("organization_id", "department_id", "role_id", "company_id")],
                skills or task,
            ]
        )

    def related_learning_jobs(self, db, job):
        family = self.learning_family(job)
        return [
            other["id"]
            for row in db.execute("SELECT data FROM jobs ORDER BY rowid DESC")
            if (other := json.loads(row[0]))["id"] != job["id"]
            and self.learning_family(other) == family
            and other["status"] in {"completed", "failed", "denied", "rejected"}
        ][:5]

    def queue_learning_review(self, db, job, trigger, *, related=None, revision=""):
        identity = hashlib.sha256(canonical([job["id"], trigger, revision]).encode()).hexdigest()
        item = dict(
            id="review-" + identity,
            kind="review",
            job_id=job["id"],
            trigger=trigger,
            related_job_ids=related or [],
            organization_id=job["organization_id"],
            role_id=job["role_id"],
            status="queued",
            created_at=time.time(),
        )
        db.execute("INSERT OR IGNORE INTO maintenance VALUES(?,?)", (item["id"], canonical(item)))

    def learning_terminal(self, db, job):
        related = self.related_learning_jobs(db, job)
        if job["status"] in {"failed", "denied", "rejected"}:
            failures = [i for i in related if self._job(db, i)["status"] in {"failed", "denied", "rejected"}]
            if failures:
                self.queue_learning_review(db, job, "repeated_failure", related=failures)
        gaps = list(
            db.execute("SELECT data FROM events WHERE job_id=? AND kind='capability_gap'", (job["id"],))
        )
        if gaps:
            self.queue_learning_review(db, job, "capability_gap", related=related)

    def report_capability_gap(self, job_id, proposal):
        from eas_shared.skills import CapabilityGap

        proposal = CapabilityGap.model_validate(proposal).model_dump()
        with self.db() as db:
            job = self._job(db, job_id)
            lease = json.loads(db.execute("SELECT data FROM lease WHERE id=1").fetchone()[0])
            self._check(job, lease, "assistant", lease["epoch"])
            old = db.execute(
                "SELECT data FROM events WHERE job_id=? AND kind='capability_gap'", (job_id,)
            ).fetchall()
            if canonical(proposal) not in [row[0] for row in old]:
                if len(old) >= 3:
                    raise ValueError("Capability request budget exhausted")
                self._event(db, job_id, "capability_gap", proposal)
            return {
                "recorded": True,
                "request": proposal,
                "authority": "Development suggestion only; no new tools, permissions or execution",
            }

    def learning_episode(self, db, job_id):
        return {
            "job": self._job(db, job_id),
            "events": [
                json.loads(r[0]) | {"kind": r[1]}
                for r in db.execute("SELECT data,kind FROM events WHERE job_id=? ORDER BY seq", (job_id,))
            ],
            "approvals": [
                json.loads(r[0]) for r in db.execute("SELECT data FROM approvals WHERE job_id=?", (job_id,))
            ],
        }

    def learning_claim(self, worker_id, scope):
        with self.db() as db:
            for row in db.execute("SELECT id,data FROM maintenance ORDER BY rowid"):
                item = json.loads(row["data"])
                if (
                    item["organization_id"] != scope["organization_id"]
                    or item["role_id"] not in scope["role_ids"]
                ):
                    continue
                if item["status"] not in {"queued", "running"} or item.get("expires", 0) > time.time():
                    continue
                if item.get("attempts", 0) >= 3:
                    item.update(status="failed", reason="Maintenance retry budget exhausted")
                else:
                    item.update(
                        status="running",
                        worker_id=worker_id,
                        attempts=item.get("attempts", 0) + 1,
                        expires=time.time() + 120,
                        claim_id=uid(),
                    )
                db.execute("UPDATE maintenance SET data=? WHERE id=?", (canonical(item), row["id"]))
                if item["status"] == "running":
                    if item["kind"] in {"learn", "review"}:
                        job = self._job(db, item["job_id"])
                        item["episode"] = self.learning_episode(db, job["id"])
                        item["related"] = [
                            self.learning_episode(db, i)
                            for i in item.get("related_job_ids", [])
                            if self.learning_family(self._job(db, i)) == self.learning_family(job)
                        ]
                    return item
        return None

    def learning_finish(self, item_id, claim_id, result, scope):
        with self.db() as db:
            row = db.execute("SELECT data FROM maintenance WHERE id=?", (item_id,)).fetchone()
            if not row:
                raise ValueError("Unknown maintenance item")
            item = json.loads(row[0])
            if (
                item["organization_id"] != scope["organization_id"]
                or item["role_id"] not in scope["role_ids"]
            ):
                raise PermissionError("Maintenance scope mismatch")
            if item.get("claim_id") != claim_id or item["status"] != "running":
                raise Stale("Maintenance claim expired or replaced")
            item.update(status="completed", result=result, finished_at=time.time())
            db.execute("UPDATE maintenance SET data=? WHERE id=?", (canonical(item), item_id))
            return item

    def skills_publish(self, metadata, scope):
        if len(canonical(metadata)) > 200000:
            raise ValueError("Skill metadata exceeds budget")
        for item in metadata.get("versions", []):
            if (
                item["organization_id"] != scope["organization_id"]
                or item["role_id"] not in scope["role_ids"]
            ):
                raise PermissionError("Skill scope mismatch")
        self.put_value(
            "skills:" + scope["organization_id"] + ":" + ",".join(sorted(scope["role_ids"])), metadata
        )
        return {"published": True}

    def learning_status(self):
        with self.db() as db:
            return {
                "queue": [
                    json.loads(r[0]) for r in db.execute("SELECT data FROM maintenance ORDER BY rowid DESC")
                ],
                "registries": [
                    json.loads(r[0]) for r in db.execute("SELECT data FROM kv WHERE key LIKE 'skills:%'")
                ],
            }

    def skill_command(self, skill_id, version=None):
        status = self.learning_status()
        matches = [
            v
            for registry in status["registries"]
            for v in registry.get("versions", [])
            if v["skill_id"] == skill_id and (version is None or v["version"] == version)
        ]
        if not matches:
            raise ValueError("Unknown installed skill/version")
        selected = matches[0]
        item = dict(
            id=uid(),
            kind="skill_change",
            skill_id=skill_id,
            version=version,
            organization_id=selected["organization_id"],
            role_id=selected["role_id"],
            status="queued",
            created_at=time.time(),
        )
        with self.db() as db:
            db.execute("INSERT INTO maintenance VALUES(?,?)", (item["id"], canonical(item)))
        return item
