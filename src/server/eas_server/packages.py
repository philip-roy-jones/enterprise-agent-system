"""Immutable package distribution and evidence audience checks; never executes skills."""

import hashlib
import json
from importlib.resources import files
from fastapi import HTTPException
from eas_shared.identity import canonical
from eas_shared.skills import SkillSpec
from eas_server.security import SCOPE


class Packages:
    def __init__(self, security):
        self.security, self.store = security, security.store
        with self.store.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS skill_packages(worker TEXT, id TEXT, version TEXT, data TEXT, PRIMARY KEY(worker,id,version))"
            )

    def chat_evidence(self, principal, evidence_id, spec):
        # Conversation teaching is an attributed text source, not accepted
        # execution. Require the exact completed admission record and preserve
        # its executable bindings; merely chatting cannot attest a new graph.
        with self.store.db() as db:
            row = db.execute("SELECT data FROM maintenance WHERE id=?", ("chat-" + evidence_id,)).fetchone()
        if not row:
            return False
        item = json.loads(row[0])
        result = item.get("result", {})
        candidate = result.get("candidate")
        if (
            item.get("worker_id") != principal.worker_id
            or item["status"] != "completed"
            or result.get("status") != "activated"
            or not result.get("signals")
            or not candidate
        ):
            return False
        candidate = SkillSpec.model_validate(candidate).model_dump()
        return (
            hashlib.sha256(canonical(candidate).encode()).hexdigest() == result.get("version")
            and evidence_id in candidate["evidence_ids"]
            and all(candidate[k] == spec[k] for k in (*SCOPE, "skill_id", "steps", "amount_labels"))
        )

    def publish(self, principal, metadata):
        if len(canonical(metadata)) > 4_000_000:
            raise ValueError("Package publication budget exceeded")
        entries = []
        for item in metadata.get("versions", []):
            spec = SkillSpec.model_validate(item["package"]).model_dump()
            self.security.authorize(principal, "admit", spec)
            if not spec["evidence_ids"]:
                seed = json.loads(files("eas_shared").joinpath("finance_seed.json").read_text())
                legacy_seed = json.loads(files("eas_shared").joinpath("finance_seed_legacy.json").read_text())
                body = {k: v for k, v in spec.items() if k not in {*SCOPE, "application_version"}}
                if body != seed and (body != legacy_seed or item.get("active")):
                    raise PermissionError("Only a registered bundled package may omit teaching evidence")
            if (
                hashlib.sha256(canonical(spec).encode()).hexdigest() != item["version"]
                or spec["skill_id"] != item["skill_id"]
            ):
                raise ValueError("Package hash or identity mismatch")
            for evidence_id in spec["evidence_ids"]:
                job = self.store.get_job(evidence_id)
                self.security.authorize(principal, "admit", job)
                if any(job[k] != spec[k] for k in SCOPE):
                    raise PermissionError("Publication cannot broaden teaching scope")
                if self.chat_evidence(principal, evidence_id, spec):
                    continue
                if job.get("execution_engine") == "shadow-1":
                    if not self.demonstration_evidence(principal, job, spec):
                        raise PermissionError("Demonstration supports admitted guidance only")
                    continue
                if (
                    any(job[k] != spec[k] for k in SCOPE)
                    or not job.get("accepted")
                    or job["status"] != "completed"
                ):
                    raise PermissionError("Publication cannot broaden or invent accepted evidence")
                if not any(
                    a["status"] == "executed" and a["name"] in {"complete", "review_discovery"}
                    for a in self.store.approvals(evidence_id)
                ):
                    raise PermissionError(
                        "Teaching evidence needs an executed verification or outcome review"
                    )
            # Admission identity attests validation. A normal executor or planner
            # cannot use this endpoint, and publication stays on this worker.
            entry = {
                **{
                    k: spec[k]
                    for k in (
                        *SCOPE,
                        "skill_id",
                        "title",
                        "description",
                        "application_version",
                        "evidence_ids",
                        "steps",
                        "instructions",
                    )
                },
                "version": item["version"],
                "active": item.get("active") is True,
                "resources": list(spec["supporting_files"]),
                "created_at": item.get("created_at"),
                "producer": principal.id,
                "worker_id": principal.worker_id,
                "provenance_status": "admission_reported",
                "package": spec,
            }
            entries.append(entry)
        with self.store.db() as db:
            for e in entries:
                db.execute(
                    "INSERT OR REPLACE INTO skill_packages VALUES(?,?,?,?)",
                    (principal.worker_id, e["skill_id"], e["version"], canonical(e)),
                )
        return {**metadata, "versions": [{k: v for k, v in e.items() if k != "package"} for e in entries]}

    def demonstration_evidence(self, principal, job, spec):
        if (
            spec["steps"]
            or job["status"] != "completed"
            or not job.get("accepted")
            or job.get("acceptance_provenance") != "human_demonstration"
        ):
            return False
        with self.store.db() as db:
            row = db.execute("SELECT data FROM maintenance WHERE id=?", ("shadow-" + job["id"],)).fetchone()
        item = json.loads(row[0]) if row else {}
        result = item.get("result", {})
        candidate = result.get("candidate")
        if (
            item.get("worker_id") != principal.worker_id
            or item.get("status") != "completed"
            or result.get("status") != "activated"
            or not candidate
        ):
            return False
        candidate = SkillSpec.model_validate(candidate).model_dump()
        return (
            not candidate["steps"]
            and job["id"] in candidate["evidence_ids"]
            and hashlib.sha256(canonical(candidate).encode()).hexdigest() == result.get("version")
            and all(candidate[k] == spec[k] for k in (*SCOPE, "skill_id", "steps", "amount_labels"))
        )

    def allowed(self, person, item):
        if not person.permits("skills", item):
            return False
        for identity in item.get("evidence_ids", []):
            try:
                self.security.job(person, identity)
            except HTTPException:
                return False
        return True

    def get(self, service, job, skill_id, version):
        with self.store.db() as db:
            row = db.execute(
                "SELECT data FROM skill_packages WHERE worker=? AND id=? AND version=?",
                (service.worker_id, skill_id, version),
            ).fetchone()
        if not row:
            raise HTTPException(404, "Package unavailable")
        item = json.loads(row[0])
        person = self.security.get(job["staff_id"])
        if any(item[k] != job[k] for k in SCOPE) or not self.allowed(person, item):
            raise HTTPException(404, "Package unavailable")
        return item
