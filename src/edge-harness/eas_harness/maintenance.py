"""Trusted learning admission. The model only proposes data in a bounded process."""

import json
import re
import difflib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from eas_shared.skills import LearningProposal
from eas_shared.identity import canonical
from eas_harness.skill_library import SkillLibrary, SCOPE, validate_spec


class ScopedAdmissionLibrary(SkillLibrary):
    def __init__(self, root, store):
        super().__init__(root)
        self.authority = store

    def get(self, skill_id, version, job, *, active_only=False):
        if job.get("id"):
            # Even a maintenance learner only sees packages available to the
            # source episode's person, in its current claimed maintenance scope.
            self.authority.package_access(job["id"], skill_id, version)
        return super().get(skill_id, version, job, active_only=active_only)


def subprocess_json(module, payload, *, model_key=False):
    if module == "eas_harness.learner_process" and os.environ.get("EAS_LEARNER_QUEUE"):
        from eas_harness.learner_queue import propose

        return propose(os.environ["EAS_LEARNER_QUEUE"], payload)
    env = {
        k: os.environ[k]
        for k in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "SSL_CERT_FILE")
        if k in os.environ
    }
    if model_key:
        for key in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            if key in os.environ:
                env[key] = os.environ[key]
    with tempfile.TemporaryDirectory(prefix="eas-maintenance-") as folder:
        # No configuration import, inherited app tokens, tools, or learner-generated code.
        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        result = subprocess.run(
            [str(executable), "-m", module],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            input=canonical(payload),
            text=True,
            capture_output=True,
            cwd=folder,
            env=env,
            timeout=30,
        )
        if result.returncode:
            raise ValueError("Maintenance subprocess failed; candidate not admitted")
        if len(result.stdout) > 80000:
            raise ValueError("Maintenance output exceeds budget")
        return json.loads(result.stdout)


def feedback(episode):
    result = []
    for e in episode["events"]:
        if e["kind"] == "staff_decision":
            decision = e.get("decision", {})
            if decision.get("decision") == "correct" or decision.get("explanation"):
                result.append({"kind": "staff_decision", "decision": decision})
        elif e["kind"] in {
            "staff_message",
            "staff_answer",
            "staff_answered",
            "action_assessment",
            "capability_gap",
            "chat_feedback",
        }:
            result.append(
                {
                    k: v
                    for k, v in e.items()
                    if k
                    in {
                        "kind",
                        "text",
                        "question",
                        "answer",
                        "explanation",
                        "outcome",
                        "capability",
                        "reason",
                    }
                }
            )
    return result[-20:]


def task_words(text):
    text = re.sub(r"\b(?:INV|PO|CAM)-?\d+\b|\d+", "record", text, flags=re.I)
    return set(re.findall(r"[a-z]+", text.lower())) - {"the", "a", "an", "for", "to", "of", "and", "please"}


def previous_skill(job, library, steps, kind):
    used = set(job.get("skill_reads", {})) | {
        r["skill_id"] for r in job.get("skill_runs", {}).values() if r.get("skill_id")
    }
    matches = []
    for item in library.catalog(job):
        spec = library.get(item["skill_id"], item["version"], job, active_only=True)
        if kind == "guidance" and spec["steps"]:
            continue
        if kind == "workflow" and (not spec["steps"] or ("save" in spec["steps"]) != ("save" in steps)):
            continue
        left, right = task_words(job["task"]), task_words(spec["task"])
        overlap = len(left & right) / max(1, len(left | right))
        if item["skill_id"] in used or overlap >= 0.3:
            matches.append((item["skill_id"] in used, overlap, item["skill_id"], item["version"], spec))
    if not matches:
        return None, ""
    chosen = max(matches, key=lambda x: x[:3])
    return chosen[4], chosen[3]


