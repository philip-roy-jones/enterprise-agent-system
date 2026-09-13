"""Approved screenshot capture and immutable, annotated chat attachments."""

import base64
import time
from eas_shared.screenshots import ScreenCapture, ShareScreenshot, captured_screen


def screen_tool(store, adapter, job_id, name, arguments):
    if name == "capture_screen":
        capture = getattr(adapter, "capture_screen", None)
        if capture is None:
            raise ValueError("This worker has no interactive desktop screenshot capability")
        raw = capture()
        png = base64.b64decode(raw["screenshot"], validate=True)
        if not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) > 5_000_000:
            raise ValueError("Screen capture must be a PNG below 5 MB")
        return ScreenCapture(
            screenshot=store.artifact(png),
            width=raw["width"],
            height=raw["height"],
            captured_at=time.time(),
            surface=raw["surface"],
        ).model_dump()
    args = ShareScreenshot.model_validate(arguments).model_dump()
    captured = (
        store.screenshot_metadata(job_id, args["screenshot"])
        if hasattr(type(store), "screenshot_metadata")
        else captured_screen(store.events(job_id), args["screenshot"])
    )
    return {"data": {**captured, **args}}


def model_image(store, job_id, screenshot):
    # RemoteStore implements an assignment-checked route. Local fixtures read
    # only the already-owned, validated artifact name.
    if hasattr(type(store), "screenshot_image"):
        png = store.screenshot_image(job_id, screenshot)
    else:
        captured_screen(store.events(job_id), screenshot)
        png = (store.root / "artifacts" / screenshot).read_bytes()
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
