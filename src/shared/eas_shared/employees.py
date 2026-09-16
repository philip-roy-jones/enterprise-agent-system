"""Bounded employee lifecycle and observation-only teaching contracts."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class EmployeeState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["shadowing", "active", "paused"]
    reason: str = Field(min_length=1, max_length=2000)


class Demonstration(BaseModel):
    channel_id: str | None = Field(default=None, pattern=r"^\d{1,22}$")
    model_config = ConfigDict(extra="forbid")
    role_id: str
    company_id: str
    task: str = Field(min_length=1, max_length=2000)


class MentorMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)


class ShadowNotes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation: str = Field(max_length=2000)
    question: str | None = Field(default=None, max_length=1000)
    lesson: str = Field(default="", max_length=4000)
