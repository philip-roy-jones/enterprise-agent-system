"""Storage containment tests; no model and no simulated business approvals."""

import pytest
from langchain_core.messages import HumanMessage, message_to_dict
from eas_harness.context_broker import ContextVault, RemoteCheckpointer
from eas_harness.learner_queue import read_response


def context_job(identity, staff="alice"):
    return dict(
        id=identity,
        staff_id=staff,
        conversation_id="ongoing-" + staff,
        organization_id="acme",
        department_id="finance",
        role_id="invoice_correction",
        company_id="ACME",
        permissions=["read"],
    )


def test_history_scope_and_opaque_checkpoints(tmp_path):
    vault = ContextVault(tmp_path)
    alice, bob = context_job("a"), context_job("b", "bob")
    vault.dispatch(
        alice,
        {"method": "archive", "messages": [message_to_dict(HumanMessage(content="private-alpha", id="one"))]},
    )
    assert not vault.dispatch(bob, {"method": "search", "query": "private-alpha"})["matches"]
    same = context_job("next")
    entry = vault.dispatch(same, {"method": "search", "query": "private-alpha"})["matches"][0]["entry_id"]
    with pytest.raises(PermissionError):
        vault.dispatch(bob, {"method": "read", "entry_id": entry})
    request = {
        "method": "checkpoint_put",
        "space": "agent",
        "config": {"thread_id": "a"},
        "data": {"id": "one", "checkpoint": ["pickle", "deliberately-invalid"], "parent": None},
    }
    vault.dispatch(alice, request)  # Privileged storage must not deserialize checkpoint bytes.
    with pytest.raises(PermissionError):
        vault.dispatch(bob, {**request, "method": "checkpoint_get"})


def test_graph_interrupt_survives_broker_checkpoint_resume(tmp_path):
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import interrupt, Command
    from typing_extensions import TypedDict

    job = context_job("request")
    vault = ContextVault(tmp_path)

    class Layer:
        def call(self, command, job_id, context):
            assert command == "context" and job_id == job["id"]
            return vault.dispatch(job, context)

    class State(TypedDict):
        answer: str

    graph = StateGraph(State)
    graph.add_node("ask", lambda state: {"answer": interrupt("Approve?")})
    graph.add_edge(START, "ask")
    graph.add_edge("ask", END)
    first = graph.compile(checkpointer=RemoteCheckpointer(Layer(), "agent"))
    config = {"configurable": {"thread_id": job["id"]}}
    assert first.invoke({"answer": ""}, config).get("__interrupt__")
    second = graph.compile(checkpointer=RemoteCheckpointer(Layer(), "agent"))
    assert second.invoke(Command(resume="denied"), config)["answer"] == "denied"


def test_learner_response_cannot_follow_link(tmp_path):
    source = tmp_path / "protected.json"
    source.write_text('{"secret": "must not read through learner output"}')
    link = tmp_path / "response"
    link.symlink_to(source)
    with pytest.raises((OSError, ValueError)):
        read_response(link)


def test_policy_change_does_not_reuse_checkpoint_notes_or_searchable_history(tmp_path):
    vault = ContextVault(tmp_path)
    first = vault.authorized_job(context_job("before"), "policy-1")
    vault.dispatch(
        first,
        {
            "method": "archive",
            "messages": [message_to_dict(HumanMessage(content="restricted-source", id="old"))],
        },
    )
    vault.dispatch(first, {"method": "manage", "invocation": "notes", "notes": "restricted-source"})
    with pytest.raises(PermissionError, match="Authorization changed"):
        vault.authorized_job(context_job("before"), "policy-2")
    # A fresh process must enforce the same boundary after restart.
    vault = ContextVault(tmp_path)
    after = vault.authorized_job(context_job("after"), "policy-2")
    assert not vault.dispatch(after, {"method": "search", "query": "restricted-source"})["matches"]
    window = vault.dispatch(after, {"method": "window", "runtime": "current authority", "max_chars": 1000})
    assert "restricted-source" not in str(window)
    restored = vault.authorized_job(context_job("restored"), "policy-1")
    assert not vault.dispatch(restored, {"method": "search", "query": "restricted-source"})["matches"]