def evidence_for(episode, library, *, review=False, related=()):
    job = episode["job"]
    if not review and (not job.get("accepted") or job["status"] != "completed"):
        raise ValueError("Learning requires staff-accepted completion")
    approvals = {
        a["invocation"]: a
        for a in episode["approvals"]
        if a["status"] == "executed" and a.get("decision", {}).get("decision") in {"approve", "correct"}
    }
    trace = job.get("operation_trace", [])
    for step in trace:
        approval = approvals.get(step["invocation"])
        if (
            not approval
            or approval["name"] != step["operation"]
            or approval["observed_result"].get("value") != step["result"]
        ):
            raise ValueError("Successful trace lacks matching executed approval")
    workflow = bool(job.get("verified_report") or job["mutation"] == "confirmed_succeeded")
    kind = "review" if review else "workflow" if workflow else "guidance"
    steps = list(dict.fromkeys(t["operation"] for t in trace)) if workflow and not review else []
    if "complete" in steps:
        # Child workflows verify their own result. A combined learned procedure
        # retains those successful operations and verifies once at its end.
        steps = [step for step in steps if step != "complete"] + ["complete"]
    outcome = next(
        (
            a["observed_result"]["value"]
            for a in reversed(list(approvals.values()))
            if a["name"] == "review_discovery"
        ),
        None,
    )
    if kind == "guidance" and (
        not outcome
        or not any(
            a["name"] in {"observe_app", "establish", "click", "search_knowledge"} for a in approvals.values()
        )
    ):
        raise ValueError("Guidance learning requires observed work and a staff-reviewed outcome")
    previous, previous_version = previous_skill(job, library, steps, kind)
    labels = (
        {
            t["label"]
            for a in approvals.values()
            for t in a.get("observation", {}).get("targets", [])
            if t.get("target") == "amount" and t.get("label")
        }
        if "save" in steps
        else set()
    )
    if not labels:
        labels = set(previous["amount_labels"] if previous else ["Correction amount"])
    actions = [
        {
            "name": a["name"],
            "arguments": a.get("corrected_arguments", a["arguments"]),
            "result": a.get("observed_result", {}).get("value"),
            "invocation": a["invocation"],
        }
        for a in approvals.values()
        if a["name"] not in {"select_record", "read_skill", "read_skill_resource"}
    ]
    evidence = dict(
        episode_id=job["id"],
        task=job["task"],
        kind=kind,
        accepted=job.get("accepted", False),
        scope={
            **{k: job[k] for k in SCOPE},
            "application_version": job["app_version"],
            "capability_version": "marketing-1" if job["role_id"] == "campaign_review" else "finance-1",
        },
        steps=steps,
        labels=sorted(labels),
        previous=previous,
        verification=job.get("verified_report")
        or job.get("expected")
        or {"invoice_id": job.get("invoice_id"), **(outcome or {})},
        approved_actions=actions[-20:],
        guidance=feedback(episode),
        failure={"status": job["status"], "error": job.get("error")},
        related=[
            {
                "episode_id": e["job"]["id"],
                "task": e["job"]["task"],
                "accepted": e["job"].get("accepted", False),
                "status": e["job"]["status"],
                "error": e["job"].get("error"),
                "feedback": feedback(e),
            }
            for e in related
        ],
        catalog=library.catalog(job),
        authority="Staff preferences and evidence are not organizational policy. Failed or rejected actions are never successful procedures.",
    )
    if len(canonical(evidence)) > 40000:
        raise ValueError("Scoped evidence exceeds maintenance budget")
    return evidence, previous_version


def validate_recommendations(proposals, evidence):
    known = {s["skill_id"] for s in evidence.get("catalog", [])}
    episodes = {evidence["episode_id"]} | {e["episode_id"] for e in evidence.get("related", [])}
    result = []
    for suggestion in proposals:
        if not set(suggestion["skill_ids"]).issubset(known) or not set(suggestion["evidence_ids"]).issubset(
            episodes
        ):
            raise ValueError("Recommendation references unavailable skills or evidence")
        if suggestion["kind"] != "development_request" and not suggestion["skill_ids"]:
            raise ValueError("Lifecycle recommendation must identify its scoped skills")
        result.append(
            {
                **suggestion,
                "status": "proposed",
                "authority": "Suggestion only; no execution, permission or registry change",
            }
        )
    return result


