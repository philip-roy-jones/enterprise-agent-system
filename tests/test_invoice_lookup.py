"""Invoice totals do not require discrepancy workflows; absent records end clearly."""

import pytest
from eas_harness.errors import RecordUnavailable, check_visible_invoice
from eas_shared.types import Observation
from test_agent_led import finish


@pytest.mark.parametrize("amount", [7305, 38129])
def test_model_can_answer_from_observation_without_a_workflow(store, job, tmp_path, monkeypatch, amount):
    """Scripted model decisions test the authority path, not live intent selection."""
    import json
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import InMemorySaver
    from eas_harness.coordinator import Coordinator, SimulatedCoordinator
    from eas_harness.execution import ExecutionLayer
    from eas_harness.candidate_checks import FixtureAdapter
    from eas_shared.identity import fingerprint

    class Adapter(FixtureAdapter):
        def observe(self):
            state = super().observe().state
            return Observation(
                revision=fingerprint(state), timestamp=1, screenshot="fixture.png", state=state
            )

        def tool_action(self, name, arguments):
            assert name == "observe_app" and arguments == {}
            return self.observe().model_dump()

    def generate(self, messages, **kwargs):
        results = [m for m in messages if isinstance(m, ToolMessage)]
        if not results:
            name, args = "run_operation", {"operation": "establish"}
        elif results[-1].name == "run_operation":
            name, args = "observe_app", {}
        else:
            observation = json.loads(results[-1].content)
            invoice = observation["state"]["invoices"][0]
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content=f"Simulated answer: {invoice['id']} totals ${invoice['amount'] / 100:,.2f}."
                        )
                    )
                ]
            )
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="Simulated decision: inspect the requested record.",
                        tool_calls=[{"name": name, "args": args, "id": f"fixture-{len(results)}"}],
                    )
                )
            ]
        )

    monkeypatch.setattr(SimulatedCoordinator, "_generate", generate)
    adapter = Adapter(job, amount, 5000, "Correction amount")
    coordinator = Coordinator(
        SimpleNamespace(
            data_dir=tmp_path, model_mode="simulated", model_id="", model_provider="", max_model_calls=6
        ),
        store,
        ExecutionLayer(store, adapter),
        InMemorySaver(),
        InMemorySaver(),
    )
    names = []
    for _ in range(8):
        coordinator.tick(store.get_job(job["id"]))
        current = store.get_job(job["id"])
        if current["status"] == "completed":
            break
        pending = [a for a in store.approvals(job["id"]) if a["status"] == "pending"]
        assert len(pending) == 1
        approval = pending[0]
        names.append(approval["name"])
        if approval["name"] == "review_discovery":
            assert f"${amount / 100:,.2f}" in approval["arguments"]["assistant_report"]
            assert current["status"] != "completed"  # The answer still needs staff's decision.
        store.decide(approval["id"], {"decision": "approve"}, actor="simulated-staff")
    assert names == ["establish", "observe_app", "review_discovery"]
    assert current["status"] == "completed" and current["result_kind"] == "reviewed_outcome"
    assert current["expected"] is None and not current.get("skill_runs")
    assert current["mutation"] == "not_attempted" and not current["accepted"]
    assert f"${amount / 100:,.2f}" in current["assistant_report"]


def test_absent_record_ends_lookup_without_generic_recovery(browser_server):
    task = "Report the discrepancy for INV-5783 without saving"
    ctx = browser_server
    response = ctx["client"].post("/api/chat", json={"task": task})
    response.raise_for_status()
    data, names = finish(ctx, response.json()["job"]["id"])
    assert data["job"]["result_kind"] == "record_unavailable"
    assert "observe_app" not in names and "ask_staff" not in names
    assert data["job"]["mutation"] == "not_attempted"
    replies = [e["data"]["text"] for e in data["events"] if e["kind"] == "assistant_message"]
    assert "couldn't find INV-5783 in the current invoice list" in replies[-1]
    assert "No changes" not in replies[-1]


def test_visible_list_absence_is_not_ui_ambiguity_or_global_nonexistence():
    observation = Observation(
        revision="visible-list",
        timestamp=1,
        screenshot="list.png",
        state={"company_id": "ACME", "view": "invoices", "dialog": None},
        targets=[{"target": "open-INV-1042"}],
    )
    with pytest.raises(RecordUnavailable) as error:
        check_visible_invoice(observation, "INV-5783", "ACME")
    assert error.value.evidence["scope"] == "currently visible invoice list"
    check_visible_invoice(observation, "INV-1042", "ACME")
    check_visible_invoice(observation.model_copy(update={"targets": []}), "INV-5783", "ACME")
    check_visible_invoice(
        observation.model_copy(update={"state": {**observation.state, "dialog": "unfamiliar"}}),
        "INV-5783",
        "ACME",
    )
    check_visible_invoice(observation, "INV-5783", "OTHER")
