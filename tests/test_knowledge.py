import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from eas_harness.assistance import build_assistant, run_assistant
from eas_server.backend import create_app
from enterprise_dev.config import Settings
from eas_harness.execution import ExecutionLayer
from eas_shared.types import JobInput
from eas_harness.errors import Paused
from test_assistant import BatchModel, ReadAdapter


def document(**overrides):
    return (
        dict(
            organization_id="acme",
            department_id="finance",
            role_id="invoice_correction",
            company_id="ACME",
            title="Invoice guidance",
            content="Prepare a correction draft only.",
        )
        | overrides
    )


def approved_search(store, job, query="invoice"):
    store.transfer(job["id"], "assistant")
    layer = ExecutionLayer(store, ReadAdapter())

    def invoke():
        return layer.run(
            job["id"],
            job["id"] + ":knowledge",
            "search_knowledge",
            {"query": query},
            lambda args: store.search_knowledge(job["id"], args["query"]),
            kind="tool",
        )

    with pytest.raises(Paused):
        invoke()
    approval = store.approvals(job["id"])[-1]
    store.decide(approval["id"], {"decision": "approve"})
    return invoke()["value"]["documents"]


def test_knowledge_filters_every_scope_before_search(store, job, monkeypatch):
    from dataclasses import replace
    from eas_server.roles import ROLES

    monkeypatch.setitem(
        ROLES, "other_finance_role", replace(ROLES["invoice_correction"], id="other_finance_role")
    )
    allowed = store.add_knowledge(document())
    shared = store.add_knowledge(document(department_id=None, role_id=None, company_id=None))
    for overrides in [
        dict(organization_id="other"),
        dict(department_id="people", role_id=None),
        dict(company_id="OTHER"),
        dict(role_id="other_finance_role"),
    ]:
        store.add_knowledge(document(**overrides))
    docs = approved_search(store, job)
    assert {d["id"] for d in docs} == {allowed["id"], shared["id"]}
    assert all(d["revision"] == 1 for d in docs)
    event = next(e for e in store.events(job["id"]) if e["kind"] == "knowledge_retrieved")
    assert {d["id"] for d in event["data"]["documents"]} == {allowed["id"], shared["id"]}


def test_knowledge_cannot_be_read_without_the_exact_approved_search(store, job):
    store.add_knowledge(document())
    store.transfer(job["id"], "assistant")
    with pytest.raises(PermissionError, match="exact search"):
        store.search_knowledge(job["id"], "invoice")
    assert not any(e["kind"] == "knowledge_retrieved" for e in store.events(job["id"]))


def test_knowledge_requires_read_permission(store):
    job = store.create_job(JobInput(invoice_id="INV-1042", permissions=["navigate"]).model_dump())
    store.claim("test")
    store.transfer(job["id"], "assistant")
    with pytest.raises(PermissionError, match="read permission"):
        store.search_knowledge(job["id"], "invoice")


def test_worker_cannot_publish_knowledge_or_choose_another_scope(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, desktop_adapter="browser"))
    client = TestClient(app, headers={"Authorization": "Bearer local-worker-demo"})
    assert client.post("/api/knowledge", json=document()).status_code == 403
    foreign = app.state.store.create_job(
        JobInput(organization_id="other", invoice_id="INV-1042").model_dump()
    )
    own = app.state.store.create_job(JobInput(invoice_id="INV-1043").model_dump())
    claim = client.post("/api/worker/claim", json={"args": ["worker"]})
    assert claim.json()["id"] == own["id"]
    assert (
        client.post("/api/worker/search_knowledge", json={"args": [foreign["id"], "invoice"]}).status_code
        == 403
    )
    assert (
        client.post("/api/worker/claim", json={"args": ["worker"], "kwargs": {"scope": None}}).status_code
        == 409
    )
    assert (
        client.post(
            "/api/worker/search_knowledge",
            json={"args": [own["id"], "invoice"], "kwargs": {"organization_id": "other"}},
        ).status_code
        == 409
    )


class KnowledgeModel(BatchModel):
    def _generate(self, messages, **kwargs):
        done = any(isinstance(message, ToolMessage) for message in messages)
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="done" if done else "",
                        tool_calls=[]
                        if done
                        else [
                            {"name": "search_knowledge", "args": {"query": "invoice"}, "id": "knowledge-1"}
                        ],
                    )
                )
            ]
        )


def test_assistant_knowledge_read_waits_for_staff_in_strict(store, job, monkeypatch):
    monkeypatch.setattr("eas_harness.assistance.SimulatedModel", KnowledgeModel)
    doc = store.add_knowledge(document())
    store.boundary(job["id"])
    store.transfer(job["id"], "assistant")
    adapter = ReadAdapter()
    agent = build_assistant(
        Settings(model_mode="simulated"),
        store,
        ExecutionLayer(store, adapter),
        InMemorySaver(),
        job["id"],
        "knowledge",
    )
    result = run_assistant(agent, {}, "knowledge", store, job["id"])
    assert result.get("__interrupt__")
    assert not any(e["kind"] == "knowledge_retrieved" for e in store.events(job["id"]))
    approval = store.approvals(job["id"])[0]
    assert approval["name"] == "search_knowledge"
    store.decide(approval["id"], {"decision": "approve"})
    result = run_assistant(agent, {}, "knowledge", store, job["id"])
    assert not result.get("__interrupt__")
    message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert doc["id"] in message.content
    assert not adapter.executed  # Guidance came from the backend, not a desktop/application API.
    assert store.get_job(job["id"])["effective_mode"] == "strict"
