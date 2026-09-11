"""Executable schemas for the shipped role, plus reusable adapter contracts."""

from functools import wraps
from inspect import signature
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .types import KnowledgeDocument, Observation


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Empty(Contract):
    pass


class NodeInputs(Contract):
    company_id: str = Field(min_length=1)
    invoice_id: str = Field(pattern=r"^INV-\d{4}$")
    reason: str = ""


class ReviewInputs(NodeInputs):
    assistant_report: str = Field(min_length=1)


class Company(Contract):
    company_id: str = Field(min_length=1)


class Invoice(Contract):
    invoice_id: str = Field(pattern=r"^INV-\d{4}$")


class FieldValue(Contract):
    field: Literal["amount", "note"]
    value: str = Field(max_length=4096, pattern=r"^[^\r\n]*$")


class ClickInputs(Contract):
    target: str | None = None
    x: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    y: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def target_or_point(self):
        if (self.x is None) != (self.y is None) or (not self.target and self.x is None):
            raise ValueError("Specify a target or both screen coordinates")
        return self


class Clicked(Contract):
    clicked: str


class DraftExpectation(Company, Invoice):
    amount: int = Field(ge=0)
    note: str
    po_id: str | None = None
    difference: int | None = None


class ExpectedResult(DraftExpectation):
    po_id: str
    difference: int


class SaveInputs(Contract):
    expected_result: DraftExpectation


class DraftResult(Company, Invoice):
    # Application adapters may retain additional evidence such as timestamps.
    model_config = ConfigDict(extra="allow", strict=True)
    id: str
    operation_id: str
    amount: int = Field(ge=0)
    note: str


class DraftFields(Contract):
    amount: str
    note: str


class InvoiceRecord(Company):
    model_config = ConfigDict(extra="allow", strict=True)
    id: str
    amount: int
    po_id: str
    po_amount: int


class AccountingView(Contract):
    model_config = ConfigDict(extra="allow", strict=True)
    company_id: str | None
    invoice_id: str | None
    view: str
    dialog: str | None
    fields: DraftFields
    invoices: list[InvoiceRecord]
    drafts: list[dict]


class Validated(Contract):
    validated: Literal[True]


class Prepared(Contract):
    prepared: Literal[True]


class Recovered(Contract):
    recovered: Literal[True]


class AssistanceAuthorized(Contract):
    supervised_assistance_authorized: Literal[True]


class ResumeResult(Contract):
    next_node: Literal["verify", "save", "establish"]
    reconciled: DraftResult | None = None
    prepared_by_assistance: bool = False


class Completed(Contract):
    verified: Literal[True]
    acceptance_required: Literal[True]


class Reviewed(Contract):
    staff_verified_outcome: str = Field(min_length=1)
    acceptance_required: Literal[True]


class KnowledgeQuery(Contract):
    query: str = Field(min_length=1, max_length=500)


class KnowledgeRecord(KnowledgeDocument):
    id: str
    revision: int = Field(ge=1)
    created_at: float


class KnowledgeResults(KnowledgeQuery):
    documents: list[KnowledgeRecord] = Field(max_length=3)


class StaffQuestion(Contract):
    question: str = Field(min_length=1, max_length=2000)


class QuestionResult(StaffQuestion):
    question_id: str
    status: Literal["pending", "answered"]
    created_at: float
    answer: str | None = None
    message_id: str | None = None


NODE_RESULTS = {
    "validate": Validated,
    "establish": Invoice,
    "compare": ExpectedResult,
    "prepare": Prepared,
    "save": DraftResult,
    "verify": DraftResult,
    "recover": Recovered,
    "assist": AssistanceAuthorized,
    "resume": ResumeResult,
    "complete": Completed,
    "review_discovery": Reviewed,
}
TOOL_CONTRACTS = {
    "observe_app": (Empty, Observation),
    "click": (ClickInputs, Clicked),
    "set_field": (FieldValue, FieldValue),
    "save_draft": (Empty, DraftResult),
    "search_knowledge": (KnowledgeQuery, KnowledgeResults),
    "ask_staff": (StaffQuestion, QuestionResult),
}


def adapter_contract(inputs, outputs):
    """Validate public adapter operation arguments and results, retaining dict APIs."""

    def decorate(function):
        parameters = signature(function)

        @wraps(function)
        def checked(self, *args, **kwargs):
            bound = parameters.bind(self, *args, **kwargs)
            values = {k: v for k, v in bound.arguments.items() if k != "self"}
            values = inputs.model_validate(values).model_dump()
            result = function(self, **values)
            return outputs.model_validate(result).model_dump(exclude_unset=True)

        return checked

    return decorate