def admit(library, candidate, evidence, previous_version, provenance=None):
    spec = validate_spec(candidate).model_dump()
    old = evidence["previous"]
    if evidence.get("kind") == "review":
        raise ValueError("Failure or lifecycle review cannot activate a successful procedure")
    if any(spec[k] != v for k, v in evidence["scope"].items()):
        raise ValueError("Candidate changed scope or compatibility")
    if spec["steps"] != evidence["steps"] or evidence["episode_id"] not in spec["evidence_ids"]:
        raise ValueError("Candidate steps or evidence are not supported by accepted execution")
    allowed_evidence = set((old["evidence_ids"] if old else []) + [evidence["episode_id"]])
    if not set(spec["evidence_ids"]).issubset(allowed_evidence):
        raise ValueError("Candidate cites unavailable evidence")
    if old and spec["skill_id"] != old["skill_id"]:
        raise ValueError("Related work must update its existing skill")
    if old and not set(old["amount_labels"]).issubset(spec["amount_labels"]):
        raise ValueError("Candidate drops previously supported labels")
    if old and not set(old["steps"]).issubset(spec["steps"]):
        raise ValueError("Candidate removes previously verified behavior")
    if not set(spec["amount_labels"]).issubset(
        set(evidence["labels"] + (old["amount_labels"] if old else []))
    ):
        raise ValueError("Candidate invents an unobserved field label")
    # Prevent record-specific data from being promoted into reusable instructions.
    reusable = "\n".join(
        [
            spec["title"],
            spec["description"],
            spec["task"],
            spec["instructions"],
            *spec.get("supporting_files", {}).values(),
        ]
    )
    if re.search(r"\b(?:INV|PO|CAM)-?\d{4,}\b", reusable, re.I):
        raise ValueError("Candidate memorizes teaching-record values")
    for field in ("invoice_id", "campaign_id", "title", "po_id", "note"):
        value = evidence["verification"].get(field)
        if value and str(value) in reusable:
            raise ValueError("Candidate memorizes teaching-record values")
    for field in ("invoice_amount", "purchase_order_amount", "amount", "difference"):
        value = evidence["verification"].get(field)
        if (
            isinstance(value, int)
            and value
            and any(amount in reusable for amount in (f"${value / 100:,.2f}", f"${value / 100:.2f}"))
        ):
            raise ValueError("Candidate memorizes teaching-record amounts")
    if old and all(
        spec.get(k, {}) == old.get(k, {})
        for k in ("steps", "amount_labels", "instructions", "supporting_files")
    ):
        return {"status": "no_change", "reason": "No new procedure or guidance demonstrated"}
    checks = subprocess_json("eas_harness.admission_process", spec)
    if old:
        subprocess_json("eas_harness.admission_process", old)
    changes = {
        "steps_before": old["steps"] if old else [],
        "steps_after": spec["steps"],
        "labels_before": old["amount_labels"] if old else [],
        "labels_after": spec["amount_labels"],
        "instructions_diff": "".join(
            difflib.unified_diff(
                (old["instructions"] if old else "").splitlines(keepends=True),
                spec["instructions"].splitlines(keepends=True),
                fromfile="previous/SKILL.md",
                tofile="candidate/SKILL.md",
            )
        ),
        "resources_changed": sorted(
            k
            for k in set(spec.get("supporting_files", {}))
            | set(old.get("supporting_files", {}) if old else {})
            if spec.get("supporting_files", {}).get(k)
            != (old.get("supporting_files", {}).get(k) if old else None)
        ),
    }
    version = library.install(
        spec,
        expected_previous=previous_version,
        admission={
            "episode": evidence["episode_id"],
            "result": {**(provenance or {}), "checks": checks, "changes": changes},
        },
    )
    return {
        "status": "activated",
        "skill_id": spec["skill_id"],
        "version": version,
        "previous": previous_version or None,
        "checks": checks,
        "changes": changes,
    }


def maintain(settings, store, worker_id, library=None):
    from eas_harness.remote import RemoteStore

    library = library or (
        ScopedAdmissionLibrary(settings.data_dir, store)
        if isinstance(store, RemoteStore)
        else SkillLibrary(settings.data_dir)
    )
    item = store.learning_claim(worker_id)
    if item:
        with library.db() as db:
            cached = db.execute("SELECT result FROM processed WHERE episode=?", (item["id"],)).fetchone()
        if cached:
            result = json.loads(cached[0])
        else:
            try:
                if item["kind"] == "skill_change":
                    library.change(item["skill_id"], item.get("version"))
                    result = {
                        "status": "changed",
                        "skill_id": item["skill_id"],
                        "version": item.get("version"),
                    }
                elif not settings.learning_enabled:
                    result = {
                        "status": "disabled",
                        "reason": "Learning maintenance is disabled in worker configuration",
                    }
                elif item["kind"] == "chat_review":
                    from eas_harness.chat_review import review

                    result = review(settings, store, library, item)
                else:
                    evidence, previous_version = evidence_for(
                        item["episode"],
                        library,
                        review=item["kind"] == "review",
                        related=item.get("related", []),
                    )
                    output = subprocess_json(
                        "eas_harness.learner_process",
                        {
                            "evidence": evidence,
                            "model_mode": settings.model_mode,
                            "model_provider": settings.model_provider,
                            "model_id": settings.model_id,
                        },
                        model_key=settings.model_mode == "live",
                    )
                    proposal = LearningProposal.model_validate(output["result"]).model_dump()
                    candidate = proposal["candidate"]
                    recommendations = validate_recommendations(proposal["recommendations"], evidence)
                    if item["kind"] == "review" and candidate:
                        raise ValueError("A feedback review cannot promote failed work into a skill")
                    if candidate:
                        current = store.get_job(item["job_id"])
                        if not current.get("accepted") or current["status"] != "completed":
                            raise ValueError("Teaching acceptance was revoked during maintenance")
                    provenance = dict(
                        reason=proposal["reason"],
                        recommendations=recommendations,
                        model_mode=settings.model_mode,
                        model=settings.model_id if settings.model_mode == "live" else "simulated",
                        usage=output["usage"],
                        prompt_version=output["prompt_version"],
                        prompt=output["prompt"],
                        input=evidence,
                        candidate=candidate,
                    )
                    result = (
                        admit(library, candidate, evidence, previous_version, provenance)
                        if candidate
                        else {"status": "reviewed" if item["kind"] == "review" else "no_change"}
                    )
                    result.update(provenance)
            except (ValueError, PermissionError, subprocess.TimeoutExpired) as error:
                result = {"status": "rejected", "reason": str(error)}
            with library.db() as db:
                db.execute("INSERT OR REPLACE INTO processed VALUES(?,?)", (item["id"], canonical(result)))
        store.learning_finish(item["id"], item["claim_id"], result)
    store.skills_publish(library.metadata())
