"""Protected edge executor. Accepts registered operations, never caller-supplied code."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import httpx
from eas_harness.config import Settings
from eas_harness.remote import RemoteStore
from eas_harness.execution import ExecutionLayer
from eas_harness.skill_library import SkillLibrary
from eas_harness.roles import get_role
from eas_harness.integrations.finance.runtime import FinanceOperations
from eas_harness.contracts import NODE_RESULTS
from eas_harness.errors import Paused
from eas_shared.types import Recovery, Stale, Stopped

NODE_OPERATIONS = set(NODE_RESULTS) | {"report", "judge"}


class Executor(FinanceOperations):
    def __init__(self, settings):
        self.settings = settings
        self.store = RemoteStore(settings.backend_url, settings.worker_token)
        self.identity = self.store.identity()
        if self.identity["kind"] != "executor":
            raise PermissionError("The execution service requires an executor identity")
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        enrollment = settings.data_dir / "worker-enrollment.json"
        registration = {k: self.identity[k] for k in ("worker_id", "environment_revision")}
        if enrollment.exists() and json.loads(enrollment.read_text()) != registration:
            raise PermissionError(
                "Environment registration changed; drain, revoke and provision a clean worker environment"
            )
        if not enrollment.exists():
            enrollment.write_text(json.dumps(registration), encoding="utf-8")
        self.library = SkillLibrary(settings.data_dir)
        from eas_harness.context_broker import ContextVault

        self.context = ContextVault(settings.data_dir)
        self.lock = threading.RLock()
        self.layer = None
        self.active_role = None
        self.catalog_revision = None

    def publish_catalog(self):
        import hashlib
        from eas_shared.identity import canonical

        metadata = self.library.metadata()
        revision = hashlib.sha256(canonical(metadata).encode()).hexdigest()
        if revision != self.catalog_revision:
            admission = RemoteStore(self.settings.backend_url, self.settings.admission_token)
            try:
                admission.skills_publish(metadata)
            finally:
                admission.client.close()
            self.catalog_revision = revision

    def skill(self, job, skill_id, version, *, active_only=False):
        self.store.package_access(job["id"], skill_id, version)
        return self.library.get(skill_id, version, job, active_only=active_only)

    def authorize(self, token, job_id):
        # One online server decision authenticates both service identities and
        # the current assignment. No cached allow decision survives revocation.
        context = self.store.planner_context(job_id, token)
        if context["environment_revision"] != self.identity["environment_revision"]:
            raise PermissionError(
                "Environment policy changed; revalidate deployment before further execution"
            )
        self.store.job_id = job_id
        return self.context.authorized_job(context["job"], context["context_revision"])

    def dispatch(self, token, body):
        if not isinstance(body, dict) or set(body) - {
            "command",
            "job_id",
            "invocation",
            "name",
            "arguments",
            "kind",
            "skill_id",
            "version",
            "active_only",
            "context",
        }:
            raise ValueError("Invalid executor request")
        with self.lock:
            job = self.authorize(token, body["job_id"])
            if body["command"] == "context":
                return self.context.dispatch(job, body["context"])
            role = get_role(job["role_id"])
            self.operation_handler = role.operation_handler
            if self.active_role != role.id:
                if self.layer:
                    self.layer.adapter.close()
                self.layer = ExecutionLayer(
                    self.store, role.adapter_factory(self.settings, self.store), role.operations
                )
                self.active_role = role.id
            self.layer.adapter.job = job
            self.library.seed(job)
            command = body["command"]
            if command in {"seed", "catalog"}:
                self.publish_catalog()
                result = []
                for item in self.library.catalog(job):
                    try:
                        self.store.package_access(job["id"], item["skill_id"], item["version"])
                        result.append(item)
                    except PermissionError:
                        continue
                return result
            if command == "skill":
                if job.get("skill_reads", {}).get(body["skill_id"]) != body["version"]:
                    raise PermissionError("Skill content requires an executed read approval")
                return self.skill(
                    job, body["skill_id"], body["version"], active_only=body.get("active_only", False)
                )
            if command == "saved_result":
                if not any(
                    a["name"] == "resume_skill" and a["status"] == "executed"
                    for a in self.store.approvals(job["id"])
                ):
                    raise PermissionError("Reconciliation requires approved workflow resume")
                result = self.layer.adapter.saved_result(job["expected"])
                if result:
                    self.store.update_job(job["id"], {"mutation": "confirmed_succeeded"})
                return result
            if command != "run" or body.get("kind") not in {"tool", "node"}:
                raise ValueError("Executor command is not registered")
            name, invocation = body["name"], body["invocation"]
            # A graph's learned labels come from its pinned admitted package, never caller input.
            for run in job.get("skill_runs", {}).values():
                if invocation.startswith(run["run_id"] + ":"):
                    spec = self.skill(job, run["skill_id"], run["version"])
                    self.amount_labels = spec["amount_labels"]
                    break
            else:
                self.amount_labels = job["amount_labels"]
            result = self.layer.run(
                job["id"],
                invocation,
                name,
                body["arguments"],
                lambda args: self.effect(job["id"], name, args),
                kind=body["kind"],
            )
            if name in NODE_OPERATIONS or body["kind"] == "node":
                current = self.store.get_job(job["id"])
                trace = current.get("operation_trace", [])
                if not any(t["invocation"] == invocation for t in trace):
                    trace.append({"invocation": invocation, "operation": name, "result": result["value"]})
                    self.store.update_job(
                        job["id"],
                        {
                            "operation_trace": trace,
                            "completed": list(dict.fromkeys(current["completed"] + [name])),
                        },
                    )
                    self.store.event(job["id"], "operation_completed", trace[-1])
            return result

    def effect(self, job_id, name, args):
        job = self.store.get_job(job_id)
        if name in {"capture_screen", "share_screenshot"}:
            from eas_harness.screenshots import screen_tool

            return screen_tool(self.store, self.layer.adapter, job_id, name, args)
        if name == "review_discovery":
            return {"staff_verified_outcome": args["assistant_report"], "acceptance_required": True}
        if name == "select_record":
            return self.store.bind_record(job_id, args[get_role(job["role_id"]).record_field])
        if name == "read_skill":
            import hashlib

            spec = self.skill(job, args["skill_id"], args["version"], active_only=True)
            self.store.update_job(
                job_id, {"skill_reads": {**job.get("skill_reads", {}), args["skill_id"]: args["version"]}}
            )
            return {
                "data": {
                    **spec,
                    "supporting_files": {
                        k: {"sha256": hashlib.sha256(v.encode()).hexdigest()}
                        for k, v in spec.get("supporting_files", {}).items()
                    },
                }
            }
        if name == "read_skill_resource":
            self.skill(job, args["skill_id"], args["version"])
            return {"data": self.library.resource(args["skill_id"], args["version"], args["path"], job)}
        if name == "run_skill":
            if job.get("skill_reads", {}).get(args["skill_id"]) != args["version"]:
                raise PermissionError("Workflow requires approved skill read")
            self.skill(job, args["skill_id"], args["version"], active_only=True)
            return {"data": args}
        if name == "resume_skill":
            if args["run_id"] not in job.get("skill_runs", {}):
                raise PermissionError("Unknown workflow run")
            return {"data": args}
        if name == "ask_staff":
            return self.store.ask_staff(job_id, args["question"])
        if name == "search_knowledge":
            return self.store.search_knowledge(job_id, args["query"])
        if self.operation_handler:
            return self.operation_handler(self.store, self.layer.adapter, job, name, args)
        if name in NODE_OPERATIONS:
            return self.operation(name, {"job_id": job_id, "reason": args.get("reason", "")})
        if name == "set_field":
            expected = job["expected"]
            if not expected or args.get("field") not in {"amount", "note"}:
                raise PermissionError("Only verified draft fields may be edited")
            value = f"{expected['amount'] / 100:.2f}" if args["field"] == "amount" else expected["note"]
            if args["value"] != value:
                raise PermissionError("Field differs from verified draft value")
        return self.layer.adapter.tool_action(name, args)


def serve(settings=None):
    settings = settings or Settings()
    executor = Executor(settings)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if self.path != "/command" or not 0 < size <= 4_000_000:
                    raise ValueError("Invalid request size or endpoint")
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                value = executor.dispatch(token, json.loads(self.rfile.read(size)))
                payload, status = {"result": value}, 200
            except (Paused, Recovery, Stale, Stopped, PermissionError, ValueError, KeyError) as e:
                payload, status = (
                    {"error": type(e).__name__, "message": str(e), "kind": getattr(e, "kind", None)},
                    409,
                )
            except Exception:
                import logging

                logging.exception("Executor request failed")
                payload, status = (
                    {"error": "Stopped", "message": "Execution failed; reconcile before continuing"},
                    500,
                )
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    def maintenance():
        from eas_harness.maintenance import maintain

        store = RemoteStore(settings.backend_url, settings.admission_token)
        while True:
            try:
                with executor.lock:
                    lease = executor.store.lease()
                    if not lease.get("job_id") or executor.store.get_job(lease["job_id"])["status"] in {
                        "completed",
                        "failed",
                        "denied",
                        "rejected",
                        "cancelled",
                    }:
                        maintain(settings, store, executor.identity["worker_id"])
            except Exception:
                import logging

                logging.exception("Scoped maintenance pass failed")
            time.sleep(5)

    if settings.learning_enabled:
        threading.Thread(target=maintenance, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", settings.executor_port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if executor.layer:
            executor.layer.adapter.close()


class RemoteExecutionLayer:
    remote = True

    def __init__(self, settings, store):
        self.store = store
        self.client = httpx.Client(
            base_url=settings.executor_url,
            headers={"Authorization": "Bearer " + settings.worker_token},
            timeout=60,
        )
        self.adapter = SimpleNamespace(job=None, close=self.client.close, saved_result=self.saved_result)
        self.library = RemoteLibrary(self)
        from eas_harness.context_broker import RemoteContext

        self.memory = RemoteContext(self)

    def call(self, command, job_id, **values):
        response = self.client.post("/command", json={"command": command, "job_id": job_id, **values})
        data = response.json()
        if "error" in data:
            if data.get("kind"):
                raise Recovery(data["kind"], data["message"])
            cls = {
                "Paused": Paused,
                "Stale": Stale,
                "Stopped": Stopped,
                "PermissionError": PermissionError,
            }.get(data["error"], ValueError)
            raise cls(data["message"])
        return data["result"]

    def run(self, job_id, invocation, name, arguments, execute, kind="node"):
        # execute is intentionally never serialized or invoked in the planner.
        return self.call("run", job_id, invocation=invocation, name=name, arguments=arguments, kind=kind)

    def saved_result(self, expected):
        return self.call("saved_result", self.store.job_id)


class RemoteLibrary:
    def __init__(self, layer):
        self.layer = layer

    def seed(self, job):
        return self.layer.call("seed", job["id"])

    def catalog(self, job):
        return self.layer.call("catalog", job["id"])

    def get(self, skill_id, version, job, *, active_only=False):
        return self.layer.call(
            "skill", job["id"], skill_id=skill_id, version=version, active_only=active_only
        )


if __name__ == "__main__":
    serve()
