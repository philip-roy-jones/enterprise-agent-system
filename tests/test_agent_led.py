"""Real separate processes; all staff decisions and model behavior explicitly simulated."""

import time
from conftest import pending


def test_malformed_recovery_click_returns_to_model_before_any_approval(store, job, tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import InMemorySaver
    from eas_harness.coordinator import Coordinator, SimulatedCoordinator
    from eas_harness.execution import ExecutionLayer
    from test_execution import FakeAdapter

    settings = SimpleNamespace(
        data_dir=tmp_path, model_mode="simulated", model_id="", model_provider="", max_model_calls=4
    )
    run = {"state": "needs_assistance", "run_id": "existing-workflow", "version": "pinned-version"}
    store.update_job(job["id"], {"skill_runs": {"existing-workflow": run}})
    calls = []

    def generate(self, messages, **kwargs):
        calls.append(messages)
        args = {"target": "invoices", "x": 96.5, "y": 234}
        if len(calls) == 2:
            error = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
            assert error.status == "error" and json.loads(error.content)["error"] == "invalid_arguments"
            assert "Specify a target or both screen coordinates" in error.content
            args = {"target": "invoices"}
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "click",
                                "args": args,
                                "id": f"recovery-{len(calls)}",
                            }
                        ],
                    )
                )
            ]
        )

    monkeypatch.setattr(SimulatedCoordinator, "_generate", generate)
    coordinator = Coordinator(
        settings, store, ExecutionLayer(store, FakeAdapter()), InMemorySaver(), InMemorySaver()
    )
    coordinator.tick(store.get_job(job["id"]))
    current = store.get_job(job["id"])
    assert current["status"] == "running" and current["execution_state"] == "awaiting_approval"
    assert current["skill_runs"] == {"existing-workflow": run}
    approvals = store.approvals(job["id"])
    assert len(approvals) == 1 and approvals[0]["status"] == "pending"
    assert approvals[0]["arguments"] == {"target": "invoices", "x": None, "y": None}
    assert not any(e["kind"] == "action_started" for e in store.events(job["id"]))
    assert len([e for e in store.events(job["id"]) if e["kind"] == "tool_arguments_rejected"]) == 1


def finish(ctx, job_id):
    client = ctx["client"]
    deadline = time.monotonic() + 60
    names = []
    while time.monotonic() < deadline:
        d = client.get("/api/jobs/" + job_id).json()
        if d["job"]["status"] == "completed":
            return d, names
        assert d["job"]["status"] not in {"failed", "denied", "rejected", "cancelled"}, d["job"]
        for a in d["approvals"]:
            if a["status"] == "pending":
                names.append(a["name"])
                ctx["store"].decide(a["id"], {"decision": "approve"}, actor="simulated-staff")
        time.sleep(0.1)
    raise AssertionError(d)


def test_agent_workflow_has_child_approvals(browser_server):
    ctx = browser_server
    r = ctx["client"].post("/api/jobs", json={"invoice_id": "INV-1042"})
    r.raise_for_status()
    job_id = r.json()["id"]
    assert pending(ctx["client"], job_id)["name"] == "read_skill"
    d, names = finish(ctx, job_id)
    assert names == [
        "read_skill",
        "run_skill",
        "validate",
        "establish",
        "compare",
        "prepare",
        "save",
        "verify",
        "complete",
    ]
    assert d["job"]["mutation"] == "confirmed_succeeded"
    assert list(d["job"]["skill_runs"].values())[0]["state"] == "completed"


def test_agent_unknown_report(browser_server):
    ctx = browser_server
    r = ctx["client"].post(
        "/api/jobs",
        json={"invoice_id": "INV-1043", "task": "Report and classify the discrepancy without saving"},
    )
    r.raise_for_status()
    d, names = finish(ctx, r.json()["id"])
    assert names == ["validate", "establish", "compare", "judge", "report", "complete"]
    assert d["job"]["mutation"] == "not_attempted"
    assert d["job"]["verified_report"]["invoice_id"] == "INV-1043"


def test_auto_is_rejected(browser_server):
    assert (
        browser_server["client"]
        .post("/api/jobs", json={"invoice_id": "INV-1042", "selected_mode": "auto"})
        .status_code
        == 422
    )


