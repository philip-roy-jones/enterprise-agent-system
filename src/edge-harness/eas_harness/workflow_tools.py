"""Trusted compiler for constrained skill workflows with durable child approvals."""

import contextvars
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from eas_harness.errors import Paused
from eas_shared.types import Recovery, Stopped
from eas_harness.workflows.finance.runtime import FinanceOperations


class WorkflowState(TypedDict, total=False):
    index: int
    paused: bool
    needs_assistance: str
    done: bool
    record_unavailable: str


class WorkflowTools(FinanceOperations):
    def __init__(self, settings, store, layer, library, checkpointer):
        self.settings, self.store, self.layer = settings, store, layer
        self.library, self.checkpointer = library, checkpointer

    def operation_once(self, job_id, invocation, name, *, kind="node"):
        job = self.store.get_job(job_id)
        result = self.layer.run(
            job_id,
            invocation,
            name,
            {"company_id": job["company_id"], "invoice_id": job["invoice_id"], "reason": ""},
            lambda args: self.operation(name, {"job_id": job_id}),
            kind=kind,
        )
        job = self.store.get_job(job_id)
        trace = job.get("operation_trace", [])
        if not any(t["invocation"] == invocation for t in trace):
            trace.append({"invocation": invocation, "operation": name, "result": result["value"]})
            self.store.update_job(
                job_id,
                {"operation_trace": trace, "completed": list(dict.fromkeys(job["completed"] + [name]))},
            )
            self.store.event(job_id, "operation_completed", trace[-1])
        return result["value"]

    def run(self, job_id, run_id, skill_id=None, version=None):
        job = self.store.get_job(job_id)
        runs = job.get("workflow_runs", {})
        run = runs.get(run_id)
        if run is None:
            if any(r["state"] not in {"completed", "failed"} for r in runs.values()):
                raise PermissionError("Another workflow owns this request")
            spec = self.library.get(skill_id, version, job, active_only=True)
            if not spec["steps"]:
                raise Recovery(
                    "guidance_only",
                    "This skill contains guidance, not a workflow. Follow it using individually approved tools.",
                )
            run = dict(
                run_id=run_id,
                skill_id=skill_id,
                version=version,
                state="running",
                checkpoint_thread=run_id,
                index=0,
                recoveries=0,
            )
            runs[run_id] = run
            self.store.update_job(job_id, {"workflow_runs": runs})
        spec = self.library.get(run["skill_id"], run["version"], job)
        # Pinned package, including learned labels; never inherit a later active version.
        self.layer.adapter.job = dict(job, amount_labels=spec["amount_labels"])
        steps = spec["steps"]
        builder = StateGraph(WorkflowState)

        def perform(state):
            index = state.get("index", 0)
            if index >= len(steps):
                return {"done": True, "paused": False}
            name = steps[index]
            try:
                # Label lookup is a package-specific parameter, not a permission change.
                self.amount_labels = spec["amount_labels"]
                self.operation_once(job_id, f"{run_id}:{index}:{name}", name)
                return {
                    "index": index + 1,
                    "paused": False,
                    "needs_assistance": "",
                    "done": index + 1 == len(steps),
                }
            except Paused:
                return {"paused": True, "needs_assistance": ""}
            except Recovery as error:
                if error.kind == "record_unavailable" and self.store.get_job(job_id).get("record_lookup"):
                    return {"paused": True, "record_unavailable": error.reason}
                self.store.event(
                    job_id,
                    "recovery_required",
                    {"kind": error.kind, "reason": error.reason, "node": name, "run_id": run_id},
                )
                return {"paused": True, "needs_assistance": error.reason}

        builder.add_node("operation", perform)
        builder.add_edge(START, "operation")
        builder.add_conditional_edges(
            "operation",
            lambda s: "end" if s.get("paused") or s.get("done") else "again",
            {"end": END, "again": "operation"},
        )
        graph = builder.compile(checkpointer=self.checkpointer)
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": 40, "max_concurrency": 4}

        def invoke():
            snapshot = graph.get_state(config)
            return graph.invoke(None if snapshot.next else {"paused": False}, config, durability="sync")

        state = contextvars.Context().run(invoke)
        run.update(
            index=state.get("index", 0),
            state="completed"
            if state.get("done")
            else "record_unavailable"
            if state.get("record_unavailable")
            else "needs_assistance"
            if state.get("needs_assistance")
            else "awaiting_approval",
            reason=state.get("record_unavailable") or state.get("needs_assistance", ""),
        )
        runs = self.store.get_job(job_id).get("workflow_runs", {})
        runs[run_id] = run
        self.store.update_job(job_id, {"workflow_runs": runs, "execution_state": run["state"]})
        if run["state"] == "awaiting_approval":
            raise Paused("Workflow operation awaits approval")
        from eas_harness.judgment import comparison_context

        current = self.store.get_job(job_id)
        return {
            **run,
            "comparison": comparison_context(current, current["expected"])["comparison"]
            if current.get("expected")
            else None,
            "verified_report": current.get("verified_report"),
            "mutation": current["mutation"],
            "verified_draft": next(
                (
                    t["result"]
                    for t in reversed(current.get("operation_trace", []))
                    if t["operation"] == "verify"
                ),
                None,
            ),
            "amount_units": "integer USD cents; divide by 100 when displaying dollars",
        }

    def resume(self, job_id, run_id):
        job = self.store.get_job(job_id)
        run = job.get("workflow_runs", {}).get(run_id)
        if not run:
            raise PermissionError("Workflow does not belong to this request")
        if run["state"] == "needs_assistance":
            if run["recoveries"] >= 4:
                raise Stopped("Workflow assistance budget exceeded")
            run["recoveries"] += 1
            runs = job["workflow_runs"]
            runs[run_id] = run
            self.store.update_job(job_id, {"workflow_runs": runs})
            # Runtime always reobserves at the next operation approval. Save requires
            # reconciliation before another attempt, even after model assistance.
            if job["mutation"] == "attempted_uncertain":
                saved = self.layer.adapter.saved_result(job["expected"])
                if not saved:
                    raise Recovery("ambiguous", "Uncertain Save still lacks authoritative confirmation")
                self.store.update_job(job_id, {"mutation": "confirmed_succeeded"})
        return self.run(job_id, run_id)
