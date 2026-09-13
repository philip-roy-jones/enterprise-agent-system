import pytest
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from eas_harness.assistance import build_assistant, run_assistant
from enterprise_dev.config import Settings
from eas_harness.execution import ExecutionLayer
from test_assistant import BatchModel, ReadAdapter
from fastapi.testclient import TestClient
from eas_server.backend import create_app

from eas_server.conversation import Conversation
from eas_shared.types import JobInput, Stale, Stopped


def ask_approved(store, job, question="Which explanation should the draft include?"):
    store.transfer(job["id"], "assistant")
    epoch = store.lease()["epoch"]
    args = {"question": question}
    approval = store.proposal(
        job["id"],
        "question-tool",
        {
            "kind": "tool",
            "name": "ask_staff",
            "arguments": args,
            "epoch": epoch,
            "observation": {"revision": "fixture"},
        },
    )
    store.decide(approval["id"], {"decision": "approve"})
    store.begin_action(
        job["id"],
        "assistant",
        epoch,
        "question-tool",
        {
            "name": "ask_staff",
            "arguments": args,
            "observation_revision": "fixture",
        },
        approval["id"],
    )
    result = Conversation(store).ask(job["id"], question)
    store.finish_action(job["id"], "question-tool", result, approval["id"])
    return result


def test_question_requires_approved_exact_tool_call(store, job):
    store.transfer(job["id"], "assistant")
    with pytest.raises(PermissionError, match="approval"):
        Conversation(store).ask(job["id"], "May I change the draft explanation?")
    assert Conversation(store).read(job["id"])["questions"] == []


def test_question_and_answer_survive_reconnect_and_duplicate_submission(store, job):
    question = ask_approved(store, job)
    assert Conversation(store).read(job["id"])["questions"][0]["status"] == "pending"
    message = {
        "text": "Mention the quantity correction.",
        "reply_to": question["question_id"],
        "message_id": "reply-1",
    }
    first = Conversation(store).message(job["id"], message)
    assert Conversation(store).message(job["id"], message) == first
    restored = Conversation(store).read(job["id"])
    assert len(restored["messages"]) == 1
    assert restored["questions"][0]["answer"] == message["text"]
    assert restored["questions"][0]["status"] == "answered"
    assert store.get_job(job["id"])["effective_mode"] == "strict"
    with pytest.raises(Stale):
        Conversation(store).message(job["id"], message | {"text": "Different content"})


def test_answer_cannot_target_another_jobs_question(store, job):
    question = ask_approved(store, job)
    other = store.create_job(JobInput(invoice_id="INV-1043").model_dump())
    with pytest.raises(ValueError, match="belong"):
        Conversation(store).message(other["id"], {"text": "yes", "reply_to": question["question_id"]})
    assert Conversation(store).read(job["id"])["questions"][0]["status"] == "pending"


def test_late_answer_does_not_revive_cancelled_job(store, job):
    question = ask_approved(store, job)
    store.stop(job["id"])
    with pytest.raises(Stopped):
        Conversation(store).message(job["id"], {"text": "yes", "reply_to": question["question_id"]})
    assert store.get_job(job["id"])["status"] == "cancelled"


def test_staff_guidance_invalidates_queued_proposals_without_approving_them(store, job):
    approval = store.proposal(
        job["id"],
        "pending",
        {
            "kind": "node",
            "name": "prepare",
            "arguments": {},
            "epoch": store.lease()["epoch"],
            "observation": {"revision": "fixture"},
        },
    )
    Conversation(store).message(job["id"], {"text": "Please reconsider the explanation."})
    assert store.approvals(job["id"])[0]["id"] == approval["id"]
    assert store.approvals(job["id"])[0]["status"] == "stale"
    assert store.get_job(job["id"])["mutation"] == "not_attempted"