def learning_result(ctx, job_id):
    end = time.monotonic() + 65
    while time.monotonic() < end:
        status = ctx["client"].get("/api/learning").json()
        entry = next((x for x in status["queue"] if x.get("job_id") == job_id), None)
        if entry and entry["status"] == "completed":
            return entry["result"]
        time.sleep(0.2)
    raise AssertionError(status)


def test_learning_accumulates_and_pins(browser_server):
    ctx = browser_server
    client = ctx["client"]

    def run(task, invoice):
        r = client.post("/api/jobs", json={"invoice_id": invoice, "task": task})
        r.raise_for_status()
        d, names = finish(ctx, r.json()["id"])
        client.post("/api/jobs/" + d["job"]["id"] + "/accept").raise_for_status()
        return d, names, learning_result(ctx, d["job"]["id"])

    first, names, learn = run("Report the discrepancy without saving", "INV-1042")
    assert learn["status"] == "activated", learn
    assert "run_skill" not in names
    assert learn["candidate"]["steps"] == ["validate", "establish", "compare", "report", "complete"]
    from eas_harness.skill_library import SkillLibrary

    library = SkillLibrary(ctx["data_dir"])
    v1 = learn["version"]
    key = learn["skill_id"]
    second, names, reuse = run("Report the discrepancy without saving", "INV-1043")
    assert "run_skill" in names
    assert reuse["status"] == "no_change", reuse
    third, names, revision = run("Report and classify the discrepancy without saving", "INV-1044")
    assert revision["status"] == "activated", revision
    assert revision["skill_id"] == key and revision["previous"] == v1
    assert "judge" in revision["candidate"]["steps"]
    assert library.get(key, v1, first["job"])["steps"] == learn["candidate"]["steps"]
    r = client.post("/api/skills/" + key + "/change", json={"version": v1})
    r.raise_for_status()
    end = time.monotonic() + 15
    while time.monotonic() < end:
        if library.catalog(first["job"])[-1]["version"] == v1:
            break
        time.sleep(0.2)
    assert library.get(key, v1, first["job"], active_only=True)
    assert len([x for x in library.history() if x["action"] == "activated" and x["skill_id"] == key]) == 2


def test_request_identity_is_durable(browser_server):
    c = browser_server["client"]
    payload = {
        "invoice_id": "INV-1042",
        "conversation_id": "conversation-test",
        "request_id": "message-1",
        "task": "Report discrepancy",
    }
    first = c.post("/api/jobs", json=payload)
    assert first.status_code == 200
    assert c.post("/api/jobs", json=payload).json()["id"] == first.json()["id"]
    assert c.post("/api/jobs", json={**payload, "task": "Different request"}).status_code == 409
    second = c.post("/api/jobs", json={**payload, "request_id": "message-2"})
    assert second.json()["conversation_id"] == first.json()["conversation_id"]
    assert second.json()["id"] != first.json()["id"]


