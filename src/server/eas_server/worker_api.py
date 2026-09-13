"""Typed, assignment-bound service protocol. No remote reflection into Store."""

import json
import time
from importlib.resources import files
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from jsonschema import Draft202012Validator
from eas_server.access import current
from eas_shared.identity import uid, fingerprint

CONTRACTS = json.loads(files("eas_shared").joinpath("finance_operations.json").read_text())
ROLE_CONTRACTS = {
    "invoice_correction": CONTRACTS,
    "campaign_review": json.loads(files("eas_shared").joinpath("marketing_operations.json").read_text()),
}


def register_contracts(role_id, metadata):
    """Trusted server role modules register data contracts, never executable edge code."""
    if role_id in ROLE_CONTRACTS:
        raise ValueError("Operation contracts already registered for this role")
    for item in metadata.values():
        Draft202012Validator.check_schema(item["input_schema"])
        Draft202012Validator.check_schema(item["output_schema"])
        if not all(item.get(k) for k in ("permission", "description", "expected")):
            raise ValueError("Incomplete operation metadata")
    ROLE_CONTRACTS[role_id] = json.loads(json.dumps(metadata))


def contracts_for(job):
    return ROLE_CONTRACTS.get(job["role_id"], {})


# Fixed arity is checked before dispatch; the function table is owned by the runtime.
ARITY = {
    "planner_context": (2, 2),
    "finish_window_recovery": (3, 3),
    "get_job": (1, 1),
    "update_job": (2, 2),
    "event": (3, 3),
    "lease": (0, 0),
    "claim": (1, 1),
    "check": (3, 3),
    "transfer": (2, 3),
    "boundary": (1, 1),
    "proposal": (3, 3),
    "approvals": (1, 1),
    "stale_approval": (1, 1),
    "begin_action": (5, 6),
    "begin_window_recovery": (4, 4),
    "finish_action": (3, 5),
    "result": (1, 1),
    "relevant_episodes": (1, 1),
    "search_knowledge": (2, 2),
    "conversation": (1, 1),
    "ask_staff": (2, 2),
    "bind_record": (2, 2),
    "report_capability_gap": (2, 2),
    "learning_claim": (1, 1),
    "learning_finish": (3, 3),
    "skills_publish": (1, 1),
    "conclude": (1, 1),
    "package_access": (3, 3),
}
PLANNER = {
    "get_job",
    "update_job",
    "event",
    "lease",
    "claim",
    "check",
    "transfer",
    "boundary",
    "approvals",
    "result",
    "conversation",
    "report_capability_gap",
    "conclude",
}
ADMISSION = {"learning_claim", "learning_finish", "skills_publish", "get_job", "package_access"}
PLANNER_UPDATES = {
    "execution_state",
    "skill_runs",
    "error",
    "model_calls",
    "tokens",
    "checkpoint",
    "model_binding",
    "assistance_thread",
    "model_guidance_revision",
    "assistant_report",
    "status",
    "elapsed_seconds",
}
EXECUTOR_UPDATES = PLANNER_UPDATES | {
    "completed",
    "expected",
    "mutation",
    "recoveries",
    "fallback_count",
    "operation_failures",
    "verified_report",
    "skill_reads",
    "operation_trace",
    "record_lookup",
}
RESERVED_EVENTS = {
    "job_created",
    "record_selected",
    "approval_policy_migrated",
    "worker_restarted",
    "knowledge_retrieved",
    "control_transferred",
    "mode_requested",
    "cancelled",
    "rejected",
    "denied",
    "stale_proposal",
    "window_recovery_started",
    "window_recovery_finished",
    "capability_gap",
    "assistant_question",
    "acceptance_revoked",
    "staff_decision",
    "action_started",
    "action_result",
    "approval_requested",
    "action_assessment",
    "staff_message",
    "staff_answered",
    "chat_feedback",
    "staff_answer",
    "record_bound",
    "accepted",
}


class RPC(BaseModel):
    model_config = ConfigDict(extra="forbid")
    args: list = Field(default_factory=list, max_length=6)
    kwargs: dict = Field(default_factory=dict)
    grant: str | None = None


