from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from enterprise.assistance import build_assistant, run_assistant
from enterprise.config import Settings
from enterprise.execution import ExecutionLayer
from enterprise.types import Observation


class BatchModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "test-batch-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, **kwargs):
        complete = any(isinstance(m, ToolMessage) for m in messages)
        msg = AIMessage(
            content="done" if complete else "",
            tool_calls=[]
            if complete
            else [
                {"name": "observe_app", "args": {}, "id": "read-1"},
                {"name": "observe_app", "args": {}, "id": "read-2"},
            ],
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])


class ReadAdapter:
    def __init__(self):
        self.executed = []

    def observe(self):
        return Observation(revision="fixed", timestamp=1, screenshot="synthetic.png", state={})

    def tool_action(self, name, args):
        self.executed.append(name)
        return {"state": {}, "read": len(self.executed)}


def test_batched_model_tools_each_require_their_own_approval(store, job, monkeypatch):
    monkeypatch.setattr("enterprise.assistance.SimulatedModel", BatchModel)
    store.mode(job["id"], "auto")
    store.boundary(job["id"])
    store.transfer(job["id"], "assistant")
    adapter = ReadAdapter()
    layer = ExecutionLayer(store, adapter)
    agent = build_assistant(Settings(), store, layer, InMemorySaver(), job["id"], "batch")
    result = run_assistant(agent, {}, "batch")
    assert result.get("__interrupt__")
    approvals = store.approvals(job["id"])
    assert len(approvals) == 2 and not adapter.executed
    store.decide(approvals[0]["id"], {"decision": "approve"})
    result = run_assistant(agent, {}, "batch")
    assert result.get("__interrupt__") and len(adapter.executed) == 1
    assert store.approvals(job["id"])[1]["status"] == "pending"
    store.decide(approvals[1]["id"], {"decision": "approve"})
    result = run_assistant(agent, {}, "batch")
    assert not result.get("__interrupt__") and len(adapter.executed) == 2
    assert store.get_job(job["id"])["effective_mode"] == "strict"
