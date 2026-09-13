"""Screenshot attachments use bounded shapes, never model-generated HTML or drawing code."""

from typing import Literal
from pydantic import Field, model_validator
from eas_shared.skills import WireModel


class ScreenCapture(WireModel):
    screenshot: str = Field(pattern=r"^[a-zA-Z0-9_-]+\.png$")
    width: int = Field(gt=0, le=20000)
    height: int = Field(gt=0, le=20000)
    captured_at: float
    surface: Literal["desktop", "browser_fixture"]


class Annotation(WireModel):
    kind: Literal["rectangle", "arrow", "circle", "text"]
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    x2: float | None = Field(default=None, ge=0, le=1)
    y2: float | None = Field(default=None, ge=0, le=1)
    label: str = Field(default="", max_length=160)
    color: Literal["red", "blue", "yellow"] = "red"

    @model_validator(mode="after")
    def complete_shape(self):
        if self.kind != "text" and (self.x2 is None or self.y2 is None):
            raise ValueError("Shapes need both normalized endpoints")
        if self.kind == "text" and not self.label.strip():
            raise ValueError("Text annotations need a label")
        return self


class ShareScreenshot(WireModel):
    screenshot: str = Field(pattern=r"^[a-zA-Z0-9_-]+\.png$")
    caption: str = Field(min_length=1, max_length=2000)
    annotations: list[Annotation] = Field(default_factory=list, max_length=12)


def captured_screen(events, name):
    starts = {
        e["data"]["invocation"]
        for e in events
        if e["kind"] == "action_started" and e["data"].get("action", {}).get("name") == "capture_screen"
    }
    for event in events:
        if event["kind"] != "action_result" or event["data"].get("invocation") not in starts:
            continue
        value = event["data"].get("result", {}).get("value", {})
        if value.get("screenshot") == name:
            return ScreenCapture.model_validate(value).model_dump()
    raise PermissionError("Screenshot requires a completed capture in this request")
