"""Learning evidence, feedback and guidance admission; model/staff behavior is simulated."""

import json
from types import SimpleNamespace
import pytest
from eas_shared.types import JobInput, Observation, Recovery
from eas_harness.execution import ExecutionLayer
from eas_harness.skill_library import SkillLibrary
from eas_harness.maintenance import evidence_for, admit, maintain, validate_recommendations
from eas_server.evaluation import assess_action
from conftest import approve_operation
from test_skill_admission import sample, scoped


def guidance():
    return {
        **sample(),
        "skill_id": "record_observation",
        "steps": [],
        "task": "Inspect the requested record",
        "description": "Answer from approved observations",
        "instructions": "Open the assigned record with establish, use observe_app, and answer only the requested facts. Stop if identity is ambiguous. Staff reviews the outcome.",
        "supporting_files": {
            "references/verification.md": "Check the current company and record before reporting observed facts."
        },
    }


def teaching(spec, episode="episode-1", previous=None):
    return {
        "kind": "guidance",
        "scope": {
            k: spec[k]
            for k in ("organization_id", "department_id", "role_id", "company_id", "application_version")
        },
        "episode_id": episode,
        "previous": previous,
        "steps": [],
        "labels": spec["amount_labels"],
        "verification": {"invoice_id": "INV-1042", "invoice_amount": 148000},
    }


def test_guidance_can_improve_without_changing_steps_and_resources_remain_pinned(tmp_path):
    library = SkillLibrary(tmp_path)
    spec = guidance()
    first = admit(library, spec, teaching(spec), "")
    assert first["status"] == "activated" and first["checks"]["model_mode"] == "none"
    assert "not performed" in first["checks"]["behavioral_evaluation"]
    old = library.get(spec["skill_id"], first["version"], scoped(spec))
    changed = {
        **spec,
        "instructions": spec["instructions"] + " After a staff correction, re-observe before answering.",
        "evidence_ids": ["episode-1", "episode-2"],
    }
    second = admit(library, changed, teaching(spec, "episode-2", old), first["version"])
    assert second["version"] != first["version"] and second["changes"]["steps_after"] == []
    assert "staff correction" in second["changes"]["instructions_diff"]
    pinned = {**scoped(spec), "skill_reads": {spec["skill_id"]: first["version"]}}
    assert (
        library.resource(spec["skill_id"], first["version"], "references/verification.md", pinned)["text"]
        == spec["supporting_files"]["references/verification.md"]
    )
    with pytest.raises(PermissionError):
        library.resource(spec["skill_id"], first["version"], "../../.env", pinned)
    with pytest.raises(PermissionError):
        library.resource(spec["skill_id"], first["version"], "references/verification.md", scoped(spec))
    resource = library.root / spec["skill_id"] / first["version"] / "references/verification.md"
    resource.write_text("Changed outside admission")
    with pytest.raises(PermissionError, match="supporting file changed"):
        library.resource(spec["skill_id"], first["version"], "references/verification.md", pinned)


@pytest.mark.parametrize(
    "resource",
    [
        "../private.txt",
        "references/../../private.txt",
        "/absolute.txt",
        "references/script.py",
        "references\\private.txt",
    ],
)
def test_supporting_resources_cannot_be_executable_or_escape(tmp_path, resource):
    with pytest.raises(ValueError):
        SkillLibrary(tmp_path).install({**guidance(), "supporting_files": {resource: "untrusted"}})


def test_resource_cannot_memorize_teaching_amount_or_record(tmp_path):
    spec = guidance()
    for text in ["Always report $1,480.00", "Always open INV-1042"]:
        with pytest.raises(ValueError, match="memorizes"):
            admit(
                SkillLibrary(tmp_path),
                {**spec, "supporting_files": {"references/value.md": text}},
                teaching(spec),
                "",
            )


