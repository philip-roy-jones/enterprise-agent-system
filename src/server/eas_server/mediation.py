"""Office policy and central inspection for the separate application mediator."""

import json
import time

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from eas_shared.identity import canonical, fingerprint
from eas_shared.mediation import MediationPolicy, MediationRequest
from eas_server.access import current


class PublishedView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=100)
    view: dict


def install_mediation(app, security):
    store = security.store
    with store.db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS mediation_policies(employee_id TEXT PRIMARY KEY, data TEXT);
            CREATE TABLE IF NOT EXISTS mediated_views(employee_id TEXT PRIMARY KEY, job_id TEXT, data TEXT, updated REAL);
        """)

    def policy(employee_id):
        with store.db() as db:
            row = db.execute(
                "SELECT data FROM mediation_policies WHERE employee_id=?", (employee_id,)
            ).fetchone()
        if not row:
            raise HTTPException(403, "No application mediation policy assigned")
        data = json.loads(row[0])
        if not data["enabled"]:
            raise HTTPException(403, "Application mediation is disabled")
        return {"policy": data, "policy_revision": fingerprint(data)}

    def supervisor(employee_id):
        p = current.get()
        employee = security.workforce.get(employee_id)
        if p.kind != "human" or not security.workforce.permits(p, employee, "supervise"):
            raise HTTPException(403, "Employee supervisor required")
        return p

    @app.put("/api/employees/{employee_id}/mediation-policy")
    def configure(employee_id: str, body: MediationPolicy):
        p = supervisor(employee_id)
        with store.db() as db:
            db.execute(
                "INSERT OR REPLACE INTO mediation_policies VALUES(?,?)",
                (employee_id, canonical(body.model_dump())),
            )
            # Never present an old view as though a new policy filtered it.
            db.execute("DELETE FROM mediated_views WHERE employee_id=?", (employee_id,))
        security.audit(p, "mediation_policy", employee_id)
        return {"policy": body.model_dump(), "policy_revision": fingerprint(body.model_dump())}

    @app.get("/api/employees/{employee_id}/mediation-policy")
    def configuration(employee_id: str):
        supervisor(employee_id)
        return policy(employee_id)

    def context(job_id):
        p = current.get()
        if p.kind != "mediator":
            raise HTTPException(403, "Application mediator identity required")
        job = store.get_job(job_id)
        if job.get("desktop_id") != p.worker_id or not p.permits("mediate", job):
            raise HTTPException(404, "Mediation assignment unavailable")
        if job.get("role_id") != "invoice_correction":
            raise HTTPException(403, "No mediation profile for this application")
        executor = next(
            (
                s
                for s in security.registry().principals
                if s.kind == "executor" and s.worker_id == p.worker_id and s.enabled
            ),
            None,
        )
        if not executor or not executor.permits("execute", job):
            raise HTTPException(403, "Employee environment is unavailable")
        if job.get("execution_engine") == "shadow-1":
            if not security.workforce.shadow(executor, job_id):
                raise HTTPException(403, "Demonstration is unavailable")
            return p, job, None, policy(p.worker_id)
        security.workforce.guard(p.worker_id)
        with store.db() as db:
            assignment = db.execute("SELECT worker_id FROM assignments WHERE job_id=?", (job_id,)).fetchone()
            lease = store._lease(db, job)
        if not assignment or assignment[0] != p.worker_id:
            raise HTTPException(404, "Mediation assignment unavailable")
        store.check(job_id, lease["owner"], lease["epoch"])
        if lease["owner"] == "staff":
            raise HTTPException(403, "Staff owns desktop control")
        return p, job, lease, policy(p.worker_id)

    @app.post("/api/mediation/authorize")
    def authorize(body: MediationRequest):
        p, job, lease, config = context(body.job_id)
        if body.path in {"/activate", "/action"}:
            if lease is None:
                raise HTTPException(403, "Shadowing is observation-only")
            if body.path == "/activate":
                with store.db() as db:
                    started = db.execute(
                        "SELECT 1 FROM events WHERE job_id=? AND kind='window_recovery_started' AND json_extract(data,'$.invocation')=?",
                        (job["id"], lease.get("inflight")),
                    ).fetchone()
                if not started:
                    raise HTTPException(403, "Reserved window recovery required")
            else:
                a = next(
                    (
                        a
                        for a in store.approvals(job["id"])
                        if a["invocation"] == lease.get("inflight") and a["status"] == "executing"
                    ),
                    None,
                )
                if not a or body.policy_revision != config["policy_revision"] or not body.revision:
                    raise HTTPException(403, "Current operation and mediation policy required")
                started = next(
                    (
                        e["at"]
                        for e in reversed(store.events(job["id"]))
                        if e["kind"] == "action_started" and e["data"].get("invocation") == a["invocation"]
                    ),
                    None,
                )
                if started is None or time.time() > started + a["operation_spec"]["timeout_seconds"]:
                    raise HTTPException(403, "Executing operation deadline expired")
                auth = a.get("authorization", {})
                if auth.get("kind") != "employee_policy":
                    raise HTTPException(403, "Employee authority required")
                security.workforce.guard(p.worker_id, expected_revision=auth.get("employee_revision"))
                target = body.target
                arguments = a.get("corrected_arguments", a["arguments"])
                name = a["name"]
                allowed = set()
                if name in {"establish", "ensure_company", "ensure_invoice_open"}:
                    allowed = {"company", "invoices", "view-invoices", "open-" + str(job.get("invoice_id"))}
                elif name == "click":
                    requested = arguments.get("target")
                    if requested:
                        allowed = {requested}
                    else:
                        nodes = [
                            n
                            for n in a["observation"]["targets"]
                            if abs(arguments["x"] - n["x"]) <= n["width"] / 2
                            and abs(arguments["y"] - n["y"]) <= n["height"] / 2
                        ]
                        if len(nodes) == 1:
                            allowed = {nodes[0]["target"]}
                elif name in {"set_field", "prepare"}:
                    allowed = {arguments["field"]} if name == "set_field" else {"amount", "note"}
                    if name == "set_field" and body.value != arguments["value"]:
                        raise HTTPException(403, "Field value differs from authorized operation")
                    if name == "prepare":
                        expected = job.get("expected") or {}
                        values = {
                            "amount": f"{expected.get('amount', 0) / 100:.2f}",
                            "note": expected.get("note"),
                        }
                        if body.value != values.get(target):
                            raise HTTPException(403, "Field value differs from verified correction")
                elif name in {"save", "save_draft"}:
                    allowed = {"save"}
                if (
                    name in {"click", "set_field", "save_draft"}
                    and body.revision != a["observation"]["revision"]
                ):
                    raise HTTPException(403, "Primitive input observation changed")
                if target not in allowed:
                    raise HTTPException(403, "Control is outside the executing operation")
                if (
                    target in {"amount", "note", "save", "dialog-discard"}
                    and not config["policy"]["allow_drafts"]
                ):
                    raise HTTPException(403, "Application policy is read-only")
                if target.startswith("open-") and target != "open-" + str(job.get("invoice_id")):
                    raise HTTPException(403, "Invoice differs from the assigned record")
                store.event(
                    job["id"],
                    "mediated_input_authorized",
                    dict(
                        target=target,
                        revision=body.revision,
                        policy_revision=config["policy_revision"],
                        invocation=a["invocation"],
                        reporter=p.id,
                    ),
                )
        return {**config, "company_id": job.get("company_id"), "record_id": job.get("record_id")}

    @app.post("/api/mediation/view")
    def publish(body: PublishedView):
        p, job, _, config = context(body.job_id)
        view = body.view
        if view.get("mediation", {}).get("policy_revision") != config["policy_revision"]:
            raise HTTPException(409, "Mediation policy changed")
        encoded = canonical(view)
        if len(encoded) > 5_000_000 or view.get("surface") != "mediated_application":
            raise HTTPException(400, "A bounded mediated view is required")
        with store.db() as db:
            db.execute(
                "INSERT OR REPLACE INTO mediated_views VALUES(?,?,?,?)",
                (p.worker_id, job["id"], encoded, time.time()),
            )
        return {"ok": True}

    @app.get("/api/employees/{employee_id}/mediated-view")
    def inspect(employee_id: str):
        person = current.get()
        if person.kind != "human":
            raise HTTPException(403, "Human identity required")
        with store.db() as db:
            row = db.execute(
                "SELECT job_id,data,updated FROM mediated_views WHERE employee_id=?", (employee_id,)
            ).fetchone()
        if not row:
            raise HTTPException(404, "No mediated observation has been received")
        # Inventory access alone is never authority to inspect business data.
        security.job(person, row[0])
        return {"view": json.loads(row[1]), "updated_at": row[2], "job_id": row[0]}
