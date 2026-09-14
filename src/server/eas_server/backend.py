from pathlib import Path
import asyncio
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
from eas_shared.types import JobInput, Decision, KnowledgeDocument, Stale, Stopped, TERMINAL
from eas_server.security import Security, token_hash
from eas_server.access import install_access, current as current_principal
from eas_server.conversation import Conversation, StaffMessage
from eas_server.web_assets import FrontendFiles, console_page


def create_app(settings=None):
    settings = settings or Settings()
    store = Store(settings.data_dir)
    # Native desktop connections and credentials belong to the Windows worker.
    mock, fixture_static = None, None
    if settings.desktop_adapter == "browser":
        try:
            from ledger_fixture.mock import MockAccounting
            import ledger_fixture
        except ImportError:
            raise ValueError(
                "Install src/test-software/ledger-fixture to enable the browser test application"
            ) from None
        mock = MockAccounting(store)
        fixture_static = Path(ledger_fixture.__file__).parent / "static"

    def browser_fixture():
        if mock is None:
            raise HTTPException(404, "Browser test workspace is disabled; use the Windows application")
        return mock

    app = FastAPI(title="Enterprise worker prototype")
    app.state.store, app.state.settings = store, settings
    security = Security(settings, store)
    app.state.security = security
    install_access(app, security)
    static = Path(__file__).parent / "frontend"
    if mock is not None:
        app.mount("/fixture-static", StaticFiles(directory=fixture_static), name="fixture-static")
    app.mount("/static", FrontendFiles(directory=static), name="static")

    def principal(request: Request):
        p = getattr(request.state, "principal", None) or security.principal(request)
        return "worker" if p.kind == "executor" else p.kind

    def staff():
        p = current_principal.get()
        if p.kind != "human":
            raise HTTPException(403, "Staff access required")
        return p.id

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
        return console_page(static)

    @app.get("/mock")
    def mock_page():
        browser_fixture()
        return FileResponse(fixture_static / "mock.html")

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "model_mode": settings.model_mode,
            "application": "browser_fixture" if mock else "configured_edge_applications",
            "release": store.get_value("release")["version"],
            "desktop_adapter": settings.desktop_adapter,
        }

    @app.get("/api/auth/config")
    def auth_config():
        return {"mode": settings.auth_mode, "login": "email_password"}

    async def login_body(request):
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise HTTPException(415, "JSON sign-in required")
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != settings.public_url.rstrip("/"):
            raise HTTPException(403, "Sign-in origin is not allowed")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16384:
                raise HTTPException(413, "Sign-in request is too large")
        try:
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError()
            return body
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Invalid sign-in request") from None

    @app.post("/api/account/setup")
    async def setup_account(request: Request):
        from starlette.concurrency import run_in_threadpool

        body = await login_body(request)
        return await run_in_threadpool(
            security.accounts.setup,
            body.get("token"),
            body.get("email"),
            body.get("password"),
            request.client.host if request.client else "unknown",
        )

    @app.post("/api/session")
    async def session(request: Request):
        from fastapi.responses import JSONResponse

        from starlette.concurrency import run_in_threadpool

        body = await login_body(request)
        if "token" in body and settings.auth_mode == "development":
            # Explicit API fixture compatibility, never offered in the staff UI.
            p, session_id, csrf = security.session(body["token"])
        else:
            p, session_id, csrf = await run_in_threadpool(
                security.accounts.login,
                body.get("email"),
                body.get("password"),
                request.client.host if request.client else "unknown",
            )
        r = JSONResponse({"ok": True, "principal": {"id": p.id, "name": p.name}, "csrf": csrf})
        r.set_cookie(
            "eas_session",
            session_id,
            httponly=True,
            samesite="strict",
            max_age=3600,
            secure=settings.public_url.startswith("https://"),
        )
        return r

    @app.get("/api/me")
    def me(request: Request):
        p = current_principal.get()
        with store.db() as db:
            row = db.execute(
                "SELECT csrf FROM security_sessions WHERE id=?",
                (token_hash(request.cookies.get("eas_session", "")),),
            ).fetchone()
        return {
            "id": p.id,
            "name": p.name,
            "kind": p.kind,
            "mode": settings.auth_mode,
            "csrf": row[0] if row else None,
        }

    @app.delete("/api/session")
    async def logout(request: Request):
        security.principal(request)
        from fastapi.responses import JSONResponse

        with store.db() as db:
            db.execute(
                "DELETE FROM security_sessions WHERE id=?",
                (token_hash(request.cookies.get("eas_session", "")),),
            )
        r = JSONResponse({"ok": True})
        r.delete_cookie("eas_session")
        return r

    @app.get("/api/roles", dependencies=[Depends(staff)])
    def roles():
        from eas_server.roles import load_roles

        return [
            role.public()
            for role in load_roles().values()
            if any(
                "request" in g.actions
                and g.role_id in {"*", role.id}
                and g.department_id in {"*", role.department_id}
                for g in current_principal.get().grants
            )
        ]

    def chat_scope(body, actor):
        from eas_server.roles import get_role

        values = get_role(body.role_id).normalize(body.model_dump(), allow_unbound=True)
        key = {k: values[k] for k in ("organization_id", "department_id", "role_id", "company_id")}
        security.request(current_principal.get(), values)
        key["staff_id"] = actor
        return "ongoing-" + hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()

    @app.get("/api/chat")
    def current_chat(role_id: str = "invoice_correction", company_id: str = "ACME", actor=Depends(staff)):
        from eas_server.roles import get_role

        body = JobInput(role_id=role_id, department_id=get_role(role_id).department_id, company_id=company_id)
        conversation_id = chat_scope(body, actor)
        requests = [
            j
            for j in security.jobs(current_principal.get())
            if j.get("conversation_id") == conversation_id and j.get("staff_id") == actor
        ]
        # Updating an older result (for example, accepting it from chat history)
        # must not replace the conversation's newest request.
        return {
            "conversation_id": conversation_id,
            "current": max(requests, key=lambda j: (j["created_at"], j["id"]), default=None),
        }

    @app.post("/api/chat")
    def send_chat(body: JobInput, actor=Depends(staff)):
        from eas_server.roles import get_role

        if not body.task or not body.task.strip():
            raise ValueError("A chat message is required")
        values = get_role(body.role_id).normalize(body.model_dump(), allow_unbound=True)
        security.request(current_principal.get(), values)
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
                    for j in security.jobs(current_principal.get())
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
        for job in security.jobs(current_principal.get()):
            groups.setdefault(job.get("conversation_id", job["id"]), []).append(job)
        return [{"id": key, "requests": list(reversed(jobs))} for key, jobs in groups.items()]

    @app.get("/api/learning", dependencies=[Depends(staff)])
    def learning():
        return security.learning(current_principal.get())

    @app.post("/api/skills/{skill_id}/change", dependencies=[Depends(staff)])
    async def skill_change(skill_id: str, request: Request):
        body = await request.json()
        permitted = [
            v
            for r in security.learning(current_principal.get())["registries"]
            for v in r["versions"]
            if v["skill_id"] == skill_id and (body.get("version") is None or v["version"] == body["version"])
        ]
        if not permitted:
            raise HTTPException(404, "Package unavailable")
        for version in permitted:
            security.authorize(current_principal.get(), "manage_skills", version)
        if body.get("worker_id"):
            permitted = [v for v in permitted if v.get("worker_id") == body["worker_id"]]
        if not permitted or len({v.get("worker_id") for v in permitted}) != 1:
            raise HTTPException(409, "Select one authorized worker's package")
        return store.skill_command(skill_id, body.get("version"), selected=permitted[0])

    @app.get("/api/jobs", dependencies=[Depends(staff)])
    def jobs():
        return security.jobs(current_principal.get())

    @app.post("/api/jobs")
    def create_job(body: JobInput, actor=Depends(staff)):
        from eas_server.roles import get_role

        values = get_role(body.role_id).normalize(body.model_dump())
        security.request(current_principal.get(), values)
        if values.get("conversation_id"):
            with store.db() as db:
                existing = db.execute(
                    "SELECT data FROM jobs WHERE json_extract(data,'$.conversation_id')=?",
                    (values["conversation_id"],),
                ).fetchall()
            if any(json.loads(r[0]).get("staff_id") != actor for r in existing):
                raise HTTPException(403, "Conversation unavailable")
        return store.create_job(values, settings.model_mode, settings.job_timeout, staff_id=actor)

    @app.get("/api/jobs/{job_id}", dependencies=[Depends(staff)])
    def get_job(job_id: str):
        lease = store.lease()
        if lease.get("job_id") != job_id:
            lease = {"job_id": None, "owner": None, "epoch": 0, "expires": 0, "inflight": None}
        return {
            "job": store.get_job(job_id),
            "approvals": store.approvals(job_id),
            "events": store.events(job_id),
            "lease": lease,
            "conversation": Conversation(store).read(job_id, require_read=False),
        }

    @app.get("/api/jobs/{job_id}/stream", dependencies=[Depends(staff)])
    async def stream(job_id: str, request: Request, after: int = 0):
        security.job(current_principal.get(), job_id)
        try:
            after = max(0, after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(400, "Invalid event cursor") from None

        async def events():
            cursor = after
            while not await request.is_disconnected():
                security.job(current_principal.get(), job_id)
                rows = store.events(job_id, cursor)
                for row in rows:
                    cursor = row["seq"]
                    yield f"id: {cursor}\ndata: {json.dumps(row)}\n\n"
                if not rows:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.1)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/approvals/{approval_id}", dependencies=[Depends(staff)])
    def decision(approval_id: str, body: Decision):
        return store.decide(approval_id, body.model_dump(), actor=current_principal.get().id)

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
        jobs = security.jobs(current_principal.get())
        results = {}
        for mode in ["simulated", "live"]:
            selected = [j for j in jobs if j["model_mode"] == mode]
            approvals = [a for j in selected for a in store.approvals(j["id"])]
            assessments = [assessment_metrics(store.events(j["id"])) for j in selected]
            results[mode] = {
                "jobs": len(selected),
                "completed_requests": sum(j["status"] == "completed" for j in selected),
                "staff_accepted_completions": sum(bool(j.get("accepted")) for j in selected),
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

    from eas_server.worker_api import install_worker_api

    install_worker_api(app, security)

    @app.get("/api/artifacts/{name}", dependencies=[Depends(staff)])
    def get_artifact(name: str):
        if not re.fullmatch(r"[a-f0-9]{32}\.png", name):
            raise HTTPException(404)
        path = store.root / "artifacts" / name
        if not path.exists():
            raise HTTPException(404)
        return FileResponse(path)

    return app
