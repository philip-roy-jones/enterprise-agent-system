"""Declarative, non-executable skill and workflow wire contracts."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillSpec(WireModel):
    skill_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=400)
    instructions: str = Field(min_length=1, max_length=12000)
    organization_id: str = "acme"
    department_id: str = "finance"
    role_id: str = "invoice_correction"
    company_id: str = "ACME"
    application_version: str
    capability_version: Literal["finance-1"] = "finance-1"
    task: str = Field(min_length=1, max_length=2000)
    steps: list[
        Literal[
            "validate", "establish", "compare", "judge", "report", "prepare", "save", "verify", "complete"
        ]
    ] = Field(default_factory=list, max_length=12)
    amount_labels: list[str] = Field(default_factory=lambda: ["Correction amount"], max_length=12)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    supporting_files: dict[str, str] = Field(default_factory=dict, max_length=10)

    @model_validator(mode="after")
    def bounded_supporting_files(self):
        import re

        if sum(len(text) for text in self.supporting_files.values()) > 24000:
            raise ValueError("Supporting files exceed the package text budget")
        for path, text in self.supporting_files.items():
            if not re.fullmatch(
                r"(?:references|templates|assets|tests)/[a-zA-Z0-9_-]+\.(?:md|json|txt)", path
            ):
                raise ValueError("Supporting files must be bounded text resources in the package")
            if not text.strip():
                raise ValueError("Supporting files cannot be empty")
        return self


class SkillRead(WireModel):
    skill_id: str
    version: str


class SkillSelection(WireModel):
    """Model selects a capability; the runtime binds its immutable version."""

    skill_id: str


class SkillResourceSelection(SkillSelection):
    path: str = Field(min_length=1, max_length=180)


class SkillResource(SkillRead):
    path: str = Field(min_length=1, max_length=180)


class LearningRecommendation(WireModel):
    kind: Literal["development_request", "consolidate", "retire", "suspend"]
    skill_ids: list[str] = Field(default_factory=list, max_length=5)
    reason: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)


class CapabilityGap(WireModel):
    capability: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)


class LearningProposal(WireModel):
    candidate: SkillSpec | None = None
    reason: str = Field(min_length=1, max_length=3000)
    recommendations: list[LearningRecommendation] = Field(default_factory=list, max_length=5)


class WorkflowCall(SkillRead):
    pass


class WorkflowResume(WireModel):
    run_id: str


class OperationCall(WireModel):
    operation: Literal[
        "validate",
        "establish",
        "compare",
        "judge",
        "report",
        "prepare",
        "save",
        "verify",
        "complete",
    ]


class ToolResult(WireModel):
    data: dict


class Judgment(WireModel):
    classification: Literal["matches", "discrepancy", "insufficient_evidence"]
    explanation: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(max_length=5)


class ComparisonEvidence(WireModel):
    company_id: str
    invoice_id: str
    po_id: str
    invoice_amount: int = Field(ge=0)
    purchase_order_amount: int = Field(ge=0)
    difference: int
    units: Literal["cents"] = "cents"
    currency: Literal["USD"] = "USD"

    @model_validator(mode="after")
    def consistent_totals(self):
        if self.invoice_amount - self.purchase_order_amount != self.difference:
            raise ValueError("Comparison arithmetic does not match the supplied totals")
        return self
