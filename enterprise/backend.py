from pathlib import Path
import asyncio
import hmac
import json
import re
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from .config import Settings
from .evaluation import ActionAssessment, assess_action, assessment_metrics
from .store import Store, uid
from .mock import MockAccounting
from .types import JobInput, Decision, KnowledgeDocument, Stale, Stopped
from .remote import WORKER_METHODS
from .conversation import Conversation, StaffMessage


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
    static = Path(__file__).parent / "static"
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
        return FileResponse(static / "mock.html")

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
        from .roles import load_roles

        return [role.public() for role in load_roles().values()]

    @app.get("/api/jobs", dependencies=[Depends(staff)])
    def jobs():
        return store.list_jobs()

    @app.post("/api/jobs", dependencies=[Depends(staff)])
    def create_job(body: JobInput):
        return store.create_job(body.model_dump(), settings.model_mode, settings.job_timeout)

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
                "execution_seconds": sum(j["elapsed_seconds"] for j in selected),
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
        if method in {"search_knowledge", "conversation", "ask_staff"}:
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