class QuestionModel(BatchModel):
    def _generate(self, messages, **kwargs):
        asked = any(isinstance(m, ToolMessage) and m.name == "ask_staff" for m in messages)
        if asked:
            guidance = [
                m.content
                for m in messages
                if isinstance(m, HumanMessage) and m.additional_kwargs.get("eas_staff_guidance")
            ]
            assert any("quantity correction" in text for text in guidance)
        message = AIMessage(
            content="Staff requested that the explanation mention the quantity correction." if asked else "",
            tool_calls=[]
            if asked
            else [
                {
                    "name": "ask_staff",
                    "args": {"question": "What should the explanation mention?"},
                    "id": "question-1",
                }
            ],
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


def test_agent_question_waits_without_model_calls_then_resumes_with_staff_answer(store, job, monkeypatch):
    monkeypatch.setattr("eas_harness.assistance.SimulatedModel", QuestionModel)
    store.transfer(job["id"], "assistant")
    checkpoint = InMemorySaver()
    adapter = ReadAdapter()

    def agent():
        return build_assistant(
            Settings(model_mode="simulated"),
            store,
            ExecutionLayer(store, adapter),
            checkpoint,
            job["id"],
            "question-flow",
        )

    result = run_assistant(agent(), {}, "question-flow", store, job["id"])
    assert result.get("__interrupt__")
    assert Conversation(store).read(job["id"])["questions"] == []
    approval = store.approvals(job["id"])[0]
    assert approval["name"] == "ask_staff"
    store.decide(approval["id"], {"decision": "approve"})
    result = run_assistant(agent(), {}, "question-flow", store, job["id"])
    assert result.get("__interrupt__")
    question = Conversation(store).read(job["id"])["questions"][0]
    assert question["status"] == "pending" and store.get_job(job["id"])["model_calls"] == 1
    assert run_assistant(agent(), {}, "question-flow", store, job["id"]).get("__interrupt__")
    assert store.get_job(job["id"])["model_calls"] == 1
    Conversation(store).message(
        job["id"], {"text": "Mention the quantity correction.", "reply_to": question["question_id"]}
    )
    result = run_assistant(agent(), {}, "question-flow", store, job["id"])
    assert not result.get("__interrupt__")
    assert store.get_job(job["id"])["model_calls"] == 2
    assert not adapter.executed
    assert any(
        e["kind"] == "assistant_message" and "quantity correction" in e["data"]["text"]
        for e in store.events(job["id"])
    )


def test_new_guidance_discards_queued_tools_and_reaches_the_next_model_turn(store, job, monkeypatch):
    monkeypatch.setattr("eas_harness.assistance.SimulatedModel", BatchModel)
    store.transfer(job["id"], "assistant")
    adapter = ReadAdapter()
    agent = build_assistant(
        Settings(model_mode="simulated"),
        store,
        ExecutionLayer(store, adapter),
        InMemorySaver(),
        job["id"],
        "guidance",
    )
    assert run_assistant(agent, {}, "guidance", store, job["id"]).get("__interrupt__")
    store.decide(store.approvals(job["id"])[0]["id"], {"decision": "approve"})
    Conversation(store).message(job["id"], {"text": "Reconsider the proposed actions before proceeding."})
    result = run_assistant(agent, {}, "guidance", store, job["id"])
    assert not result.get("__interrupt__") and not adapter.executed
    messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert all("guidance changed" in m.content for m in messages)
    used = [
        e["data"]["message_sequences"] for e in store.events(job["id"]) if e["kind"] == "conversation_context"
    ]
    assert used[-1] == [Conversation(store).read(job["id"])["revision"]]


def test_worker_cannot_submit_staff_answers_or_read_another_organization(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, desktop_adapter="browser"))
    client = TestClient(app, headers={"Authorization": "Bearer local-worker-demo"})
    foreign = app.state.store.create_job(
        JobInput(organization_id="other", invoice_id="INV-1042").model_dump()
    )
    assert client.post(f"/api/jobs/{foreign['id']}/messages", json={"text": "approve"}).status_code == 403
    assert client.post("/api/worker/conversation", json={"args": [foreign["id"]]}).status_code == 403
    assert client.post("/api/worker/ask_staff", json={"args": [foreign["id"], "question"]}).status_code == 403