def test_accepted_observation_and_later_negative_feedback_enter_learning(store, job, tmp_path):
    class Adapter:
        def observe(self):
            return Observation(
                revision="synthetic",
                timestamp=1,
                screenshot="",
                state={"company_id": "ACME", "invoice_id": "INV-1042", "amount": 7305},
            )

    store.transfer(job["id"], "assistant", store.lease()["epoch"])
    layer = ExecutionLayer(store, Adapter())
    approve_operation(
        layer,
        job["id"],
        "observation",
        "observe_app",
        {},
        lambda _: layer.adapter.observe().model_dump(),
        kind="tool",
    )
    args = {
        "company_id": job["company_id"],
        "invoice_id": job["invoice_id"],
        "assistant_report": "Observed total was 73.05; checked the current record.",
    }
    approve_operation(
        layer,
        job["id"],
        "outcome-review",
        "review_discovery",
        args,
        lambda a: {"staff_verified_outcome": a["assistant_report"], "acceptance_required": True},
    )
    store.update_job(job["id"], {"status": "completed", "result_kind": "reviewed_outcome"})
    store.accept(job["id"])
    assert store.learning_status()["queue"][0]["kind"] == "learn"
    with store.db() as db:
        episode = store.learning_episode(db, job["id"])
    evidence, _ = evidence_for(episode, SkillLibrary(tmp_path))
    assert evidence["kind"] == "guidance" and evidence["steps"] == []
    assert evidence["verification"]["staff_verified_outcome"] == args["assistant_report"]
    assert evidence["approved_actions"][0]["name"] == "observe_app"
    assess_action(
        store,
        job["id"],
        {
            "invocation": "observation",
            "outcome": "incorrect",
            "explanation": "Staff found the record changed before reporting.",
        },
    )
    assert not store.get_job(job["id"])["accepted"]
    queue = store.learning_status()["queue"]
    assert sum(q.get("trigger") == "incorrect_assessment" for q in queue) == 1
    assess_action(
        store,
        job["id"],
        {
            "invocation": "observation",
            "outcome": "incorrect",
            "explanation": "Staff found the record changed before reporting.",
        },
    )
    assert len(store.learning_status()["queue"]) == len(queue)
    with pytest.raises(ValueError, match="staff-accepted"):
        with store.db() as db:
            evidence_for(store.learning_episode(db, job["id"]), SkillLibrary(tmp_path))


def test_repeated_failures_queue_one_bounded_review_and_never_activate(store, tmp_path):
    scope = {"organization_id": "acme", "role_ids": ["invoice_correction"]}
    for invoice in ["INV-1042", "INV-1043"]:
        j = store.create_job(
            JobInput(invoice_id=invoice, task=f"Inspect unsupported field for {invoice}").model_dump()
        )
        store.update_job(j["id"], {"status": "failed", "error": "unsupported control"})
    queue = store.learning_status()["queue"]
    assert len(queue) == 1 and queue[0]["trigger"] == "repeated_failure"
    assert len(queue[0]["related_job_ids"]) == 1
    assert store.learning_claim("wrong", {"organization_id": "other", "role_ids": scope["role_ids"]}) is None

    class RPC:
        def learning_claim(self, worker):
            return store.learning_claim(worker, scope)

        def learning_finish(self, key, claim, value):
            return store.learning_finish(key, claim, value, scope)

        def skills_publish(self, metadata):
            return store.skills_publish(metadata, scope)

    library = SkillLibrary(tmp_path)
    maintain(
        SimpleNamespace(
            data_dir=tmp_path, learning_enabled=True, model_mode="simulated", model_provider="", model_id=""
        ),
        RPC(),
        "fixture-worker",
        library,
    )
    result = store.learning_status()["queue"][0]["result"]
    assert result["status"] == "reviewed" and result["candidate"] is None
    assert result["recommendations"][0]["kind"] == "development_request"
    assert not library.metadata()["versions"]
    with pytest.raises(ValueError, match="cannot activate"):
        admit(library, guidance(), {**teaching(guidance()), "kind": "review"}, "")


