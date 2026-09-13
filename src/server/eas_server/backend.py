from pathlib import Path
import asyncio
import hmac
import hashlib
import json
import re
import time
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from eas_server.config import Settings
from eas_server.evaluation import ActionAssessment, assess_action, assessment_metrics
from eas_server.store import Store
from eas_shared.identity import uid
from eas_server.fixtures.mock import MockAccounting
from eas_shared.types import JobInput, Decision, KnowledgeDocument, Stale, Stopped, TERMINAL
from eas_shared.protocol import WORKER_METHODS
from eas_server.conversation import Conversation, StaffMessage


def create_app(settings=None):
    settings = settings or Settings()
    store = Store(settings.data_dir)
    # Native desktop connections and credentials belong to the Windows worker.
    mock = MockAccounting(store) if settings.desktop_adapter == "browser" else None

    def browser_fixture():
        if mock is None:
            raise HTTPException(404, "Browser test workspace is disabled; use the Windows application")
        return mock

    app = FastAPI(title="Enterprise worker prototype")
    app.state.store, app.state.settings = store, settings
    static = Path(__file__).parent / "frontend"
    fixture_static = Path(__file__).parent / "fixtures" / "static"
    if mock is not None:
        app.mount("/fixture-static", StaticFiles(directory=fixture_static), name="fixture-static")
    app.mount("/static", StaticFiles(directory=static), name="static")

    def principal(request: Request):
        token = request.headers.get("Authorization", "").removeprefix("Bearer ") or request.cookies.get(
            "eas_session", ""
        )
        for role, expected in [
            ("staff", settings.staff_token),
            ("worker", settings.worker_token),
            ("developer", settings.developer_token),
        ]:
            if token and hmac.compare_digest(token, expected):
                return role
        raise HTTPException(401, "Sign in with your local demo token")

    def staff(role=Depends(principal)):
        if role not in {"staff", "developer"}:
            raise HTTPException(403, "Staff access required")
        return role

    def worker(role=Depends(principal)):
        if role != "worker":
            raise HTTPException(403, "Worker access required")

    @app.post("/api/knowledge", dependencies=[Depends(staff)])
    def add_knowledge(document: KnowledgeDocument):
        return store.add_knowledge(document.model_dump())

    @app.exception_handler(Stale)
    @app.exception_handler(Stopped)
    @app.exception_handler(PermissionError)
    @app.exception_handler(ValueError)
    async def error_handler(request, error):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=403 if isinstance(error, PermissionError) else 409,
            content={"detail": {"type": type(error).__name__, "message": str(error)}},
        )

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/mock")
    def mock_page():
        browser_fixture()
        return FileResponse(fixture_static / "mock.html")

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "model_mode": settings.model_mode,
            "application": "browser_fixture" if mock else "windows_desktop",
            "release": store.get_value("release")["version"],
            "desktop_adapter": settings.desktop_adapter,
        }

    @app.post("/api/session")
    async def session(request: Request):
        body = await request.json()
        token = body.get("token", "")
        if not any(hmac.compare_digest(token, t) for t in [settings.staff_token, settings.developer_token]):
            raise HTTPException(401, "Invalid staff token")
        from fastapi.responses import JSONResponse

        r = JSONResponse({"ok": True})
        r.set_cookie("eas_session", token, httponly=True, samesite="strict", max_age=86400)
        return r

    @app.get("/api/roles", dependencies=[Depends(staff)])
    def roles():
        from eas_server.roles import load_roles

        return [role.public() for role in load_roles().values()]

    def chat_scope(body, actor):
        from eas_server.roles import get_role

        values = get_role(body.role_id).normalize(body.model_dump(), allow_unbound=True)
        key = {k: values[k] for k in ("organization_id", "department_id", "role_id", "company_id")}
        # The prototype has one authenticated staff principal and one developer
        # principal. Token rotation does not change their conversation identity.
        key["staff_id"] = actor
        return "ongoing-" + hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()

    @app.get("/api/chat")
    def current_chat(role_id: str = "invoice_correction", company_id: str = "ACME", actor=Depends(staff)):
        body = JobInput(role_id=role_id, company_id=company_id)
        conversation_id = chat_scope(body, actor)
        requests = [
            j
            for j in store.list_jobs()
            if j.get("conversation_id") == conversation_id and j.get("staff_id") == actor
        ]
        return {"conversation_id": conversation_id, "current": requests[0] if requests else None}

    @app.post("/api/chat")
    def send_chat(body: JobInput, actor=Depends(staff)):
        from eas_server.roles import get_role

        if not body.task or not body.task.strip():
            raise ValueError("A chat message is required")
        values = get_role(body.role_id).normalize(body.model_dump(), allow_unbound=True)
        values["conversation_id"] = chat_scope(body, actor)
        values["request_id"] = values.get("request_id") or uid()
        # A retried guidance delivery stays guidance even after its request ends.
        with store.db() as db:
            delivered = db.execute(
                "SELECT e.data,j.data FROM events e JOIN jobs j ON j.id=e.job_id WHERE e.kind='staff_message' AND json_extract(e.data,'$.message_id')=? AND json_extract(j.data,'$.conversation_id')=?",
                (values["request_id"], values["conversation_id"]),
            ).fetchone()
            if delivered:
                message, previous = json.loads(delivered[0]), json.loads(delivered[1])
                if message["text"] != body.task or (
                    values.get("invoice_id") is not None and previous["invoice_id"] != values["invoice_id"]
                ):
                    raise ValueError("Message identity reused with different inputs")
                return {"job": previous, "kind": "guidance"}
        try:
            result = store.create_job(
                values, settings.model_mode, settings.job_timeout, staff_id=actor, ongoing=True
            )
            return {"job": result, "kind": "request"}
        except Stale:
            current = next(
                (
                    j
                    for j in store.list_jobs()
                    if j.get("conversation_id") == values["conversation_id"] and j["status"] not in TERMINAL
                ),
                None,
            )
            if not current:
                raise
            if values.get("invoice_id") is not None and current["invoice_id"] != values["invoice_id"]:
                raise Stale("Finish or cancel the current request before changing its record")
            conversation = Conversation(store)
            question = next(
                (
                    q
                    for q in conversation.read(current["id"], require_read=False)["questions"]
                    if q["status"] == "pending"
                ),
                None,
            )
            conversation.message(
                current["id"],
                {
                    "text": body.task or "",
                    "message_id": values["request_id"],
                    "reply_to": question["question_id"] if question else None,
                },
            )
            return {"job": store.get_job(current["id"]), "kind": "guidance"}

    @app.get("/api/conversations", dependencies=[Depends(staff)])
    def conversations():
        groups = {}
        for job in store.list_jobs():
            groups.setdefault(job.get("conversation_id", job["id"]), []).append(job)
        return [{"id": key, "requests": list(reversed(jobs))} for key, jobs in groups.items()]

    @app.get("/api/learning", dependencies=[Depends(staff)])
    def learning():
        return store.learning_status()

    @app.post("/api/skills/{skill_id}/change", dependencies=[Depends(staff)])
    async def skill_change(skill_id: str, request: Request):
        body = await request.json()
        return store.skill_command(skill_id, body.get("version"))

    @app.get("/api/jobs", dependencies=[Depends(staff)])
    def jobs():
        return store.list_jobs()

    @app.post("/api/jobs")
    def create_job(body: JobInput, actor=Depends(staff)):
        return store.create_job(body.model_dump(), settings.model_mode, settings.job_timeout, staff_id=actor)

    @app.get("/api/jobs/{job_id}", dependencies=[Depends(staff)])
    def get_job(job_id: str):
        return {
            "job": store.get_job(job_id),
            "approvals": store.approvals(job_id),
            "events": store.events(job_id),
            "lease": store.lease(),
            "conversation": Conversation(store).read(job_id, require_read=False),
        }

    @app.get("/api/jobs/{job_id}/stream", dependencies=[Depends(staff)])
    async def stream(job_id: str, request: Request, after: int = 0):
        async def events():
            cursor = after
            while not await request.is_disconnected():
                rows = store.events(job_id, cursor)
                for row in rows:
                    cursor = row["seq"]
                    yield f"id: {cursor}\ndata: {json.dumps(row)}\n\n"
                if not rows:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/approvals/{approval_id}", dependencies=[Depends(staff)])
    def decision(approval_id: str, body: Decision):
        return store.decide(approval_id, body.model_dump())

    @app.post("/api/jobs/{job_id}/mode", dependencies=[Depends(staff)])
    async def mode(job_id: str, request: Request):
        return store.mode(job_id, (await request.json())["mode"])

    @app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(staff)])
    def cancel(job_id: str):
        return store.stop(job_id)

    @app.post("/api/jobs/{job_id}/takeover", dependencies=[Depends(staff)])
    def takeover(job_id: str):
        current = store.lease()
        store.put_value(f"handoff:{job_id}", current["owner"])
        return store.transfer(job_id, "staff", current["epoch"])

    @app.post("/api/jobs/{job_id}/release", dependencies=[Depends(staff)])
    def release(job_id: str):
        current = store.lease()
        if current["owner"] != "staff":
            raise Stale("Staff does not hold control")
        result = store.transfer(job_id, store.get_value(f"handoff:{job_id}") or "script", current["epoch"])
        store.event(
            job_id, "staff_released", {"message": "Fresh observation and invocation validation required"}
        )
        return result

    @app.post("/api/jobs/{job_id}/accept", dependencies=[Depends(staff)])
    def accept(job_id: str):
        return store.accept(job_id)

    @app.post("/api/jobs/{job_id}/messages", dependencies=[Depends(staff)])
    def message(job_id: str, body: StaffMessage):
        return Conversation(store).message(job_id, body.model_dump())

    @app.post("/api/jobs/{job_id}/assessments", dependencies=[Depends(staff)])
    def action_assessment(job_id: str, body: ActionAssessment):
        return assess_action(store, job_id, body.model_dump())

    @app.get("/api/jobs/{job_id}/episode", dependencies=[Depends(staff)])
    def episode(job_id: str):
        return {
            "job": store.get_job(job_id),
            "events": store.events(job_id),
            "approvals": store.approvals(job_id),
            "app_version": store.get_job(job_id).get("app_version", "mock-1"),
        }

    @app.get("/api/metrics", dependencies=[Depends(staff)])
    def metrics():
        jobs = store.list_jobs()
        results = {}
        for mode in ["simulated", "live"]:
            selected = [j for j in jobs if j["model_mode"] == mode]
            approvals = [a for j in selected for a in store.approvals(j["id"])]
            assessments = [assessment_metrics(store.events(j["id"])) for j in selected]
            results[mode] = {
                "jobs": len(selected),
                "verified_completions": sum(j["status"] == "completed" for j in selected),
                "completion_rate": sum(j["status"] == "completed" for j in selected) / len(selected)
                if selected
                else None,
                "approval_requests": len(approvals),
                "corrections": sum(
                    a.get("decision", {}).get("decision") == "correct" for a in approvals if a.get("decision")
                ),
                "fallback_jobs": sum(j["fallback_count"] > 0 for j in selected),
                "model_calls": sum(j["model_calls"] for j in selected),
                "tokens": sum(j["tokens"] for j in selected),
                "execution_seconds": sum(
                    j["elapsed_seconds"]
                    if j["status"] in TERMINAL
                    else max(0, time.time() - j["started_at"])
                    if j.get("started_at")
                    else 0
                    for j in selected
                ),
                "jobs_missing_elapsed_time": sum(
                    bool(j.get("started_at"))
                    and j["status"] in TERMINAL
                    and not j.get("ended_at")
                    and not j["elapsed_seconds"]
                    for j in selected
                ),
                **{
                    key: sum(a[key] for a in assessments)
                    for key in ("incorrect_actions_reported", "assessed_actions", "unassessed_actions")
                },
            }
        return results

    @app.get("/api/mock/state", dependencies=[Depends(principal)])
    def mock_state():
        return browser_fixture().state()

    @app.post("/api/mock/action")
    async def mock_action(request: Request, role=Depends(principal)):
        body = await request.json()
        return browser_fixture().action(body["name"], body.get("args", {}), role)

    @app.post("/api/mock/scenario", dependencies=[Depends(staff)])
    async def scenario(request: Request):
        return browser_fixture().scenario(await request.json())

    @app.post("/api/worker/{method}", dependencies=[Depends(worker)])
    async def worker_rpc(method: str, request: Request):
        if method not in WORKER_METHODS:
            raise HTTPException(403, "Worker method not permitted")
        body = await request.json()
        if method in {"learning_claim", "learning_finish", "skills_publish"}:
            body.setdefault("kwargs", {})["scope"] = {
                "organization_id": settings.worker_organization_id,
                "role_ids": list(settings.worker_role_ids),
            }
        if method == "claim":
            args = body.get("args", [])
            if len(args) != 1 or body.get("kwargs"):
                raise ValueError(
                    "Claim accepts one worker identifier; authorization is configured on the server"
                )
            return store.claim(
                args[0],
                {"organization_id": settings.worker_organization_id, "role_ids": settings.worker_role_ids},
            )
        if method in {
            "search_knowledge",
            "conversation",
            "ask_staff",
            "bind_record",
            "report_capability_gap",
        }:
            args, kwargs = body.get("args", []), body.get("kwargs", {})
            if len(args) != (1 if method == "conversation" else 2) or kwargs:
                raise ValueError("Expected job identifier and only the declared tool arguments")
            job = store.get_job(args[0])
            if (
                job["organization_id"] != settings.worker_organization_id
                or job["role_id"] not in settings.worker_role_ids
            ):
                raise PermissionError("Job is outside the configured worker scope")
        return getattr(store, method)(*body.get("args", []), **body.get("kwargs", {}))

    @app.post("/api/worker-artifacts", dependencies=[Depends(worker)])
    async def artifact(request: Request):
        data = await request.body()
        if len(data) > 5_000_000 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("A PNG below 5 MB is required")
        name = uid() + ".png"
        (store.root / "artifacts" / name).write_bytes(data)
        return {"id": name}

    @app.get("/api/artifacts/{name}", dependencies=[Depends(staff)])
    def get_artifact(name: str):
        if not re.fullmatch(r"[a-f0-9]{32}\.png", name):
            raise HTTPException(404)
        path = store.root / "artifacts" / name
        if not path.exists():
            raise HTTPException(404)
        return FileResponse(path)

    return app
