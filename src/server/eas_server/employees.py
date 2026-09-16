"""Server-owned employee lifecycle and explicitly scoped human demonstrations."""

import json
import time
from fastapi import HTTPException
from eas_shared.identity import canonical, fingerprint, uid
from eas_shared.types import TERMINAL, Stale
from eas_shared.employees import EmployeeState, Demonstration, MentorMessage, ShadowNotes
from eas_server.security import SCOPE


class Workforce:
    def __init__(self, security):
        self.security, self.store = security, security.store
        with self.store.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS employees(id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.sync()

    def sync(self):
        executors = [p for p in self.security.registry().principals if p.kind == "executor"]
        from eas_server.roles import load_roles

        with self.store.db() as db:
            for p in executors:
                profiles = self.profiles(p, load_roles())
                revision = fingerprint(profiles)
                row = db.execute("SELECT data FROM employees WHERE id=?", (p.worker_id,)).fetchone()
                employee = (
                    json.loads(row[0])
                    if row
                    else dict(
                        id=p.worker_id,
                        name=p.name.removesuffix(" executor"),
                        state="shadowing",
                        revision=1,
                        reason="New or migrated employee; supervisor activation required",
                        created_at=time.time(),
                        activated_by=None,
                        readiness=None,
                    )
                )
                if row and employee["scope_revision"] != revision:
                    employee.update(
                        state="paused",
                        revision=employee["revision"] + 1,
                        reason="Registered application scope changed; reprovision and reassess",
                    )
                employee.update(profiles=profiles, scope_revision=revision, enabled=p.enabled)
                db.execute("INSERT OR REPLACE INTO employees VALUES(?,?)", (p.worker_id, canonical(employee)))
            for row in db.execute("SELECT data FROM jobs"):
                job = json.loads(row[0])
                if job["status"] not in TERMINAL and job.get("execution_policy") != 3:
                    job.update(
                        status="cancelled",
                        error="Historical approval policy retired; submit new work after employee activation",
                    )
                    self.store._invalidate(db, job["id"])
                    self.store._put(db, job)

    @staticmethod
    def profiles(principal, roles=None):
        from eas_server.roles import load_roles

        profiles = []
        for grant in principal.grants:
            if "execute" not in grant.actions:
                continue
            for role in (roles or load_roles()).values():
                profile = dict(
                    organization_id=grant.organization_id,
                    department_id=role.department_id,
                    role_id=role.id,
                    company_id="ACME" if grant.company_id == "*" else grant.company_id,
                )
                if grant.matches(profile):
                    profiles.append({**profile, "capabilities": grant.capabilities})
        return profiles

    def get(self, employee_id, db=None):
        if db is None:
            with self.store.db() as connection:
                return self.get(employee_id, connection)
        row = db.execute("SELECT data FROM employees WHERE id=?", (employee_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Employee unavailable")
        return json.loads(row[0])

    def permits(self, person, employee, action="request"):
        checks = [person.permits(action, p) for p in employee["profiles"]]
        return (
            employee["enabled"] and bool(checks) and (all(checks) if action == "supervise" else any(checks))
        )

    def guard(self, employee_id, *, db=None, expected_revision=None):
        employee = self.get(employee_id, db)
        executor = next(
            (
                p
                for p in self.security.registry().principals
                if p.worker_id == employee_id and p.kind == "executor" and p.enabled
            ),
            None,
        )
        if (
            not executor
            or not employee["enabled"]
            or employee["state"] != "active"
            or employee["scope_revision"] != fingerprint(self.profiles(executor))
        ):
            raise HTTPException(403, "Digital employee is not active")
        if expected_revision is not None and employee["revision"] != expected_revision:
            raise Stale("Employee authority changed")
        return employee

    def resolve(self, person, values, *, active=True):
        self.security.request(person, values)
        self.sync()
        with self.store.db() as db:
            employees = [json.loads(r[0]) for r in db.execute("SELECT data FROM employees ORDER BY id")]
        for e in employees:
            if values.get("employee_id") and e["id"] != values["employee_id"]:
                continue
            if not self.permits(person, e) or not any(
                all(p[k] == values[k] for k in SCOPE)
                and set(values.get("permissions", [])) <= set(p["capabilities"])
                for p in e["profiles"]
            ):
                continue
            if active:
                if not values.get("employee_id") and e["state"] != "active":
                    continue
                self.guard(e["id"])
            values["employee_id"] = e["id"]
            return e
        raise HTTPException(403, "No authorized employee for this request")

    def change(self, person, employee_id, change):
        change = EmployeeState.model_validate(change)
        if not change.reason.strip():
            raise ValueError("A supervisor reason is required")
        self.sync()
        with self.store.db() as db:
            e = self.get(employee_id, db)
            if not self.permits(person, e, "supervise"):
                raise HTTPException(403, "Supervisor permission required")
            lease = self.store._lease(db, {"desktop_id": employee_id})
            if change.state != "paused" and lease.get("inflight"):
                raise Stale("Reconcile the in-flight operation before changing authority")
            if change.state != e["state"]:
                # Never resume an old request under a newly granted authority.
                for row in db.execute("SELECT data FROM jobs"):
                    job = json.loads(row[0])
                    if (
                        job.get("desktop_id") == employee_id or job.get("employee_id") == employee_id
                    ) and job["status"] not in TERMINAL:
                        job.update(status="cancelled", error="Employee lifecycle changed")
                        self.store._invalidate(db, job["id"])
                        self.store._put(db, job)
                        self.store._event(db, job["id"], "employee_stopped", {"actor": person.id})
            e.update(
                state=change.state,
                reason=change.reason,
                revision=e["revision"] + 1,
                changed_at=time.time(),
                changed_by=person.id,
            )
            if change.state == "active":
                e.update(
                    activated_by=person.id,
                    readiness={
                        "actor": person.id,
                        "reason": change.reason,
                        "at": time.time(),
                        "kind": "supervisor_assessment",
                    },
                )
            db.execute("UPDATE employees SET data=? WHERE id=?", (canonical(e), employee_id))
            db.execute(
                "INSERT INTO security_audit(at,actor,action,resource) VALUES(?,?,?,?)",
                (time.time(), person.id, "employee:" + change.state, canonical(e)),
            )
            return e

    def start(self, person, employee_id, body, model_mode):
        from eas_server.roles import get_role

        body = Demonstration.model_validate(body)
        role = get_role(body.role_id)
        e = self.get(employee_id)
        profile = next(
            (
                p
                for p in e["profiles"]
                if p["role_id"] == body.role_id
                and p["company_id"] == body.company_id
                and person.permits("supervise", p)
            ),
            None,
        )
        if not profile:
            raise HTTPException(403, "Demonstration scope unavailable")
        values = role.normalize(
            dict(
                role_id=body.role_id,
                department_id=role.department_id,
                organization_id=profile["organization_id"],
                company_id=body.company_id,
                task=body.task,
                employee_id=employee_id,
            ),
            allow_unbound=True,
        )
        self.resolve(person, values, active=False)
        if not self.permits(person, e, "supervise"):
            raise HTTPException(403, "Supervisor permission required to demonstrate")
        channel = None
        if body.channel_id:
            from eas_server.channels import Channels

            channels = Channels(self.security)
            channel = channels.get(body.channel_id)
            if any(
                channel.values().get(k) != values.get(k)
                for k in ("employee_id", "organization_id", "department_id", "role_id", "company_id")
            ):
                raise PermissionError("Channel and demonstration scopes differ")
            linked = next((i for i, p in channel.members.items() if p == person.id), None)
            channels.member(channel, linked)
        # Creation and desktop reservation are one transaction; no execution-queue window.
        with self.store.db() as db:
            e = self.get(employee_id, db)
            if e["state"] != "shadowing":
                raise Stale("Place the employee in shadowing before demonstrating")
            lease = self.store._lease(db, {"desktop_id": employee_id})
            if lease.get("inflight") or (
                lease.get("job_id") and self.store._job(db, lease["job_id"])["status"] not in TERMINAL
            ):
                raise Stale("The desktop is already occupied")
            job = dict(
                values,
                id=uid(),
                staff_id=person.id,
                status="shadowing",
                execution_engine="shadow-1",
                employee_id=employee_id,
                desktop_id=employee_id,
                selected_mode="auto",
                effective_mode="auto",
                execution_policy=3,
                created_at=time.time(),
                started_at=time.time(),
                timeout=1800,
                completed=[],
                expected=None,
                mutation="not_attempted",
                accepted=False,
                model_mode=model_mode,
                model_calls=0,
                tokens=0,
                elapsed_seconds=0,
                recoveries=0,
                fallback_count=0,
                amount_labels=["Correction amount"],
                shadow_frames=0,
                shadow_reviews=0,
                conversation_id="shadow-" + uid(),
                task=body.task,
                app_version="campaign-desk-1"
                if role.id == "campaign_review"
                else "demobooks-windows-1"
                if "Windows" in role.application
                else "mock-1",
                conversation_request=False,
                controller="staff",
            )
            if channel:
                job.update(
                    conversation_id=channel.conversation_id, communication=channel.values()["communication"]
                )
            self.store._put(db, job)
            self.store._event(db, job["id"], "shadow_started", {"mentor": person.id, "task": body.task})
            lease.update(
                job_id=job["id"],
                owner="staff",
                epoch=lease["epoch"] + 1,
                expires=time.time() + 1800,
                inflight=None,
            )
            self.store._set_lease(db, lease)
            return job

    def shadow(self, principal, job_id=None, *, db=None):
        if principal.kind != "executor":
            raise HTTPException(403, "Only the registered observation service may capture demonstrations")
        if db is None:
            with self.store.db() as connection:
                return self.shadow(principal, job_id, db=connection)
        e = self.get(principal.worker_id, db)
        lease = self.store._lease(db, {"desktop_id": e["id"]})
        if not e["enabled"] or e["state"] != "shadowing" or not lease.get("job_id"):
            return None
        job = self.store._job(db, lease["job_id"])
        if job_id and job["id"] != job_id:
            raise HTTPException(404, "Demonstration unavailable")
        if job.get("execution_engine") != "shadow-1" or job["status"] != "shadowing":
            return None
        mentor = self.security.get(job["staff_id"])
        if (
            not mentor.enabled
            or not mentor.permits("supervise", job)
            or not principal.permits("execute", job)
            or e["scope_revision"] != fingerprint(self.profiles(principal))
        ):
            raise HTTPException(403, "Demonstration authority revoked")
        if time.time() > job["started_at"] + job["timeout"]:
            job.update(status="cancelled", error="Demonstration time limit reached")
            self.store._put(db, job)
            return None
        return job


def install_employees(app, security):
    from eas_server.access import current

    workforce, store = security.workforce, security.store

    def human():
        p = security.get(current.get().id)
        if p.kind != "human":
            raise HTTPException(403, "Human identity required")
        return p

    @app.get("/api/employees")
    def employees():
        person = human()
        workforce.sync()
        with store.db() as db:
            rows = [json.loads(r[0]) for r in db.execute("SELECT data FROM employees ORDER BY id")]
        return [
            {
                **e,
                "can_supervise": workforce.permits(person, e, "supervise"),
                "profiles": [p for p in e["profiles"] if person.permits("request", p)],
            }
            for e in rows
            if workforce.permits(person, e)
        ]

    @app.post("/api/employees/{employee_id}/state")
    def state(employee_id: str, body: EmployeeState):
        return workforce.change(human(), employee_id, body)

    @app.post("/api/employees/{employee_id}/demonstrations")
    def start(employee_id: str, body: Demonstration):
        return workforce.start(human(), employee_id, body, security.settings.model_mode)

    @app.get("/api/employees/{employee_id}/demonstration")
    def demonstration(employee_id: str):
        person = human()
        e = workforce.get(employee_id)
        if not workforce.permits(person, e, "supervise"):
            raise HTTPException(403, "Supervisor permission required")
        jobs = [
            j
            for j in security.jobs(person)
            if j.get("employee_id") == employee_id and j.get("execution_engine") == "shadow-1"
        ]
        if not jobs:
            return None
        job = max(jobs, key=lambda j: j["created_at"])
        return {"job": job, "events": store.events(job["id"])}

    @app.post("/api/demonstrations/{job_id}/messages")
    def message(job_id: str, body: MentorMessage):
        person = human()
        job = security.job(person, job_id, "control")
        e = workforce.get(job["employee_id"])
        if not workforce.permits(person, e, "supervise") or person.id != job["staff_id"]:
            raise HTTPException(403, "Only this demonstration's mentor may teach")
        with store.db() as db:
            job = store._job(db, job_id)
            if job["status"] != "shadowing":
                raise Stale("Demonstration ended")
            store._event(db, job_id, "mentor_message", {"text": body.text, "actor": person.id})
        return {"ok": True}

    @app.post("/api/demonstrations/{job_id}/finish")
    def finish(job_id: str, body: MentorMessage):
        person = human()
        job = security.job(person, job_id, "control")
        if person.id != job["staff_id"] or not workforce.permits(
            person, workforce.get(job["employee_id"]), "supervise"
        ):
            raise HTTPException(403, "Only this demonstration's mentor may finish")
        with store.db() as db:
            job = store._job(db, job_id)
            if job["status"] == "completed":
                return job
            if job["status"] != "shadowing" or not job["shadow_frames"]:
                raise Stale("An observed demonstration is required")
            store._event(db, job_id, "mentor_outcome", {"text": body.text, "actor": person.id})
            job.update(
                status="completed",
                accepted=True,
                acceptance_provenance="human_demonstration",
                completion_kind="human_demonstration",
                assistant_report=body.text,
            )
            store._put(db, job)
            item = dict(
                id="shadow-" + job_id,
                kind="shadow_review",
                trigger="demonstration",
                job_id=job_id,
                organization_id=job["organization_id"],
                role_id=job["role_id"],
                target_worker_id=job["employee_id"],
                status="queued",
                created_at=time.time(),
            )
            db.execute("INSERT OR IGNORE INTO maintenance VALUES(?,?)", (item["id"], canonical(item)))
        return job

    @app.post("/api/employee-observation/poll")
    def poll():
        job = workforce.shadow(security.get(current.get().id))
        if job:
            return {"job": job, "events": store.events(job["id"])[-20:]}
        return None

    @app.post("/api/employee-observation/{job_id}")
    def capture(job_id: str, body: dict):
        p = security.get(current.get().id)
        if len(canonical(body)) > 150000 or set(body) - {
            "observation",
            "notes",
            "model_mode",
            "model",
            "usage",
            "review_seq",
            "reserve_review",
            "error",
        }:
            raise ValueError("Invalid observation report")
        with store.db() as db:
            job = workforce.shadow(p, job_id, db=db)
            if not job:
                raise Stale("Demonstration is not observing")
            if "error" in body:
                error = str(body["error"])[:500]
                if job.get("observation_error") != error:
                    store._event(db, job_id, "shadow_unavailable", {"message": error})
                job["observation_error"] = error
            if "observation" in body:
                from eas_shared.types import Observation

                obs = Observation.model_validate(body["observation"]).model_dump()
                if len(canonical(obs)) > 100000 or job["shadow_frames"] >= 180:
                    raise ValueError("Demonstration observation budget exhausted")
                if time.time() - job.get("shadow_last_capture", 0) < 2:
                    raise Stale("Observation interval too short")
                # Artifact ownership is established at upload, before a model sees it.
                if (
                    obs["screenshot"]
                    and not db.execute(
                        "SELECT 1 FROM artifact_owners WHERE id=? AND job_id=?", (obs["screenshot"], job_id)
                    ).fetchone()
                ):
                    raise PermissionError("Screenshot belongs to another request")
                store._event(
                    db,
                    job_id,
                    "shadow_observation",
                    {**obs, "source": "sampled_mentor_desktop", "reported_by": p.id},
                )
                job.update(
                    shadow_frames=job["shadow_frames"] + 1,
                    shadow_last_capture=time.time(),
                    observation_error=None,
                )
            if body.get("reserve_review") is True:
                if job["shadow_reviews"] >= 12 or body.get("model_mode") != job["model_mode"]:
                    raise ValueError("Shadow model budget or provenance mismatch")
                seq = body.get("review_seq")
                if not isinstance(seq, int) or seq <= job.get("shadow_review_seq", 0):
                    raise Stale("Observation already reviewed")
                if not db.execute(
                    "SELECT 1 FROM events WHERE job_id=? AND seq=? AND kind IN ('mentor_message','shadow_observation','shadow_started')",
                    (job_id, seq),
                ).fetchone():
                    raise ValueError("Review source is not part of this demonstration")
                job.update(
                    shadow_reviews=job["shadow_reviews"] + 1, shadow_review_seq=seq, shadow_pending_review=seq
                )
                store._event(
                    db, job_id, "shadow_model_call", {"review_seq": seq, "model_mode": job["model_mode"]}
                )
            if "notes" in body:
                notes = ShadowNotes.model_validate(body["notes"]).model_dump()
                seq = body.get("review_seq")
                if (
                    not isinstance(seq, int)
                    or seq != job.get("shadow_pending_review")
                    or body.get("model_mode") != job["model_mode"]
                ):
                    raise Stale("No outstanding model observation for this result")
                usage = body.get("usage", {})
                if not isinstance(usage, dict) or len(canonical(usage)) > 2000:
                    raise ValueError("Invalid model usage report")
                store._event(
                    db,
                    job_id,
                    "shadow_notes",
                    {
                        **notes,
                        "model_mode": body["model_mode"],
                        "model": str(body.get("model", ""))[:200],
                        "usage": usage,
                        "performed_by": "agent_observer",
                    },
                )
                job["shadow_pending_review"] = None
            store._put(db, job)
        return {"ok": True}
