from typing import Any, Literal, TypedDict
from pydantic import BaseModel, Field

Mode = Literal["strict", "auto"]
TERMINAL = {"completed", "cancelled", "rejected", "denied", "failed"}


class JobInput(BaseModel):
    organization_id: str = "acme"
    department_id: str = "finance"
    role_id: str = "invoice_correction"
    inputs: dict[str, Any] = Field(default_factory=dict)
    company_id: str | None = None
    invoice_id: str | None = Field(default=None, pattern=r"^INV-\d{4}$")
    task: str | None = None
    selected_mode: Mode = "strict"
    permissions: list[str] | None = None


class Decision(BaseModel):
    decision: Literal["approve", "reject", "correct"]
    arguments: dict[str, Any] | None = None
    explanation: str = ""


class Observation(BaseModel):
    revision: str
    timestamp: float
    screenshot: str
    width: int = 1200
    height: int = 800
    state: dict[str, Any]
    targets: list[dict[str, Any]] = Field(default_factory=list)


class GraphState(TypedDict, total=False):
    job_id: str
    paused: bool
    turn: int
    next_node: str
    resume_node: str
    reason: str
    recovery_kind: str
    result: dict


class Recovery(Exception):
    def __init__(self, kind: str, reason: str):
        self.kind, self.reason = kind, reason
        super().__init__(reason)


class Paused(Exception):
    pass


class Stopped(Exception):
    pass


class Stale(Exception):
    pass