def test_lifecycle_suggestions_are_scoped_and_do_not_change_registry(tmp_path):
    spec = guidance()
    library = SkillLibrary(tmp_path)
    version = library.install(spec)
    ev = {"episode_id": "episode-1", "catalog": library.catalog(scoped(spec)), "related": []}
    proposals = [
        {
            "kind": kind,
            "skill_ids": [spec["skill_id"]],
            "reason": "Recorded correction invalidates this guidance; review before future reuse.",
            "evidence_ids": ["episode-1"],
        }
        for kind in ["suspend", "retire", "consolidate"]
    ]
    assert all(r["status"] == "proposed" for r in validate_recommendations(proposals, ev))
    assert library.get(spec["skill_id"], version, scoped(spec), active_only=True)
    with pytest.raises(ValueError, match="unavailable"):
        validate_recommendations([{**proposals[0], "skill_ids": ["other-company"]}], ev)


def test_judgment_receives_explicit_totals_and_abstention_escalates(store, job, monkeypatch):
    from eas_harness.judgment import judge
    from langchain_core.messages import AIMessage

    seen = []

    class Model:
        def invoke(self, messages):
            seen.append(messages)
            context = json.loads(messages[1].content)
            assert context["comparison"] == {
                "company_id": "ACME",
                "invoice_id": "INV-1042",
                "po_id": "PO-1042",
                "invoice_amount": 97500,
                "purchase_order_amount": 90000,
                "difference": 7500,
                "units": "cents",
                "currency": "USD",
            }
            assert "transcript" not in messages[1].content
            return AIMessage(
                content=json.dumps(
                    {
                        "classification": "insufficient_evidence",
                        "explanation": "Synthetic abstention exercises escalation.",
                        "evidence_ids": [context["evidence_id"]],
                    }
                )
            )

    monkeypatch.setattr("eas_harness.judgment.model_for", lambda _: Model())
    comparison = dict(
        company_id="ACME", invoice_id="INV-1042", po_id="PO-1042", amount=90000, difference=7500
    )
    with pytest.raises(Recovery, match="abstained"):
        judge(
            SimpleNamespace(model_mode="live", model_id="test-stub", max_model_calls=2),
            store,
            job,
            comparison,
        )
    assert len(seen) == 1
    assert any(e["kind"] == "judgment_abstained" for e in store.events(job["id"]))


def test_judgment_approval_discloses_and_binds_the_exact_model_context(store, job):
    from eas_harness.judgment import judge
    from eas_harness.errors import Paused

    class Adapter:
        def observe(self):
            return Observation(revision="unchanged-screen", timestamp=1, screenshot="", state={})

    comparison = dict(
        company_id="ACME", invoice_id="INV-1042", po_id="PO-1042", amount=90000, difference=7500
    )
    store.update_job(job["id"], {"expected": comparison})
    layer = ExecutionLayer(store, Adapter())
    settings = SimpleNamespace(model_mode="simulated", model_id="", max_model_calls=5)

    def run():
        return layer.run(
            job["id"],
            "isolated-judgment",
            "judge",
            {"company_id": "ACME", "invoice_id": "INV-1042", "reason": ""},
            lambda _: judge(settings, store, store.get_job(job["id"]), store.get_job(job["id"])["expected"]),
        )

    with pytest.raises(Paused):
        run()
    approval = store.approvals(job["id"])[-1]
    assert approval["inputs"]["judgment"]["context"]["comparison"]["invoice_amount"] == 97500
    store.decide(approval["id"], {"decision": "approve"}, actor="simulated-staff")
    store.update_job(job["id"], {"expected": {**comparison, "difference": 8000}})
    with pytest.raises(Paused):
        run()
    assert not any(e["kind"] == "judgment_request" for e in store.events(job["id"]))
    assert store.approvals(job["id"])[-1]["status"] == "stale"
    with pytest.raises(Paused):
        run()
    fresh = store.approvals(job["id"])[-1]
    assert fresh["id"] != approval["id"] and fresh["status"] == "pending"
    store.decide(fresh["id"], {"decision": "approve"}, actor="simulated-staff")
    run()
    sent = next(e["data"] for e in store.events(job["id"]) if e["kind"] == "judgment_request")
    assert sent["context"] == fresh["inputs"]["judgment"]["context"]
    assert sent["prompt"] == fresh["inputs"]["judgment"]["prompt"]


