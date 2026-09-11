import multiprocessing
import sqlite3
import time
import pytest

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from eas_harness.assistance import build_assistant, run_assistant
from eas_harness.config import Settings
from eas_harness.execution import ExecutionLayer
from eas_server.store import Store
from eas_shared.types import JobInput, Observation


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
        return self.observe().model_dump()


def test_batched_model_tools_each_require_their_own_approval(store, job, monkeypatch):
    monkeypatch.setattr("eas_harness.assistance.SimulatedModel", BatchModel)
    store.mode(job["id"], "auto")
    store.boundary(job["id"])
    store.transfer(job["id"], "assistant")
    adapter = ReadAdapter()
    layer = ExecutionLayer(store, adapter)
    agent = build_assistant(
        Settings(model_mode="simulated"), store, layer, InMemorySaver(), job["id"], "batch"
    )
    result = run_assistant(agent, {}, "batch", store, job["id"])
    assert result.get("__interrupt__")
    approvals = store.approvals(job["id"])
    assert len(approvals) == 2 and not adapter.executed
    store.decide(approvals[0]["id"], {"decision": "approve"})
    result = run_assistant(agent, {}, "batch", store, job["id"])
    assert result.get("__interrupt__") and len(adapter.executed) == 1
    assert store.approvals(job["id"])[1]["status"] == "pending"
    store.decide(approvals[1]["id"], {"decision": "approve"})
    result = run_assistant(agent, {}, "batch", store, job["id"])
    assert not result.get("__interrupt__") and len(adapter.executed) == 2
    assert store.get_job(job["id"])["effective_mode"] == "strict"


class SlowSqliteSaver(SqliteSaver):
    def put(self, *args, **kwargs):
        # Let later graph work queue while the checkpoint executor is occupied.
        time.sleep(0.03)
        return super().put(*args, **kwargs)


def exercise_slow_checkpoints(data_dir):
    import eas_harness.assistance as assistance

    assistance.SimulatedModel = BatchModel
    store = Store(data_dir)
    job = store.create_job(JobInput(invoice_id="INV-1042").model_dump())
    store.claim("checkpoint-test")
    store.transfer(job["id"], "assistant")
    adapter = ReadAdapter()
    layer = ExecutionLayer(store, adapter)
    # Reopen the database and rebuild the agent at every staff decision: pending
    # tools must survive a restart, finish their writes, and execute exactly once.
    for step in range(3):
        with sqlite3.connect(data_dir / "assistant.sqlite", check_same_thread=False) as connection:
            agent = build_assistant(
                Settings(model_mode="simulated"), store, layer, SlowSqliteSaver(connection), job["id"], "slow"
            )
            result = run_assistant(agent, {}, "slow", store, job["id"])
        assert len(adapter.executed) == step
        pending = [a for a in store.approvals(job["id"]) if a["status"] == "pending"]
        if step < 2:
            assert result.get("__interrupt__") and len(pending) == 2 - step
            store.decide(pending[0]["id"], {"decision": "approve"})
        else:
            assert not result.get("__interrupt__") and not pending


def test_slow_sqlite_checkpoints_finish_and_resume_approved_tools(tmp_path):
    # A process deadline makes checkpoint deadlocks fail instead of hanging pytest.
    process = multiprocessing.get_context("spawn").Process(target=exercise_slow_checkpoints, args=(tmp_path,))
    process.start()
    try:
        process.join(timeout=20)
        assert not process.is_alive(), "Assistant checkpoint executor stalled"
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)


class PrematureSaveModel(BatchModel):
    def _generate(self, messages, **kwargs):
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="", tool_calls=[{"name": "save_draft", "args": {}, "id": "premature-save"}]
                    )
                )
            ]
        )


def test_model_cannot_save_before_comparison_even_if_it_requests_unavailable_tool(store, job, monkeypatch):
    monkeypatch.setattr("eas_harness.assistance.SimulatedModel", PrematureSaveModel)
    store.transfer(job["id"], "assistant")
    adapter = ReadAdapter()
    agent = build_assistant(
        Settings(model_mode="simulated"),
        store,
        ExecutionLayer(store, adapter),
        InMemorySaver(),
        job["id"],
        "premature",
    )
    with pytest.raises(PermissionError, match="comparison must verify"):
        run_assistant(agent, {}, "premature", store, job["id"])
    assert not adapter.executed and not store.approvals(job["id"])
