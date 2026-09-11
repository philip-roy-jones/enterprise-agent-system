"""Adapter for our native Windows DemoBooks application, not real QuickBooks.

The edge worker reaches the application bridge over Windows loopback. It exposes
scoped application controls and real Windows screenshots; never arbitrary code.
"""

import base64
import time
import httpx
from .store import fingerprint, uid
from .types import Observation, Recovery, Stale


class WindowsBridge:
    def __init__(self, settings):
        if not settings.windows_token:
            raise ValueError("EAS_WINDOWS_TOKEN must match the VM's private bridge.token")
        self.client = httpx.Client(
            base_url=settings.windows_bridge_url,
            headers={"Authorization": f"Bearer {settings.windows_token}"},
            timeout=12,
        )

    def call(self, path, data=None):
        response = self.client.get(path) if data is None else self.client.post(path, json=data)
        if response.is_error:
            reason = response.json().get("error", "Windows bridge request failed")
            if response.status_code in {401, 403}:
                raise PermissionError(reason)
            if "revision" in reason.lower():
                raise Stale(reason)
            raise Recovery("unfamiliar", reason)
        return response.json()


class WindowsAdapter:
    def __init__(self, settings, store):
        self.store = store
        self.bridge = WindowsBridge(settings)
        self.bridge.call("/health")
        self.job = None
        self.fence = lambda: (_ for _ in ()).throw(PermissionError("No active operation"))

    def close(self):
        self.bridge.client.close()

    def correction_note(self, note):
        return note

    def read_state(self):
        return self.bridge.call("/state")

    def get_model_image(self):
        return getattr(self, "_model_image", None)

    def prepare_observation(self, job_id, owner, epoch):
        window = self.bridge.call("/window")
        if window["foreground"] and not window.get("minimized", False) and window.get("onscreen", True):
            return
        invocation = f"{job_id}:window:{uid()}"
        self.store.begin_window_recovery(job_id, owner, epoch, invocation)
        result = {"recovered": False}
        try:
            self.bridge.call("/activate", {})
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                self.store.check(job_id, owner, epoch)
                window = self.bridge.call("/window")
                if (
                    window["foreground"]
                    and not window.get("minimized", False)
                    and window.get("onscreen", True)
                ):
                    result = {"recovered": True, "application": "DemoBooks Desktop"}
                    return
                time.sleep(0.1)
            raise Recovery("temporary", "The assigned Windows application could not be activated")
        finally:
            self.store.finish_action(job_id, invocation, result, cache=False)

    def observe(self):
        raw = self.bridge.call("/observe")
        self._model_image = raw["screenshot"] if raw["foreground"] else None
        state = dict(raw["state"], foreground=raw["foreground"], desktop_session=raw["desktop_session"])
        shape = {"state": state, "targets": raw["targets"], "width": raw["width"], "height": raw["height"]}
        artifact = self.store.artifact(base64.b64decode(raw["screenshot"]))
        return Observation(
            revision=fingerprint(shape),
            timestamp=time.time(),
            screenshot=artifact,
            width=raw["width"],
            height=raw["height"],
            state=state,
            targets=raw["targets"],
        )

    def ready(self):
        deadline = time.monotonic() + 6
        while True:
            state = self.read_state()
            if state["loading_until"] <= time.time():
                break
            if time.monotonic() >= deadline:
                raise Recovery("temporary", "Windows accounting view is still loading")
            time.sleep(0.1)
        if state["dialog"]:
            raise Recovery(
                "known" if state["dialog"] == "info" else "unfamiliar", f"Visible {state['dialog']} dialog"
            )
        return state

    def _action(self, name, args):
        self.fence()
        state = self.read_state()
        return self.bridge.call(
            "/action",
            {
                "name": name,
                "args": args,
                "operation_id": self.job["id"],
                "invoice_id": self.job["invoice_id"],
                "revision": state["revision"],
            },
        )

    def click_target(self, target):
        return self._action("click", {"target": target})

    def ensure_company(self, company_id):
        state = self.ready()
        if state["company_id"] != company_id:
            self.click_target("company")
        if self.read_state()["company_id"] != company_id:
            raise PermissionError("Company identity mismatch")
        return {"company_id": company_id}

    def ensure_invoice_open(self, invoice_id):
        state = self.ready()
        if state["view"] != "invoice" or state["invoice_id"] != invoice_id:
            self.click_target("invoices")
            self.ready()
            self.click_target("open-" + invoice_id)
        if self.ready()["invoice_id"] != invoice_id:
            raise PermissionError("Invoice identity mismatch")
        return {"invoice_id": invoice_id}

    def ensure_editable(self):
        state = self.ready()
        if (
            state["company_id"] != self.job["company_id"]
            or state["invoice_id"] != self.job["invoice_id"]
            or state["view"] != "invoice"
        ):
            raise Recovery("unfamiliar", "Record identity changed; re-establish the scoped invoice")
        return state

    def set_field(self, field, value):
        self.ensure_editable()
        result = self._action("field", {"field": field, "value": str(value)})
        if result["fields"].get(field) != str(value):
            raise Recovery("unfamiliar", "Native draft field did not retain the approved value")
        return {"field": field, "value": str(value)}

    def saved_result(self, expected):
        state = self.read_state()
        draft = next((d for d in state["drafts"] if d["operation_id"] == self.job["id"]), None)
        if draft and any(draft[k] != expected[k] for k in ("company_id", "invoice_id", "amount")):
            raise Recovery("ambiguous", "Persisted native draft differs from expected business result")
        return draft

    def save_and_verify(self, expected_result):
        saved = self.saved_result(expected_result)
        if saved:
            return saved
        if self.job.get("mutation") == "attempted_uncertain":
            raise Recovery(
                "ambiguous",
                "An earlier Save has no verified result; staff must reconcile before another Save",
            )
        self.ensure_editable()
        try:
            result = self.click_target("save")
        except httpx.TimeoutException:
            raise Recovery(
                "ambiguous", "Native Save timed out; reconcile the persisted result before retrying"
            ) from None
        if result["dialog"]:
            raise Recovery(
                "ambiguous",
                "Native Save confirmation interrupted; inspect persistent results before another Save",
            )
        saved = self.saved_result(expected_result)
        if not saved:
            raise Recovery("ambiguous", "No native correction draft found after Save")
        return saved

    def tool_action(self, name, args):
        if name == "observe_app":
            return self.observe().model_dump()
        if name == "click":
            target = args.get("target")
            if args.get("x") is not None:
                obs = self.observe()
                matches = [
                    t
                    for t in obs.targets
                    if abs(float(args["x"]) - t["x"]) <= t["width"] / 2
                    and abs(float(args["y"]) - t["y"]) <= t["height"] / 2
                ]
                if not matches:
                    raise PermissionError("Correction is not an actionable native control")
                target = matches[-1]["target"]
            allowed = {
                "dialog-review",
                "dialog-keep",
                "dialog-discard",
                "dialog-acknowledge",
                "invoices",
                "company",
                "open-" + self.job["invoice_id"],
            }
            if target not in allowed:
                raise PermissionError("Native click outside assistance scope")
            self.click_target(target)
            return {"clicked": target}
        if name == "set_field":
            if args["field"] not in {"amount", "note"}:
                raise PermissionError("Native field outside correction draft scope")
            return self.set_field(args["field"], args["value"])
        if name == "save_draft":
            return self.save_and_verify(self.job["expected"])
        raise PermissionError("Unknown native tool")