def test_missing_capability_is_reviewed_in_background_without_a_chat_reporting_tool(
    store, tmp_path, monkeypatch
):
    from eas_harness.coordinator import Coordinator, SimulatedCoordinator
    from langgraph.checkpoint.memory import InMemorySaver
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from test_chat_records import NoDesktop

    j = store.create_job(
        JobInput(task="Export a supplier catalog using a missing integration").model_dump(), ongoing=True
    )
    store.claim("fixture-worker")

    def generate(self, messages, **kwargs):
        response = AIMessage(content="This workspace has no supplier export integration.")
        return ChatResult(generations=[ChatGeneration(message=response)])

    monkeypatch.setattr(SimulatedCoordinator, "_generate", generate)
    c = Coordinator(
        SimpleNamespace(
            data_dir=tmp_path, model_mode="simulated", model_provider="", model_id="", max_model_calls=3
        ),
        store,
        ExecutionLayer(store, NoDesktop()),
        InMemorySaver(),
        InMemorySaver(),
    )
    c.tick(store.get_job(j["id"]))
    assert store.get_job(j["id"])["status"] == "completed"
    assert store.approvals(j["id"]) == []
    queue = store.learning_status()["queue"]
    assert sum(q["kind"] == "chat_review" for q in queue) == 1
    calls = [e["data"] for e in store.events(j["id"]) if e["kind"] == "model_step"]
    assert all("report_capability_gap" not in call["available_tools"] for call in calls)
    assert not any(e["kind"] == "agent_tool_call" for e in store.events(j["id"]))


def test_supporting_file_read_has_its_own_approval(store, job, tmp_path, monkeypatch):
    from eas_harness.coordinator import Coordinator, SimulatedCoordinator
    from langgraph.checkpoint.memory import InMemorySaver
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from test_execution import FakeAdapter

    library = SkillLibrary(tmp_path)
    spec = {**guidance(), "application_version": job["app_version"]}
    version = library.install(spec)
    seen = []

    def generate(self, messages, **kwargs):
        results = [m for m in messages if isinstance(m, ToolMessage)]
        seen.append(results)
        if not results:
            name, args = "read_skill", {"skill_id": spec["skill_id"]}
        else:
            metadata = json.loads(results[-1].content)
            assert metadata["supporting_files"]["references/verification.md"].keys() == {"sha256"}
            name, args = (
                "read_skill_resource",
                {"skill_id": spec["skill_id"], "path": "references/verification.md"},
            )
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="", tool_calls=[{"id": f"read-{len(results)}", "name": name, "args": args}]
                    )
                )
            ]
        )

    monkeypatch.setattr(SimulatedCoordinator, "_generate", generate)
    c = Coordinator(
        SimpleNamespace(
            data_dir=tmp_path, model_mode="simulated", model_provider="", model_id="", max_model_calls=3
        ),
        store,
        ExecutionLayer(store, FakeAdapter()),
        InMemorySaver(),
        InMemorySaver(),
    )
    c.tick(store.get_job(job["id"]))
    a = store.approvals(job["id"])[0]
    assert a["name"] == "read_skill" and a["status"] == "pending"
    assert a["arguments"]["version"] == version
    store.decide(a["id"], {"decision": "approve"}, actor="simulated-staff")
    c.tick(store.get_job(job["id"]))
    pending = [a for a in store.approvals(job["id"]) if a["status"] == "pending"]
    assert len(pending) == 1 and pending[0]["name"] == "read_skill_resource"
    assert pending[0]["arguments"]["version"] == version
    assert not any(
        e["kind"] == "agent_tool_result" and e["data"]["name"] == "read_skill_resource"
        for e in store.events(job["id"])
    )
    store.decide(pending[0]["id"], {"decision": "reject"}, actor="simulated-staff")
    assert store.get_job(job["id"])["status"] == "rejected"
