"""Trusted read-only Campaign Desk integration; learned packages contain no code."""

from dataclasses import replace
from decimal import Decimal, ROUND_HALF_UP
import time

import httpx

from eas_harness.contracts import Empty, Completed, Validated, Reviewed
from eas_harness.integrations.finance.operations import OPERATIONS as FINANCE, Operation
from eas_shared.marketing import CampaignSelection, CampaignOperation, CampaignRecord, CampaignReview
from eas_shared.skills import ToolResult
from eas_shared.identity import fingerprint
from eas_shared.types import Observation, Recovery

OPERATIONS = {
    name: replace(FINANCE[name], conditions="Authorized company, campaign and current observation")
    for name in (
        "read_skill",
        "read_skill_resource",
        "run_skill",
        "resume_skill",
        "ask_staff",
        "search_knowledge",
    )
}
for name, description, output in (
    ("validate", "Validate the authorized campaign and read permission", Validated),
    ("establish", "Read the selected campaign from Campaign Desk and verify its company", ToolResult),
    (
        "report",
        "Read current campaign metrics and calculate click-through rate and cost per click",
        ToolResult,
    ),
    ("complete", "Verify the reported campaign metrics against the current application record", Completed),
):
    OPERATIONS[name] = Operation(
        description,
        "A result bound to the selected campaign and current metrics",
        input_model=CampaignOperation,
        output_model=output,
        conditions="Authorized company and campaign; read-only application access",
    )
OPERATIONS["select_record"] = Operation(
    "Use the campaign identified in this conversation",
    "Bind this request to the disclosed campaign",
    desktop=False,
    input_model=CampaignSelection,
    output_model=ToolResult,
    conditions="Unbound conversational request; authorized company and Marketing role",
)
OPERATIONS["observe_app"] = Operation(
    "Read the selected campaign's current metrics from Campaign Desk",
    "Current synthetic campaign evidence",
    input_model=Empty,
    output_model=Observation,
    conditions="Authorized company and campaign",
)
OPERATIONS["review_discovery"] = Operation(
    "Review the assistant's answer against the requested outcome and campaign evidence",
    "Agent report only; human acceptance is recorded separately",
    input_model=CampaignReview,
    output_model=Reviewed,
    conditions="Recorded campaign evidence",
)


def campaign_metrics(record):
    record = CampaignRecord.model_validate(record).model_dump()
    if record["clicks"] > record["impressions"]:
        raise Recovery("ambiguous", "Campaign clicks exceed impressions; review the application data")

    def ratio(numerator, denominator):
        return (
            float((Decimal(numerator) / denominator).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            if denominator
            else None
        )

    return {
        **record,
        "click_through_percent": ratio(record["clicks"] * 100, record["impressions"]),
        "cost_per_click_cents": ratio(record["spend_cents"], record["clicks"]),
        "record_fingerprint": fingerprint(record),
        "synthetic": True,
    }


class CampaignAdapter:
    def __init__(self, settings, store):
        if not settings.campaign_token:
            raise ValueError("Campaign Desk application credential is required by the executor")
        self.client = httpx.Client(
            base_url=settings.campaign_url,
            headers={"Authorization": "Bearer " + settings.campaign_token},
            timeout=10,
            follow_redirects=False,
        )
        self.job = None
        self.fence = lambda: None

    def close(self):
        self.client.close()

    def observe(self):
        # Observation is a protected evidence capture for the pending approval.
        record_id = self.job.get("campaign_id")
        CampaignSelection(campaign_id=record_id)
        response = self.client.get("/campaigns/" + record_id)
        if response.status_code == 404:
            state = {
                "company_id": self.job["company_id"],
                "campaign_id": record_id,
                "exists": False,
                "synthetic": True,
                "source": "Campaign Desk scoped lookup",
            }
        else:
            response.raise_for_status()
            record = CampaignRecord.model_validate(response.json()).model_dump()
            if record["company_id"] != self.job["company_id"] or record["campaign_id"] != record_id:
                raise PermissionError("Campaign application returned an unauthorized record")
            state = {"record": record, "company_id": record["company_id"], "exists": True, "synthetic": True}
        return Observation(revision=fingerprint(state), timestamp=time.time(), screenshot="", state=state)


def operation(store, adapter, job, name, arguments):
    if name == "observe_app":
        return adapter.observe().model_dump()
    if name == "validate":
        CampaignOperation.model_validate(arguments)
        if job["role_id"] != "campaign_review" or set(job["permissions"]) != {"read"}:
            raise PermissionError("Unsupported Marketing scope")
        return {"validated": True}
    state = adapter.observe().state
    if not state["exists"]:
        raise Recovery(
            "record_unavailable", f"Campaign {job['campaign_id']} does not exist in the authorized company."
        )
    if name == "establish":
        return {"data": state["record"]}
    if name == "report":
        report = campaign_metrics(state["record"])
        store.update_job(job["id"], {"verified_report": report})
        return {"data": report}
    if name == "complete":
        if job.get("verified_report") != campaign_metrics(state["record"]):
            raise Recovery(
                "ambiguous", "Campaign metrics changed or no report exists; report again before completing"
            )
        return {"verified": True, "acceptance_required": True}
    raise PermissionError("Operation is not installed for Marketing")
