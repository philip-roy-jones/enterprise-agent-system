"""Staff assessments distinguish observed errors from unassessed actions."""

import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ActionAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    invocation: str = Field(min_length=1, max_length=300)
    outcome: Literal["correct", "incorrect"]
    explanation: str = Field(min_length=1, max_length=2000)


def assess_action(store, job_id, assessment):
    assessment = ActionAssessment.model_validate(assessment).model_dump()
    if not assessment["explanation"].strip():
        raise ValueError("Describe the observed result")
    with store.db() as db:
        job = store._job(db, job_id)
        kinds = {
            r[0]
            for r in db.execute(
                "SELECT kind FROM events WHERE job_id=? AND json_extract(data,'$.invocation')=? AND kind IN ('action_started','action_result')",
                (job_id, assessment["invocation"]),
            )
        }
        if kinds != {"action_started", "action_result"}:
            raise ValueError("Assessment requires a finished operation belonging to this job")
        previous = db.execute(
            "SELECT data FROM events WHERE job_id=? AND kind='action_assessment' AND json_extract(data,'$.invocation')=? ORDER BY seq DESC LIMIT 1",
            (job_id, assessment["invocation"]),
        ).fetchone()
        if not previous or json.loads(previous[0]) != assessment:
            store._event(db, job_id, "action_assessment", assessment)
        if assessment["outcome"] == "incorrect" and job.get("accepted"):
            job["accepted"] = False
            store._put(db, job)
            store._event(
                db, job_id, "acceptance_revoked", {"reason": "Staff reported an incorrect operation"}
            )
        return assessment


def assessment_metrics(events):
    started = {e["data"]["invocation"] for e in events if e["kind"] == "action_started"}
    finished = started & {e["data"]["invocation"] for e in events if e["kind"] == "action_result"}
    assessments = {
        e["data"]["invocation"]: e["data"]["outcome"]
        for e in events
        if e["kind"] == "action_assessment" and e["data"]["invocation"] in finished
    }
    return {
        "incorrect_actions_reported": sum(v == "incorrect" for v in assessments.values()),
        "assessed_actions": len(assessments),
        "unassessed_actions": len(finished - assessments.keys()),
    }
