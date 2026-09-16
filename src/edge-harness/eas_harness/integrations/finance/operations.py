from eas_shared.skills import SkillRead, SkillResource, SkillRun, SkillResume, ToolResult
from dataclasses import dataclass, replace
from pydantic import BaseModel
import math
from eas_harness.contracts import NODE_RESULTS, TOOL_CONTRACTS, NodeInputs, ReviewInputs, Invoice
from eas_harness.contracts import Empty
from eas_shared.screenshots import ScreenCapture, ShareScreenshot


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
    "capture_screen": Operation(
        "Capture the entire interactive desktop, including other visible windows, for this conversation",
        "A timestamped screenshot of all monitors; browser fixtures capture only their test viewport",
        input_model=Empty,
        output_model=ScreenCapture,
        conditions="Server-authorized read of the assigned worker desktop; no record required",
    ),
    "share_screenshot": Operation(
        "Send the disclosed screenshot, caption and annotations to this staff conversation",
        "An immutable chat attachment; annotations describe the capture, not current application state",
        desktop=False,
        input_model=ShareScreenshot,
        output_model=ToolResult,
        conditions="Previously authorized capture in this request; same staff conversation",
    ),
    "select_record": Operation(
        "Use the disclosed invoice for the work requested in this conversation",
        "The request is bound to this invoice; application actions each require server authorization",
        desktop=False,
        conditions="Unbound conversational request; authorized company and role",
        input_model=Invoice,
        output_model=ToolResult,
    ),
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
        "Ask the assistant to investigate the interruption; every tool requires current authority",
        "A proposed resolution with separately authorized tools",
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
        "Draft field has the validated text",
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

# Agent-led orchestration uses the same authority and typed result contracts.
for name, schema, description in [
    ("read_skill", SkillRead, "Read the disclosed version of a skill within this job's scope"),
    (
        "read_skill_resource",
        SkillResource,
        "Read the disclosed supporting file from this exact skill version",
    ),
    (
        "run_skill",
        SkillRun,
        "Start this versioned workflow; each internal operation needs separate authorization",
    ),
    (
        "resume_skill",
        SkillResume,
        "Resume this suspended workflow after rechecking current application state",
    ),
]:
    OPERATIONS[name] = Operation(
        description,
        "Only this invocation and scope are authorized",
        desktop=False,
        input_model=schema,
        output_model=ToolResult,
    )
for name, description in [
    ("judge", "Classify the verified comparison in an isolated model context"),
    ("report", "Verify and report the current invoice and purchase-order discrepancy without saving"),
]:
    OPERATIONS[name] = Operation(
        description,
        "A result bound to current comparison evidence",
        desktop=name == "report",
        input_model=NodeInputs,
        output_model=ToolResult,
        timeout_seconds=45 if name == "judge" else 10,
    )
