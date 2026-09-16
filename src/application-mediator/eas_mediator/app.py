"""Loopback mediation service. Only this process holds the native controller token."""

import hmac
import os
from pathlib import Path
from threading import RLock

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from eas_shared.identity import fingerprint
from eas_mediator.demobooks import project
from eas_mediator.ledger import InputLedger


class ObservationChanged(Exception):
    pass


class Mediator:
    def __init__(self, native, office, ledger):
        self.native, self.office = native, office
        self.ledger = ledger
        self.lock = RLock()

    def authorize(self, job_id, path, **extra):
        response = self.office.post("/api/mediation/authorize", json=dict(job_id=job_id, path=path, **extra))
        if response.is_error:
            raise PermissionError("Office authorization unavailable or denied")
        return response.json()

    def native_call(self, path, data=None):
        response = self.native.get(path) if data is None else self.native.post(path, json=data)
        if response.is_error:
            if response.status_code == 409 and "revision" in response.json().get("error", "").lower():
                raise ObservationChanged("Observation revision changed; request a fresh view")
            # Native errors can contain control text; never relay them verbatim.
            raise PermissionError("Native application is unavailable or its observation revision changed")
        return response.json()

    def call(self, path, job_id, data):
        with self.lock:
            authority = self.authorize(job_id, "/observe" if path == "/action" else path)
            if path in {"/window", "/activate"}:
                return self.native_call(path, {} if path == "/activate" else None)
            raw = self.native_call("/observe", {"screenshot": False})
            view = project(raw, authority)
            if path == "/action":
                if data.get("revision") != view["revision"]:
                    raise ObservationChanged("Observation revision changed; request a fresh view")
                matches = [
                    n for n in view["elements"] if n["element"] == data.get("element") and n["enabled"]
                ]
                if len(matches) != 1 or not matches[0].get("mediated_target"):
                    raise PermissionError("Only one permitted, described control may receive input")
                node = matches[0]
                if node["mediated_target"] in {"amount", "note", "save"}:
                    names = [n.get("name", "") for n in raw["elements"] if n.get("type") == "Text"]
                    record = "Vendor invoice " + str(authority.get("record_id"))
                    company = "Company: " + str(authority.get("company_id")) + " "
                    if names.count(record) != 1 or not any(n.startswith(company) for n in names):
                        raise PermissionError("Visible company or invoice differs from the assigned record")
                operation = data.get("operation")
                expected = "set_value" if node["type"] == "Edit" else "invoke"
                if operation not in {expected, "click" if expected == "invoke" else expected}:
                    raise PermissionError("Input does not match this control's declared operation")
                native = dict(revision=raw["revision"], element=node["element"], operation=operation)
                if operation == "set_value":
                    value = data.get("value")
                    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
                        raise PermissionError("Only bounded single-line field values are permitted")
                    native.update(value=value, keyboard=bool(data.get("keyboard", False)))
                elif operation == "click":
                    # Caller-supplied coordinates never become native input.
                    native.update(x=node["x"], y=node["y"])
                self.authorize(
                    job_id,
                    path,
                    target=node["mediated_target"],
                    value=native.get("value"),
                    revision=view["revision"],
                    policy_revision=authority["policy_revision"],
                )
                # Native controller rechecks revision + foreground immediately
                # before input; an office round trip cannot make a stale click.
                key = fingerprint([job_id, view["revision"], native])
                return self.ledger.run(key, lambda: self.native_call(path, native))
            # Only filtered content is submitted to central storage. Failure to
            # record it fails this read rather than falling back to raw capture.
            response = self.office.post("/api/mediation/view", json=dict(job_id=job_id, view=view))
            if response.is_error:
                raise PermissionError("The mediated observation could not be recorded")
            if path == "/screenshot":
                return {k: view[k] for k in ("screenshot", "width", "height", "surface", "mediation")}
            if data.get("screenshot") is False:
                view["screenshot"] = None
            return view


def create_app(*, native=None, office=None, token=None, ledger_path=None):
    from urllib.parse import urlsplit

    if (
        office is None
        and os.getenv("EAS_SECURITY_PROFILE") == "managed"
        and urlsplit(os.environ["EAS_OFFICE_URL"]).scheme != "https"
    ):
        raise ValueError("Managed mediators require HTTPS to the office")
    token = token or os.environ.get("EAS_MEDIATOR_TOKEN", "")
    if len(token) < 32:
        raise ValueError("A separate mediator credential of at least 32 characters is required")
    native = (
        native
        if native is not None
        else httpx.Client(
            base_url=os.getenv("EAS_NATIVE_URL", "http://127.0.0.1:8766"),
            timeout=12,
            headers={"Authorization": "Bearer " + os.environ["EAS_NATIVE_TOKEN"]},
        )
    )
    office = (
        office
        if office is not None
        else httpx.Client(
            base_url=os.environ["EAS_OFFICE_URL"],
            timeout=12,
            headers={
                "Authorization": "Bearer " + os.environ["EAS_MEDIATOR_OFFICE_TOKEN"],
                "X-EAS-Protocol": "2",
            },
        )
    )
    app = FastAPI(title="Enterprise Agent System · Application Mediator", docs_url=None, redoc_url=None)
    if ledger_path is None:
        root = Path(os.environ.get("EAS_MEDIATOR_DATA_DIR", "mediator-runtime"))
        root.mkdir(parents=True, exist_ok=True)
        ledger_path = root / "inputs.sqlite"
    mediator = Mediator(native, office, InputLedger(ledger_path))
    app.state.mediator = mediator

    @app.middleware("http")
    async def authenticated(request: Request, call_next):
        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            return JSONResponse({"error": "Mediator credential required"}, status_code=403)
        return await call_next(request)

    @app.api_route("/{path}", methods=["GET", "POST"])
    async def dispatch(path: str, request: Request):
        if path == "health":
            return {"status": "ok", "application": "Application Mediator", "profile": "demobooks-v1"}
        if path not in {"observe", "screenshot", "window", "activate", "action"}:
            return JSONResponse({"error": "Unknown mediation endpoint"}, status_code=404)
        if path in {"action", "activate", "screenshot"} and request.method != "POST":
            return JSONResponse({"error": "POST required"}, status_code=405)
        job_id = request.headers.get("x-eas-job", "")
        if not job_id or len(job_id) > 100:
            return JSONResponse(
                {"error": "An assigned request or demonstration is required"}, status_code=403
            )
        raw = await request.body()
        if len(raw) > 16000:
            return JSONResponse({"error": "Input exceeds mediation limit"}, status_code=413)
        import json
        from starlette.concurrency import run_in_threadpool

        try:
            data = json.loads(raw) if raw else {}
            if not isinstance(data, dict):
                raise ValueError("An object is required")
            return await run_in_threadpool(mediator.call, "/" + path, job_id, data)
        except PermissionError as error:
            return JSONResponse({"error": str(error)}, status_code=403)
        except ObservationChanged as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return JSONResponse(
                {"error": "Mediated application unavailable; no raw fallback"}, status_code=409
            )

    return app


def main():
    from dotenv import load_dotenv
    import uvicorn

    load_dotenv(Path(os.environ.get("EAS_MEDIATOR_ENV_FILE", ".env")))
    # This service is reached by the local executor. Central debugging uses
    # published, scoped views; it never exposes this port over the network.
    uvicorn.run(
        create_app(), host="127.0.0.1", port=int(os.getenv("EAS_MEDIATOR_PORT", "8768")), access_log=False
    )
