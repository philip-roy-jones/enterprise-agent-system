"""Real Deep Agents harness with a deterministic, explicitly simulated model option."""

import json
from typing import Any
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langchain.agents.middleware import wrap_model_call, wrap_tool_call
from langgraph.types import interrupt, Command
from deepagents import create_deep_agent
from .types import Paused, Stopped


class SimulatedModel(BaseChatModel):
    """Fixture policy for evaluating the harness; NOT an evaluation of model intelligence."""

    @property
    def _llm_type(self):
        return "explicit-simulated-accounting-assistant"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        human = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
        context = json.loads(human.content)
        results = [m for m in messages[messages.index(human) + 1 :] if isinstance(m, ToolMessage)]
        name, args = None, {}
        if not results:
            name = "observe_app"
        else:
            observed = next((json.loads(m.content) for m in results if m.name == "observe_app"), {})
            state = observed.get("state", context["observation"]["state"])
            dialog = state.get("dialog")
            if dialog and not any(m.name == "click" for m in results):
                name, args = (
                    "click",
                    {
                        "target": {
                            "info": "dialog-acknowledge",
                            "unfamiliar": "dialog-review",
                            "unsaved": "dialog-discard",
                        }[dialog]
                    },
                )
            elif (
                not dialog
                and "label" in context["reason"].lower()
                and not any(m.name == "set_field" for m in results)
            ):
                name, args = (
                    "set_field",
                    {"field": "amount", "value": f"{context['expected']['amount'] / 100:.2f}"},
                )
            elif (
                not dialog
                and "label" in context["reason"].lower()
                and sum(m.name == "set_field" for m in results) == 1
            ):
                name, args = "set_field", {"field": "note", "value": context["expected"]["note"]}
        msg = AIMessage(
            content="Supervised resolution proposed."
            if name
            else "Resolution finished; independently verify before resuming.",
            tool_calls=[{"name": name, "args": args, "id": f"sim-{len(results)}"}] if name else [],
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])


def build_assistant(settings, store, layer, checkpointer, job_id, thread_id):
    @tool
    def observe_app() -> dict:
        """Read current accounting application state. Requires individual staff approval."""
        return {}

    @tool
    def click(target: str = "", x: float | None = None, y: float | None = None) -> dict:
        """Click a scoped visible control; coordinates must refer to the current screenshot."""
        return {}

    @tool
    def set_field(field: str, value: str) -> dict:
        """Set amount or note in the assigned invoice's correction draft."""
        return {}

    @tool
    def save_draft() -> dict:
        """Save this job's correction draft only if it matches the verified expected amount."""
        return {}

    scoped_tools = [observe_app, click, set_field, save_draft]
    allowed = {t.name: t for t in scoped_tools}

    @wrap_model_call
    def budget_and_scope(request, handler):
        job = store.get_job(job_id)
        if job["status"] in {"cancelled", "rejected", "denied", "failed"}:
            raise Stopped(job["status"])
        if job["model_calls"] >= settings.max_model_calls:
            raise Stopped("Model call budget exceeded")
        store.update_job(job_id, {"model_calls": job["model_calls"] + 1})
        response = handler(request.override(tools=scoped_tools))
        usage = sum(
            (getattr(m, "usage_metadata", None) or {}).get("total_tokens", 0) for m in response.result
        )
        if usage:
            store.update_job(job_id, {"tokens": store.get_job(job_id)["tokens"] + usage})
        return response

    @wrap_tool_call
    def supervised_tool(request, handler):
        call = request.tool_call
        name, args = call["name"], call["args"]
        if name not in allowed:
            raise PermissionError("Deep Agent built-in, filesystem, shell, and delegation tools are disabled")
        invocation = f"{thread_id}:tool:{call['id']}"
        while True:
            try:

                def execute(corrected: dict[str, Any]):
                    validated = allowed[name].args_schema.model_validate(corrected).model_dump()
                    return layer.adapter.tool_action(name, validated)

                result = layer.run(job_id, invocation, name, args, execute, kind="tool")
                return ToolMessage(content=json.dumps(result["value"]), tool_call_id=call["id"], name=name)
            except Paused as pending:
                interrupt({"approval": str(pending), "tool": name})

    if settings.model_mode == "simulated":
        model = SimulatedModel()
    else:
        if not settings.model_provider or not settings.model_id:
            raise ValueError("Live mode requires a verified EAS_MODEL_PROVIDER and EAS_MODEL_ID")
        from langchain.chat_models import init_chat_model

        model = init_chat_model(
            settings.model_id, model_provider=settings.model_provider, timeout=20, max_retries=0
        )
    return create_deep_agent(
        model=model,
        tools=scoped_tools,
        subagents=[],
        middleware=[budget_and_scope, supervised_tool],
        checkpointer=checkpointer,
        system_prompt="You assist with one synthetic invoice correction. Use only the supplied accounting tools. Every tool, including reads, is supervised by staff. You cannot approve, change modes, delegate, run code, or access files. Work only on the assigned company/invoice. Never retry an uncertain save: observe and reconcile. Stop after resolving the reported condition. Report brief results, not private reasoning.",
    )


def run_assistant(agent, context, thread_id, store, job_id):
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60, "max_concurrency": 1}
    snapshot = agent.get_state(config)
    if snapshot.interrupts:
        decisions = {a["id"]: a["status"] for a in store.approvals(job_id)}
        ready = {
            item.id: True
            for item in snapshot.interrupts
            if decisions.get(item.value.get("approval")) in {"approved", "corrected", "stale", "executing"}
        }
        if not ready:
            return {"__interrupt__": snapshot.interrupts}
        value = Command(resume=ready)
    elif snapshot.next:
        value = None
    elif snapshot.values:
        return snapshot.values
    else:
        value = {"messages": [HumanMessage(content=json.dumps(context))]}
    return agent.invoke(value, config)
