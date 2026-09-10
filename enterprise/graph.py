import time
import contextvars
from langgraph.graph import StateGraph, START, END
from .types import GraphState, Paused, Recovery
from .assistance import build_assistant, run_assistant

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
]
NEXT = dict(
    validate="establish",
    establish="compare",
    compare="prepare",
    prepare="save",
    save="verify",
    verify="complete",
    complete="end",
)


class RoleGraph:
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
            START, lambda s: s.get("next_node", "validate"), {n: n for n in NODES} | {"end": END}
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
                    }
            if name == "assist":
                try:
                    self.assist(state)
                except Paused:
                    return {"paused": True, "next_node": name}
                next_node = "resume"
            elif name == "resume":
                next_node = result["value"]["next_node"]
                lease = self.store.lease()
                if lease["owner"] != "script":
                    self.store.transfer(job_id, "script", lease["epoch"])
            elif name == "recover":
                next_node = state.get("resume_node", "establish")
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
            if name == "complete":
                updates.update(status="completed", elapsed_seconds=round(time.time() - job["started_at"], 2))
            self.store.update_job(job_id, updates)
            self.store.event(
                job_id,
                "progress",
                {"operation": name, "next": next_node, "effective_mode": job["effective_mode"]},
            )
            return {"turn": turn + 1, "next_node": next_node, "result": result["value"]}

        return execute

    def operation(self, name, state):
        job = self.store.get_job(state["job_id"])
        adapter = self.layer.adapter
        adapter.job = job
        if name == "validate":
            if job["task"] != "invoice_correction":
                raise Recovery(
                    "unsupported", "Unsupported task; staff must submit a supported invoice correction job"
                )
            if not {"read", "navigate", "draft"}.issubset(job["permissions"]):
                raise PermissionError("Invoice correction requires read, navigate and draft permissions")
            obs = adapter.observe()
            if not any(
                i["id"] == job["invoice_id"] and i["company_id"] == job["company_id"]
                for i in obs.state["invoices"]
            ):
                raise PermissionError("Invoice outside assigned company or missing")
            return {"validated": True}
        if name == "establish":
            adapter.ensure_company(job["company_id"])
            return adapter.ensure_invoice_open(job["invoice_id"])
        if name == "compare":
            s = adapter.ensure_editable()
            inv = next(i for i in s["invoices"] if i["id"] == job["invoice_id"])
            expected = {
                "company_id": job["company_id"],
                "invoice_id": job["invoice_id"],
                "amount": inv["po_amount"],
                "po_id": inv["po_id"],
                "difference": inv["amount"] - inv["po_amount"],
                "note": f"Align correction draft with approved purchase order {inv['po_id']}.",
            }
            self.store.update_job(job["id"], {"expected": expected})
            return expected
        if name == "prepare":
            adapter.ensure_editable()
            labels = [t["label"] for t in adapter.observe().targets]
            if not any(label in labels for label in job["amount_labels"]):
                raise Recovery("unfamiliar", "The correction amount field label changed")
            adapter.set_field("amount", f"{job['expected']['amount'] / 100:.2f}")
            adapter.set_field("note", job["expected"]["note"])
            return {"prepared": True}
        if name == "save":
            self.store.update_job(job["id"], {"mutation": "attempted_uncertain"})
            result = adapter.save_and_verify(job["expected"])
            self.store.update_job(job["id"], {"mutation": "confirmed_succeeded"})
            return result
        if name == "verify":
            result = adapter.saved_result(job["expected"])
            if not result:
                raise Recovery("ambiguous", "Saved correction is not visible; reconciliation required")
            self.store.update_job(job["id"], {"mutation": "confirmed_succeeded"})
            return result
        if name == "recover":
            if "info" in state["reason"]:
                adapter.click_target("dialog-acknowledge")
            else:
                adapter.ready()
            return {"recovered": True}
        if name == "assist":
            return {"supervised_assistance_authorized": True}
        if name == "resume":
            obs = adapter.observe()
            if job["expected"]:
                saved = adapter.saved_result(job["expected"])
                if saved:
                    self.store.update_job(job["id"], {"mutation": "confirmed_succeeded"})
                    return {"next_node": "verify", "reconciled": saved}
                if job["mutation"] == "attempted_uncertain":
                    raise Recovery(
                        "unfamiliar", "Uncertain save has no verified result; staff must reconcile"
                    )
                fields = obs.state["fields"]
                if (
                    obs.state["company_id"] == job["company_id"]
                    and obs.state["invoice_id"] == job["invoice_id"]
                    and not obs.state["dialog"]
                    and fields["amount"] == f"{job['expected']['amount'] / 100:.2f}"
                    and fields["note"] == job["expected"]["note"]
                ):
                    return {"next_node": "save", "prepared_by_assistance": True}
            if obs.state["dialog"]:
                raise Recovery("unfamiliar", "Dialog still requires supervised resolution")
            return {"next_node": "establish"}
        if name == "complete":
            if job["mutation"] != "confirmed_succeeded":
                raise Recovery("ambiguous", "Completion requires a verified saved result")
            return {"verified": True, "acceptance_required": True}
        raise ValueError(name)

    def assist(self, state):
        job_id = state["job_id"]
        lease = self.store.lease()
        if lease["owner"] == "staff":
            raise Paused("Staff has desktop control")
        if lease["owner"] != "assistant":
            self.store.transfer(job_id, "assistant", lease["epoch"])
        thread_id = f"{job_id}:assistance:{state.get('turn', 0)}"
        job = self.store.get_job(job_id)
        if job.get("assistance_thread") != thread_id:
            self.store.update_job(
                job_id, {"fallback_count": job["fallback_count"] + 1, "assistance_thread": thread_id}
            )
        agent = build_assistant(
            self.settings, self.store, self.layer, self.assistant_checkpointer, job_id, thread_id
        )
        context = {
            "goal": job["task"],
            "company_id": job["company_id"],
            "invoice_id": job["invoice_id"],
            "expected": job["expected"],
            "verified_progress": job["completed"],
            "reason": state["reason"],
            "observation": self.layer.adapter.observe().model_dump(),
            "past_episodes": self.store.relevant_episodes(job_id, state["reason"]),
        }
        result = contextvars.Context().run(run_assistant, agent, context, thread_id, self.store, job_id)
        if result.get("__interrupt__"):
            raise Paused("Strict — staff approval required during assistance.")
