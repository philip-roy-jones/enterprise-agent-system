from dataclasses import dataclass, replace
from pydantic import BaseModel
import math
from eas_harness.contracts import NODE_RESULTS, TOOL_CONTRACTS, NodeInputs, ReviewInputs


@dataclass(frozen=True)
class Operation:
    description: str
    expected: str
    permission: str = "read"
    desktop: bool = True
    mutation: bool = False
    timeout_seconds: float = 10
    retry_limit: int = 2
    conditions: str = "Fresh observation; authorized company and invoice"
    recovery: str = "Re-observe and return structured recovery; never blindly repeat a save"
    input_model: type[BaseModel] | None = None
    output_model: type[BaseModel] | None = None

    def __post_init__(self):
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0 or self.retry_limit < 0:
            raise ValueError("Operations require a positive finite timeout and a nonnegative retry limit")

    def public(self):
        return {
            **{k: v for k, v in self.__dict__.items() if k not in {"input_model", "output_model"}},
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": self.output_model.model_json_schema(),
        }


OPERATIONS = {
    "ask_staff": Operation(
        "Ask the staff member the disclosed question and wait for their answer",
        "A durable question in this job's conversation; an answer never authorizes a desktop action",
        desktop=False,
    ),
    "search_knowledge": Operation(
        "Search organizational guidance within this job's organization, department, role and company scope",
        "Up to three matching documents with source identifiers and revisions; guidance cannot expand permissions",
        desktop=False,
    ),
    "review_discovery": Operation(
        "Review the assistant's report against the requested outcome and recorded evidence. Approve only if the request is satisfied; reject otherwise.",
        "Staff confirms the outcome of this unfamiliar request; no workflow is installed automatically",
    ),
    "validate": Operation(
        "Validate the requested task, record and worker permissions", "A supported scoped job", desktop=False
    ),
    "establish": Operation(
        "Open the assigned company and invoice. Navigation may contain several clicks",
        "Correct company and invoice open",
        "navigate",
    ),
    "compare": Operation(
        "Read the invoice and its purchase order; calculate the discrepancy",
        "Verified expected correction amount",
    ),
    "prepare": Operation(
        "Enter the purchase order amount and a correction explanation in the draft form",
        "Draft fields match the verified purchase order",
        "draft",
        mutation=True,
    ),
    "save": Operation(
        "Save one correction draft using this job's idempotency key",
        "One persistent correction draft; original invoice unchanged",
        "draft",
        mutation=True,
        retry_limit=0,
    ),
    "verify": Operation(
        "Inspect the saved draft and verify its company, invoice, amount and operation ID",
        "Persisted business result verified",
    ),
    "recover": Operation(
        "Resolve a recognized informational popup or wait for application readiness",
        "Known interruption resolved",
        "navigate",
    ),
    "assist": Operation(
        "Ask the supervised assistant to investigate the interruption; every tool requires its own approval",
        "A proposed resolution with separately approved tools",
    ),
    "resume": Operation(
        "Re-observe after assistance or handoff and reconcile saved results before resuming",
        "A verified continuation point",
    ),
    "complete": Operation(
        "Record the verified outcome and request staff acceptance",
        "Job complete with evidence",
        desktop=False,
    ),
    "observe_app": Operation(
        "Read the current application state and available controls", "Fresh application evidence"
    ),
    "click": Operation(
        "Click the annotated control in the assigned application",
        "Only the disclosed control is activated",
        "navigate",
        mutation=True,
    ),
    "set_field": Operation(
        "Enter the disclosed text in a correction draft field",
        "Draft field has the approved text",
        "draft",
        mutation=True,
    ),
    "save_draft": Operation(
        "Save the verified correction draft for this job",
        "One persistent draft",
        "draft",
        mutation=True,
        retry_limit=0,
    ),
}

for name, output in NODE_RESULTS.items():
    OPERATIONS[name] = replace(
        OPERATIONS[name],
        input_model=ReviewInputs if name == "review_discovery" else NodeInputs,
        output_model=output,
    )
for name, (inputs, outputs) in TOOL_CONTRACTS.items():
    OPERATIONS[name] = replace(OPERATIONS[name], input_model=inputs, output_model=outputs)