def install_worker_api(app, security):
    store = security.store
    from eas_server.execution_grants import ExecutionGrants

    grants = ExecutionGrants(security)
    app.state.execution_grants = grants
    with store.db() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS assignments(job_id TEXT PRIMARY KEY, worker_id TEXT, executor_id TEXT)"
        )
    dispatch = {
        name: getattr(store, name) for name in ARITY if name not in {"package_access", "planner_context"}
    }

    @app.get("/api/worker/identity")
    def identity():
        p = security.get(current.get().id)
        if p.kind == "human":
            raise HTTPException(403, "Service identity required")
        return {
            "id": p.id,
            "kind": p.kind,
            "worker_id": p.worker_id,
            "protocol": 2,
            "environment_revision": environment_revision(p),
        }

    def environment_revision(p):
        return fingerprint(
            [
                {
                    k: getattr(g, k)
                    for k in ("organization_id", "department_id", "role_id", "company_id", "capabilities")
                }
                for g in p.grants
            ]
        )

    def scope(p, action):
        grants = [g for g in p.grants if action in g.actions]
        if not grants or len({g.organization_id for g in grants}) != 1:
            raise HTTPException(403, "A service must have one explicit organization")
        from eas_server.roles import load_roles

        roles = {r for g in grants for r in (load_roles() if g.role_id == "*" else [g.role_id])}
        return {"organization_id": grants[0].organization_id, "role_ids": sorted(roles)}

    def assigned(p, job_id, *, receipt=False):
        job = store.get_job(job_id)
        action = "admit" if p.kind == "admission" else "execute"
        if not p.permits(action, job) or (
            p.kind != "admission"
            and not any(
                g.matches(job) and action in g.actions and set(job["permissions"]) <= set(g.capabilities)
                for g in p.grants
            )
        ):
            raise HTTPException(404, "Assignment unavailable")
        if p.kind == "admission":
            with store.db() as db:
                items = [json.loads(r[0]) for r in db.execute("SELECT data FROM maintenance")]
            if not any(
                i.get("worker_id") == p.worker_id
                and i.get("status") == "running"
                and i.get("expires", 0) > time.time()
                and job_id in [i.get("job_id"), *i.get("related_job_ids", [])]
                for i in items
            ):
                raise HTTPException(404, "Maintenance assignment unavailable")
        else:
            with store.db() as db:
                row = db.execute("SELECT worker_id FROM assignments WHERE job_id=?", (job_id,)).fetchone()
            if not row or row[0] != p.worker_id:
                raise HTTPException(404, "Assignment unavailable")
            lease = store.lease()
            if lease.get("job_id") != job_id:
                raise HTTPException(404, "Assignment is no longer current")
            if not receipt:
                requester = security.get(job["staff_id"])
                security.request(requester, job)
                for a in store.approvals(job_id):
                    if a["status"] == "executing":
                        security.authorize(security.get(a["decision"]["actor"]), "approve", job)
        return job

    def validate_proposal(job, proposal):
        op = contracts_for(job).get(proposal.get("name"))
        if not op or op["permission"] not in job["permissions"]:
            raise HTTPException(403, "Operation not authorized")
        if not Draft202012Validator(op["input_schema"]).is_valid(proposal["arguments"]):
            raise HTTPException(400, "Invalid operation arguments")
        targets = {
            **job.get("inputs", {}),
            **{
                k: job.get(k)
                for k in ("company_id", "invoice_id", "organization_id", "department_id", "role_id")
            },
        }
        for k, value in targets.items():
            if k in proposal["arguments"] and value is not None and proposal["arguments"][k] != value:
                raise HTTPException(403, "Operation target is outside the request")
        if proposal.get("operation_spec") != op:
            raise HTTPException(403, "Operation contract differs from installed metadata")
        proposal.update(description=op["description"], expected=op["expected"], operation_spec=op)

    @app.post("/api/worker/{method}")
    def worker_rpc(method: str, body: RPC):
        p = security.get(current.get().id)
        if p.kind == "human" or method not in ARITY:
            raise HTTPException(403, "Service command not permitted")
        if p.kind == "planner" and method not in PLANNER:
            raise HTTPException(403, "Planner command not permitted")
        if p.kind == "admission" and method not in ADMISSION:
            raise HTTPException(403, "Admission command not permitted")
        if p.kind != "admission" and method in ADMISSION - {"get_job", "package_access"}:
            raise HTTPException(403, "Separate admission identity required")
        args, kwargs = body.args, body.kwargs
        low, high = ARITY[method]
        allowed_kwargs = {"cache"} if method == "finish_action" else set()
        if not low <= len(args) <= high or set(kwargs) - allowed_kwargs:
            raise HTTPException(400, "Command arguments do not match the protocol")
        if (
            args
            and method != "skills_publish"
            and (not isinstance(args[0], str) or not 1 <= len(args[0]) <= 300)
        ):
            raise HTTPException(400, "A bounded resource identifier is required")
        objects = {
            "update_job": [1],
            "event": [2],
            "proposal": [2],
            "begin_action": [4],
            "finish_action": [2],
            "report_capability_gap": [1],
            "learning_finish": [2],
            "skills_publish": [0],
        }
        if (
            any(not isinstance(args[i], dict) for i in objects.get(method, []))
            or len(json.dumps(args)) > 4_000_000
        ):
            raise HTTPException(400, "Invalid command payload")
        if method in {"check", "begin_action", "begin_window_recovery"} and (
            args[1] not in {"script", "assistant", "staff"} or type(args[2]) is not int
        ):
            raise HTTPException(400, "Invalid lease binding")
        if method == "transfer" and (
            args[1] not in {"script", "assistant"} or (len(args) == 3 and type(args[2]) is not int)
        ):
            raise HTTPException(403, "Invalid service ownership transition")
        if method == "claim":
            # The caller's process nonce never determines its authenticated machine identity.
            authorized_scope = scope(p, "execute")

            def eligible(j):
                try:
                    security.request(security.get(j["staff_id"]), j)
                except HTTPException:
                    return False
                return p.permits("execute", j) and any(
                    g.matches(j) and "execute" in g.actions and set(j["permissions"]) <= set(g.capabilities)
                    for g in p.grants
                )

            authorized_scope["predicate"] = eligible
            job = store.claim(p.worker_id + ":" + str(args[0])[:80], authorized_scope)
            if job:
                security.request(security.get(job["staff_id"]), job)
                with store.db() as db:
                    db.execute(
                        "INSERT OR REPLACE INTO assignments VALUES(?,?,?)", (job["id"], p.worker_id, p.id)
                    )
            return job
        if method == "lease":
            lease = store.lease()
            if lease.get("job_id"):
                assigned(p, lease["job_id"])
            return lease
        if method == "learning_claim":
            return store.learning_claim(
                p.worker_id,
                scope(p, "admit")
                | {
                    "predicate": lambda j: (
                        p.permits("admit", j)
                        and (j.get("desktop_id") == p.worker_id or j.get("target_worker_id") == p.worker_id)
                    )
                },
            )
        if method == "learning_finish":
            with store.db() as db:
                row = db.execute("SELECT data FROM maintenance WHERE id=?", (args[0],)).fetchone()
            item = json.loads(row[0]) if row else {}
            if item.get("worker_id") != p.worker_id or item.get("expires", 0) <= time.time():
                raise HTTPException(403, "Maintenance claim unavailable")
            if item.get("job_id"):
                security.authorize(p, "admit", store.get_job(item["job_id"]))
            return store.learning_finish(*args, scope=scope(p, "admit"))
        if method == "skills_publish":
            metadata = security.packages.publish(p, args[0])
            return store.skills_publish(metadata, scope(p, "admit"), worker_id=p.worker_id)
        if method in {"result", "stale_approval"}:
            table, col = ("invocations", "id") if method == "result" else ("approvals", "id")
            with store.db() as db:
                row = db.execute(f"SELECT job_id FROM {table} WHERE {col}=?", (args[0],)).fetchone()
            if not row:
                return None if method == "result" else (_ for _ in ()).throw(HTTPException(404))
            assigned(p, row[0])
        else:
            job = assigned(p, args[0], receipt=method in {"finish_action", "finish_window_recovery"})
            if method == "planner_context":
                planner = security.authenticate_token(args[1])
                if (
                    planner.kind != "planner"
                    or planner.worker_id != p.worker_id
                    or not planner.permits("execute", job)
                ):
                    raise HTTPException(403, "Planner is outside this execution environment")
                if not any(
                    g.matches(job)
                    and "execute" in g.actions
                    and set(job["permissions"]) <= set(g.capabilities)
                    for g in planner.grants
                ):
                    raise HTTPException(403, "Planner capability is not permitted")
                lease = store.lease()
                return {
                    "job": store.check(job["id"], lease["owner"], lease["epoch"]),
                    "lease": lease,
                    "environment_revision": environment_revision(p),
                    "context_revision": security.revision(),
                }
            invocation_index = {
                "proposal": 1,
                "begin_action": 3,
                "begin_window_recovery": 3,
                "finish_action": 1,
                "finish_window_recovery": 1,
            }.get(method)
            if invocation_index is not None and (
                not isinstance(args[invocation_index], str)
                or not args[invocation_index].startswith(job["id"] + ":")
            ):
                raise HTTPException(403, "Invocation must belong to its assigned request")
            if method == "package_access":
                return security.packages.get(p, job, args[1], args[2])
            if method == "proposal":
                validate_proposal(job, args[2])
            if method == "event":
                if isinstance(args[1], str) and args[1] in {
                    "assistant_message_delta",
                    "assistant_stream_end",
                }:
                    data = args[2]
                    expected_keys = (
                        {"message_id", "text"} if args[1] == "assistant_message_delta" else {"message_id"}
                    )
                    if (
                        set(data) != expected_keys
                        or not isinstance(data.get("message_id"), str)
                        or not 1 <= len(data["message_id"]) <= 300
                        or (
                            "text" in data
                            and (not isinstance(data["text"], str) or not 1 <= len(data["text"]) <= 16000)
                        )
                    ):
                        raise HTTPException(400, "Invalid public response chunk")
                if (
                    not isinstance(args[1], str)
                    or args[1].startswith("staff_")
                    or args[1] in RESERVED_EVENTS
                    or not isinstance(args[2], dict)
                ):
                    raise HTTPException(403, "Runtime-owned event")
                args[2] = {**args[2], "reported_by": p.id}
            if method == "update_job":
                if not isinstance(args[1], dict) or set(args[1]) - (
                    PLANNER_UPDATES if p.kind == "planner" else EXECUTOR_UPDATES
                ):
                    raise HTTPException(403, "Service cannot update execution authority or results")
                if args[1].get("status") and args[1]["status"] not in {"failed", "denied"}:
                    raise HTTPException(403, "Completion requires a validated transition")
                if "skill_runs" in args[1]:
                    old, new = job.get("skill_runs", {}), args[1]["skill_runs"]
                    if not isinstance(new, dict) or set(old) - set(new):
                        raise HTTPException(403, "Workflow history cannot be removed")
                    approved = [
                        a
                        for a in store.approvals(job["id"])
                        if a["name"] == "run_skill" and a["status"] == "executed"
                    ]
                    for run_id, run in new.items():
                        if run_id != run.get("run_id") or run_id != run.get("checkpoint_thread"):
                            raise HTTPException(403, "Workflow identity differs")
                        if run_id in old:
                            if any(
                                run[k] != old[run_id][k]
                                for k in ("run_id", "skill_id", "version", "checkpoint_thread")
                            ):
                                raise HTTPException(403, "Pinned workflow cannot change")
                        elif not any(
                            run_id == a["invocation"] + ":skill"
                            and {"skill_id": run["skill_id"], "version": run["version"]}
                            == a.get("corrected_arguments", a["arguments"])
                            for a in approved
                        ):
                            raise HTTPException(403, "Workflow requires its executed parent approval")
            if method == "transfer" and args[1] == "staff":
                raise HTTPException(403, "Only staff may take desktop control")
            if method == "finish_action":
                approval_id = args[3] if len(args) > 3 else None
                approval = next((a for a in store.approvals(job["id"]) if a["id"] == approval_id), None)
                if not approval or approval["status"] != "executing" or approval["invocation"] != args[1]:
                    raise HTTPException(403, "An executing approved invocation is required")
                if "value" in args[2]:
                    if not Draft202012Validator(
                        contracts_for(job)[approval["name"]]["output_schema"]
                    ).is_valid(args[2]["value"]):
                        raise HTTPException(400, "Invalid operation result")
                args[2]["provenance"] = {
                    "producer": p.id,
                    "status": "structurally_validated_executor_report",
                    "independently_verified": False,
                }
        if method == "begin_action":
            if len(args) != 6:
                raise HTTPException(400, "Exact action and approval required")
            return store.begin_action(*args, authorization=grants.consumer(p, body.grant, args))
        return dispatch[method](*args, **kwargs)

    @app.post("/api/execution/grant")
    def execution_grant(body: RPC):
        p = current.get()
        if p.kind != "executor" or len(body.args) != 6 or body.kwargs or body.grant:
            raise HTTPException(403, "Executor and exact operation required")
        assigned(p, body.args[0])
        return grants.issue(p, body.args)

    @app.post("/api/worker-artifacts")
    async def artifact(request: Request):
        p = current.get()
        if p.kind != "executor":
            raise HTTPException(403, "Executor identity required")
        job_id = request.headers.get("x-eas-job")
        assigned(p, job_id)
        data = await request.body()
        if len(data) > 5_000_000 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("A PNG below 5 MB is required")
        name = uid() + ".png"
        (store.root / "artifacts" / name).write_bytes(data)
        with store.db() as db:
            db.execute("INSERT INTO artifact_owners VALUES(?,?,?)", (name, job_id, p.id))
        return {"id": name}

    @app.get("/api/worker-artifacts/{job_id}/{name}")
    def screenshot_image(job_id: str, name: str, metadata: bool = False):
        from fastapi.responses import FileResponse
        from eas_shared.screenshots import captured_screen

        p = current.get()
        if p.kind not in {"planner", "executor"}:
            raise HTTPException(403, "Assigned execution identity required")
        assigned(p, job_id)
        capture = captured_screen(store.events(job_id), name)
        with store.db() as db:
            if not db.execute(
                "SELECT 1 FROM artifact_owners WHERE id=? AND job_id=?", (name, job_id)
            ).fetchone():
                raise HTTPException(404, "Screenshot unavailable")
        return capture if metadata else FileResponse(store.root / "artifacts" / name, media_type="image/png")
