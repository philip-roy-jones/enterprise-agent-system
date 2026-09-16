"""One HTTP resource boundary, including streams and compatibility routes."""

from contextvars import ContextVar
import json
import re
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from eas_server.security import SCOPE
from eas_server.store import desktop_context

current = ContextVar("authenticated_principal")


def install_access(app, security):
    @app.middleware("http")
    async def authorize_request(request, call_next):
        path = request.url.path
        if not path.startswith("/api/") or path in {
            "/api/health",
            "/api/session",
            "/api/auth/config",
            "/api/account/setup",
        }:
            return await call_next(request)
        token = None
        desktop_token = None
        try:
            p = security.principal(request)
            request.state.principal = p
            token = current.set(p)
            if p.kind != "human":
                desktop_token = desktop_context.set(p.worker_id)
            if path.startswith(
                ("/api/worker", "/api/execution", "/api/employee-observation", "/api/mediation/")
            ):
                if p.kind == "human":
                    raise HTTPException(403, "Service identity required")
                if request.headers.get("x-eas-protocol") != "2":
                    raise HTTPException(426, "Worker protocol 2 is required; no legacy fallback")
            elif path.startswith("/api/mock/"):
                if security.settings.auth_mode != "development":
                    raise HTTPException(404, "Resource unavailable")
                scope = dict(zip(SCOPE, ("acme", "finance", "invoice_correction", "ACME")))
                security.authorize(p, "read" if p.kind == "human" else "execute", scope)
                if p.kind == "planner":
                    raise HTTPException(403, "Planner has no application access")
            else:
                if p.kind != "human":
                    raise HTTPException(403, "Human identity required")
                match = re.fullmatch(r"/api/jobs/([^/]+)(?:/([^/]+))?", path)
                if match:
                    job_id, suffix = match.groups()
                    action = (
                        "read"
                        if request.method == "GET"
                        else {
                            "accept": "accept",
                            "assessments": "accept",
                            "messages": "control",
                        }.get(suffix, "control")
                    )
                    job = security.job(p, job_id, action)
                    desktop_token = desktop_context.set(job.get("desktop_id"))
                elif path.startswith("/api/approvals/"):
                    with security.store.db() as db:
                        row = db.execute(
                            "SELECT job_id FROM approvals WHERE id=?", (path.rsplit("/", 1)[1],)
                        ).fetchone()
                    if not row:
                        raise HTTPException(404, "Resource unavailable")
                    security.job(p, row[0], "approve")
                elif path.startswith("/api/artifacts/"):
                    with security.store.db() as db:
                        row = db.execute(
                            "SELECT job_id FROM artifact_owners WHERE id=?", (path.rsplit("/", 1)[1],)
                        ).fetchone()
                    if not row:
                        raise HTTPException(404, "Resource unavailable")
                    security.job(p, row[0])
                elif path.startswith("/api/skills/"):
                    skill_id = path.split("/")[3]
                    permitted = [
                        v
                        for r in security.learning(p)["registries"]
                        for v in r["versions"]
                        if v["skill_id"] == skill_id
                    ]
                    if not permitted:
                        raise HTTPException(404, "Resource unavailable")
                elif path == "/api/knowledge":
                    body = await request.json()
                    security.authorize(p, "knowledge", {k: body.get(k) or "*" for k in SCOPE})
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                security.audit(p, request.method, path)
            return await call_next(request)
        except HTTPException as e:
            return JSONResponse({"detail": e.detail}, status_code=e.status_code)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return JSONResponse({"detail": "Invalid request"}, status_code=400)
        finally:
            if desktop_token is not None:
                desktop_context.reset(desktop_token)
            if token is not None:
                current.reset(token)

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response