def test_runtime_final_verification_needs_approval_when_model_stops_early(store, job, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from langgraph.checkpoint.memory import InMemorySaver
    from eas_harness.coordinator import Coordinator
    from eas_harness.execution import ExecutionLayer
    from test_execution import FakeAdapter

    store.update_job(
        job["id"],
        {
            "verified_report": {"difference": 20000},
            "completed": ["validate", "establish", "compare", "report"],
        },
    )
    settings = SimpleNamespace(data_dir=tmp_path, model_mode="simulated", model_id="", model_provider="")
    coordinator = Coordinator(
        settings, store, ExecutionLayer(store, FakeAdapter()), InMemorySaver(), InMemorySaver()
    )
    monkeypatch.setattr(coordinator, "build", lambda _: object())
    monkeypatch.setattr("eas_harness.coordinator.run_assistant", lambda *args: {"messages": []})
    verified = []

    def complete(name, state):
        assert name == "complete"
        verified.append(state)
        return {"verified": True, "acceptance_required": True}

    monkeypatch.setattr(coordinator.skills, "operation", complete)
    coordinator.tick(store.get_job(job["id"]))
    assert not verified and store.get_job(job["id"])["status"] == "running"
    approval = store.approvals(job["id"])[0]
    assert approval["name"] == "complete"
    store.decide(approval["id"], {"decision": "approve"}, actor="simulated-staff")
    coordinator.tick(store.get_job(job["id"]))
    assert len(verified) == 1 and store.get_job(job["id"])["status"] == "completed"
    assert store.get_job(job["id"])["operation_trace"][-1]["operation"] == "complete"


def test_completed_child_workflow_returns_to_agent_for_remaining_work(store, job, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import InMemorySaver
    from eas_harness.coordinator import Coordinator, SimulatedCoordinator
    from eas_harness.candidate_checks import FixtureAdapter
    from eas_harness.execution import ExecutionLayer
    from eas_harness.maintenance import evidence_for
    from eas_shared.identity import fingerprint
    from eas_shared.types import Observation
    from test_skill_admission import sample

    class Adapter(FixtureAdapter):
        def observe(self):
            view = super().observe()
            return Observation(
                revision=fingerprint(view.state),
                timestamp=1,
                screenshot="",
                state=view.state,
                targets=view.targets,
            )

        def save_and_verify(self, expected):
            self.saved = {**super().save_and_verify(expected), "id": "fixture-draft"}
            return self.saved

    settings = SimpleNamespace(
        data_dir=tmp_path, model_mode="simulated", model_id="", model_provider="", max_model_calls=10
    )
    adapter = Adapter(job, 15327, 12340, "Correction amount")
    coordinator = Coordinator(
        settings, store, ExecutionLayer(store, adapter), InMemorySaver(), InMemorySaver()
    )
    report = {**sample(), "application_version": job["app_version"]}
    coordinator.library.install(report)
    coordinator.library.seed(job)
    correction = next(s for s in coordinator.library.catalog(job) if s["skill_id"] == "invoice_correction")
    selections = [
        ("read_skill", {"skill_id": "report"}),
        ("run_skill", {"skill_id": "report"}),
        ("read_skill", {"skill_id": correction["skill_id"]}),
        ("run_skill", {"skill_id": correction["skill_id"]}),
    ]
    calls = []

    def generate(self, messages, **kwargs):
        index = len(calls)
        if index == 2:
            import json
            from langchain_core.messages import ToolMessage

            result = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
            assert result["comparison"]["invoice_amount"] == 15327
            assert result["comparison"]["purchase_order_amount"] == 12340
            assert result["comparison"]["units"] == "cents"
            assert result["verified_report"]["difference"] == 2987
        calls.append(index)
        tool_calls = (
            [{"name": selections[index][0], "args": selections[index][1], "id": f"composition-{index}"}]
            if index < len(selections)
            else []
        )
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="Both requested outcomes verified." if not tool_calls else "",
                        tool_calls=tool_calls,
                    )
                )
            ]
        )

    monkeypatch.setattr(SimulatedCoordinator, "_generate", generate)
    for _ in range(35):
        coordinator.tick(store.get_job(job["id"]))
        current = store.get_job(job["id"])
        if current["status"] == "completed":
            break
        for approval in store.approvals(job["id"]):
            if approval["status"] == "pending":
                store.decide(approval["id"], {"decision": "approve"}, actor="simulated-staff")
    assert current["status"] == "completed" and adapter.saves == 1
    assert len(current["skill_runs"]) == 2 and len(calls) == 5
    assert all(r["state"] == "completed" for r in current["skill_runs"].values())
    approvals = store.approvals(job["id"])
    assert sum(a["name"] == "run_skill" for a in approvals) == 2
    assert all(a["status"] == "executed" and a.get("decision") for a in approvals)
    store.accept(job["id"])
    with store.db() as db:
        evidence, _ = evidence_for(store.learning_episode(db, job["id"]), coordinator.library)
    assert evidence["steps"] == [
        "validate",
        "establish",
        "compare",
        "report",
        "prepare",
        "save",
        "verify",
        "complete",
    ]


def test_ordinary_chat_reply_has_no_business_approval(browser_server):
    client = browser_server["client"]
    response = client.post(
        "/api/jobs", json={"invoice_id": "INV-1042", "task": "Hello", "conversation_id": "chat-session"}
    )
    response.raise_for_status()
    from conftest import wait_for

    data = wait_for(client, response.json()["id"], lambda d: d["job"]["status"] == "completed")
    assert data["job"]["result_kind"] == "conversation"
    assert not data["approvals"] and not data["job"].get("operation_trace")
    second = client.post(
        "/api/jobs", json={"invoice_id": "INV-1042", "task": "Thanks", "conversation_id": "chat-session"}
    )
    second.raise_for_status()
    data = wait_for(client, second.json()["id"], lambda d: d["job"]["status"] == "completed")
    assert data["conversation"]["requests"][0]["task"] == "Hello"
    assert data["conversation"]["requests"][0]["reply"]
