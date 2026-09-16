"""Wire contracts only. Application interpretation belongs to the mediator."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class MediationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: Literal["demobooks-v1"] = "demobooks-v1"
    enabled: bool = True
    allow_drafts: bool = True
    # This profile always withholds bank details and unrecognized UI content.
    # Neither a learner nor the runtime can turn that rule off.


class MediationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=100)
    path: Literal["/observe", "/screenshot", "/window", "/activate", "/action"]
    target: str | None = Field(default=None, max_length=100)
    value: str | None = Field(default=None, max_length=4096)
    revision: str | None = Field(default=None, max_length=128)
    policy_revision: str | None = Field(default=None, max_length=128)
