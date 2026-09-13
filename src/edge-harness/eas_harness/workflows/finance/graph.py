from eas_harness.workflows.finance.runtime import FinanceOperations
import time
import contextvars
from langgraph.graph import StateGraph, START, END
from eas_harness.state import GraphState
from eas_harness.errors import Paused
from eas_shared.types import Recovery
from eas_harness.assistance import build_assistant, run_assistant
from eas_harness.workflows.finance.procedures import matches_invoice_procedure

NODES = [
    "validate",
    "establish",
    "compare",
    "prepare",
    "save",
    "verify",
    "complete",
    "recover",
    "assist",
    "resume",
    "review_discovery",
]
NEXT = dict(
    validate="establish",
    establish="compare",
    compare="prepare",
    prepare="save",
    save="verify",
    verify="complete",
    complete="end",
    review_discovery="end",
)


class RoleGraph(FinanceOperations):
    def __init__(self, settings, store, layer, checkpointer, assistant_checkpointer):
        self.settings, self.store, self.layer = settings, store, layer
        self.assistant_checkpointer = assistant_checkpointer
        builder = StateGraph(GraphState)
        for name in NODES:
            builder.add_node(name, self.node(name))
            builder.add_conditional_edges(
                name,
                lambda s: "end" if s.get("paused") else s["next_node"],
                {n: n for n in NODES} | {"end": END},
            )
        builder.add_conditional_edges(
            START,
            lambda s: (
                s.get("next_node")
                or (
                    "validate"
                    if matches_invoice_procedure(self.store.get_job(s["job_id"])["task"])
                    else "assist"
                )
            ),
            {n: n for n in NODES} | {"end": END},
        )
        self.graph = builder.compile(checkpointer=checkpointer)

    def node(self, name):
        def execute(state):
            job_id, turn = state["job_id"], state.get("turn", 0)
            invocation = f"{job_id}:{turn}:{name}"
            while True:
                try:
                    result = self.layer.run(
                        job_id,
                        invocation,
                        name,
                        {
                            "company_id": self.store.get_job(job_id)["company_id"],
                            "invoice_id": self.store.get_job(job_id)["invoice_id"],
                            "reason": state.get("reason", ""),
                            **(
                                {"assistant_report": self.store.get_job(job_id).get("assistant_report")}
                                if name == "review_discovery"
                                else {}
                            ),
                        },
                        lambda args: self.operation(name, state),
                    )
                    break
                except Paused:
                    return {"paused": True, "next_node": name}
                except Recovery as recovery:
                    job = self.store.get_job(job_id)
                    if job["recoveries"] >= 6:
                        raise RuntimeError("Recovery budget exceeded")
                    self.store.update_job(job_id, {"recoveries": job["recoveries"] + 1})
                    self.store.event(
                        job_id,
                        "recovery_required",
                        {"kind": recovery.kind, "reason": recovery.reason, "node": name},
                    )
                    route = (
                        "recover"
                        if recovery.kind in {"known", "temporary"}
                        else "resume"
                        if recovery.kind == "ambiguous"
                        else "assist"
                    )
                    return {
                        "turn": turn + 1,
                        "next_node": route,
                        "resume_node": name,
                        "reason": recovery.reason,
                        "recovery_kind": recovery.kind,
                    }
            if name == "assist":
                try:
                    self.assist(state)
                except Paused:
                    return {"paused": True, "next_node": name}
                next_node = (
                    "resume"
                    if matches_invoice_procedure(self.store.get_job(job_id)["task"])
                    else "review_discovery"
                )
            elif name == "resume":
                next_node = result["value"]["next_node"]
                lease = self.store.lease()
                if lease["owner"] != "script":
                    self.store.transfer(job_id, "script", lease["epoch"])
            elif name == "recover":
                next_node = state.get("resume_node", "establish")
            elif name == "review_discovery":
                lease = self.store.lease()
                self.store.transfer(job_id, "script", lease["epoch"])
                next_node = "end"
            else:
                next_node = NEXT[name]
            job = self.store.get_job(job_id)
            completed = list(dict.fromkeys(job["completed"] + ([name] if name in NEXT else [])))
            updates = {
                "completed": completed,
                "checkpoint": {
                    "turn": turn + 1,
                    "next_node": next_node,
                    "graph_version": job["graph_version"],
                },
            }
            if name in {"complete", "review_discovery"}:
                updates.update(elapsed_seconds=round(time.time() - job["started_at"], 2))
            self.store.update_job(job_id, updates)
            if name in {"complete", "review_discovery"}:
                self.store.conclude(job_id)
            self.store.event(
                job_id,
                "progress",
                {"operation": name, "next": next_node, "effective_mode": job["effective_mode"]},
            )
            return {"turn": turn + 1, "next_node": next_node, "result": result["value"]}

        return execute

    def assist(self, state):
        job_id = state["job_id"]
        lease = self.store.lease()
        if lease["owner"] == "staff":
            raise Paused("Staff has desktop control")
        if lease["owner"] != "assistant":
            self.store.transfer(job_id, "assistant", lease["epoch"])
        self.layer.adapter.prepare_observation(job_id, "assistant", self.store.lease()["epoch"])
        thread_id = f"{job_id}:assistance:{state.get('turn', 0)}"
        job = self.store.get_job(job_id)
        unknown = not matches_invoice_procedure(job["task"])
        reason = (
            state.get("reason")
            or "No installed procedure matches the request; investigate within this worker's existing scope."
        )
        if job.get("assistance_thread") != thread_id:
            self.store.update_job(
                job_id, {"fallback_count": job["fallback_count"] + 1, "assistance_thread": thread_id}
            )
            self.store.event(
                job_id,
                "fallback_started",
                {
                    "trigger": "missing_procedure"
                    if unknown
                    else "procedure_failure"
                    if state.get("recovery_kind") == "code_failure"
                    else "unfamiliar_state",
                    "reason": reason,
                },
            )
        agent = build_assistant(
            self.settings, self.store, self.layer, self.assistant_checkpointer, job_id, thread_id
        )
        context = {
            "goal": job["task"],
            "assistance_task": "There is no known procedure for this request. Investigate with approved tools, then report your findings and any unmet parts of the request for staff review. Do not claim work you could not perform. You currently have read and navigation tools; new business mutations require verified values and appropriate installed capabilities."
            if unknown
            else "Resolve only the reported interruption, then finish your response so the scripted workflow can continue. Do not complete the whole invoice workflow."
            if not job["expected"]
            else "Resolve the reported interruption using the verified expected values, then return control for independent verification.",
            "company_id": job["company_id"],
            "invoice_id": job["invoice_id"],
            "expected": job["expected"],
            "draft_fields": {
                "amount": f"{job['expected']['amount'] / 100:.2f}",
                "note": job["expected"]["note"],
            }
            if job["expected"]
            else None,
            "amount_units": "Stored amounts are integer cents; the amount form takes decimal dollars.",
            "verified_progress": job["completed"],
            "mutation": job["mutation"],
            "reason": reason,
            "observation": self.layer.adapter.observe().model_dump(),
            "past_episodes": self.store.relevant_episodes(job_id, reason),
        }
        result = contextvars.Context().run(run_assistant, agent, context, thread_id, self.store, job_id)
        if result.get("__interrupt__"):
            raise Paused("Strict — staff approval required during assistance.")
        if unknown:
            messages = [m for m in result.get("messages", []) if m.type == "ai" and not m.tool_calls]
            if not messages:
                raise Recovery("unfamiliar", "Discovery ended without an outcome report")
            message = messages[-1]
            report = (
                message.content
                if isinstance(message.content, str)
                else "\n".join(
                    block.get("text", "")
                    for block in message.content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            )
            self.store.update_job(job_id, {"assistant_report": report})
            self.store.event(job_id, "discovery_report", {"text": report, "request": job["task"]})
