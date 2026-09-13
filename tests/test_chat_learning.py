"""Conversation reviewers and staff behavior are simulated explicitly."""

from types import SimpleNamespace
import pytest
from eas_shared.types import JobInput
from eas_shared.chat_learning import validate_signals
from eas_harness.skill_library import SkillLibrary
from eas_harness.chat_review import review
from eas_server.conversation import Conversation
from test_learning_feedback import guidance


def ended(store, task, conversation="continuous", staff="staff", **fields):
    job = store.create_job(
        JobInput(task=task, conversation_id=conversation).model_dump(), ongoing=True, staff_id=staff
    )
    store.update_job(job["id"], {"status": "completed", **fields})
    return store.get_job(job["id"])


def episode(store, job):
    with store.db() as db:
        return store.learning_episode(db, job["id"])


def test_chat_review_collects_ordinary_guidance_once_and_keeps_audience(store):
    old = ended(store, "Read the total")
    foreign = ended(store, "Private colleague conversation", staff="colleague")
    current = store.create_job(
        JobInput(task="Please use currency units", conversation_id="continuous").model_dump(), ongoing=True
    )
    Conversation(store).message(
        current["id"], {"message_id": "correction", "text": "Include the currency beside each amount."}
    )
    with store.db() as db:
        store.queue_chat_review(db, store._job(db, current["id"]))
    store.update_job(current["id"], {"status": "completed"})
    item = next(i for i in store.learning_status()["queue"] if i["job_id"] == current["id"])
    assert item["related_job_ids"] == [old["id"]]
    assert foreign["id"] not in item["related_job_ids"]
    assert len([i for i in store.learning_status()["queue"] if i["job_id"] == current["id"]]) == 1
    assert not store.approvals(current["id"])
    assert not store.get_job(current["id"])["accepted"]


def test_signal_requires_real_new_message_and_completed_scoped_operation(store):
    old = ended(store, "Read the total")
    current = ended(store, "That was the wrong total")
    ev, previous = episode(store, current), episode(store, old)
    signal = dict(
        kind="problem",
        message_id="request:" + current["id"],
        quote="wrong total",
        explanation="Staff reports an incorrect result",
        target_episode_id=old["id"],
    )
    assert validate_signals([signal], ev, [previous])
    for patch in [
        {"quote": "invented correction"},
        {"target_episode_id": "foreign"},
        {"invocation": "unfinished"},
        {"message_id": "request:" + old["id"]},
    ]:
        with pytest.raises(ValueError):
            validate_signals([{**signal, **patch}], ev, [previous])
    assert not store.get_job(old["id"])["accepted"]


def test_background_reviewer_can_record_missing_capability_without_foreground_note(
    store, tmp_path, monkeypatch
):
    current = ended(store, "Export the supplier catalog")

    def simulated(module, payload, **kwargs):
        assert "available_operations" in payload["evidence"]
        assert "export_supplier_catalog" not in payload["evidence"]["available_operations"]
        return dict(
            result={
                "signals": [],
                "candidate": None,
                "reason": "Simulated missing integration",
                "recommendations": [
                    dict(
                        kind="development_request",
                        skill_ids=[],
                        evidence_ids=[current["id"]],
                        reason="Supplier export is not installed",
                    )
                ],
            },
            usage={},
            prompt="Simulated reviewer",
            prompt_version="simulated-test",
        )

    monkeypatch.setattr("eas_harness.maintenance.subprocess_json", simulated)
    result = review(
        SimpleNamespace(model_mode="simulated", model_provider="", model_id=""),
        store,
        SkillLibrary(tmp_path),
        dict(episode=episode(store, current), related=[]),
    )
    assert result["status"] == "reviewed"
    assert result["recommendations"][0]["status"] == "proposed"
    assert not store.approvals(current["id"])
    assert not result["candidate"]


def test_chat_lesson_updates_text_without_form_or_execution_acceptance(store, tmp_path, monkeypatch):
    library = SkillLibrary(tmp_path)
    old = ended(store, "Inspect an invoice")
    spec = {**guidance(), "application_version": old["app_version"]}
    version = library.install(spec)
    current = ended(
        store,
        "When answering a total, always include its currency. Do not compare it to a purchase order unless I ask.",
    )
    signal = dict(
        kind="correction",
        message_id="request:" + current["id"],
        quote="always include its currency",
        explanation="Reusable output preference",
        target_episode_id=old["id"],
    )
    candidate = {
        **spec,
        "instructions": spec["instructions"] + " Include currency with totals. Compare only when requested.",
        "evidence_ids": spec["evidence_ids"] + [current["id"]],
    }

    def simulated(module, payload, **kwargs):
        if module.endswith("learner_process"):
            assert payload["evidence"]["history"][0]["episode_id"] == old["id"]
            return dict(
                result={"signals": [signal], "candidate": candidate, "reason": "Simulated staff correction"},
                usage={},
                prompt="Simulated reviewer",
                prompt_version="simulated-test",
            )
        from eas_harness.admission_process import check_candidate

        return check_candidate(payload)

    monkeypatch.setattr("eas_harness.maintenance.subprocess_json", simulated)
    item = dict(episode=episode(store, current), related=[episode(store, old)])
    settings = SimpleNamespace(model_mode="simulated", model_provider="", model_id="")
    result = review(settings, store, library, item)
    assert result["status"] == "activated" and result["version"] != version
    assert library.get(spec["skill_id"], result["version"], current)["steps"] == []
    assert not store.approvals(current["id"]) and not current["accepted"]
    scope = {"organization_id": "acme", "role_ids": ["invoice_correction"]}
    while claim := store.learning_claim("fixture", scope):
        store.learning_finish(
            claim["id"],
            claim["claim_id"],
            result if claim["job_id"] == current["id"] else {"status": "no_change"},
            scope,
        )
    events = store.events(current["id"])
    feedback = next(e["data"] for e in events if e["kind"] == "chat_feedback")
    assert feedback["attribution"] == "model_inferred_from_staff_chat"
    assert feedback["target_episode_id"] == old["id"]
    assert not any(e["kind"] in {"action_assessment", "accepted", "staff_decision"} for e in events)
    # A later chat proposal cannot add executable steps under text admission.
    candidate["steps"] = ["validate", "establish", "compare", "report", "complete"]
    with pytest.raises(ValueError, match="steps"):
        review(settings, store, library, item)
