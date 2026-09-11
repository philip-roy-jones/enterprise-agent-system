"""Browser adapter. Only ExecutionLayer grants action-time fencing callbacks."""

from typing import Protocol
import base64
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout, Error as PlaywrightError
from enterprise.shared.identity import fingerprint
from enterprise.shared.types import Observation, Recovery, MutationRejected
from enterprise.shared.contracts import (
    adapter_contract,
    Empty,
    Company,
    Invoice,
    AccountingView,
    FieldValue,
    SaveInputs,
    DraftResult,
)


class DesktopAdapter(Protocol):
    def prepare_observation(self, job_id, owner, epoch) -> None: ...
    def observe(self) -> Observation: ...
    def ensure_company(self, company_id: str) -> dict: ...
    def ensure_invoice_open(self, invoice_id: str) -> dict: ...
    def ensure_editable(self) -> dict: ...
    def set_field(self, field: str, value: str) -> dict: ...
    def save_and_verify(self, expected_result: dict) -> dict: ...


class NativeWindowsAdapter:
    """Extension point only. No QuickBooks or native desktop support is claimed."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("Inspect and test the actual Windows application interfaces first")


class BrowserAdapter:
    def __init__(self, settings, store):
        self.store = store
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=settings.headless)
        self.context = self.browser.new_context(
            viewport={"width": 1200, "height": 800},
            extra_http_headers={"Authorization": f"Bearer {settings.worker_token}"},
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(6000)
        self.page.goto(settings.backend_url + "/mock")
        self.page.wait_for_function("window.appState !== undefined")
        self.fence = lambda: (_ for _ in ()).throw(PermissionError("No execution authority"))
        self.job = None
        self.deadline = None

    def timeout_ms(self):
        return max(1, int(self.deadline.remaining(6) * 1000)) if self.deadline else 6000

    def close(self):
        self.browser.close()
        self.playwright.stop()

    def correction_note(self, note):
        return note

    def get_model_image(self):
        return getattr(self, "_model_image", None)

    def prepare_observation(self, job_id, owner, epoch):
        # This adapter owns a dedicated browser page, independent of OS focus.
        return None

    def observe(self):
        try:
            self.page.evaluate("timeout => sync(timeout, true)", self.timeout_ms())
        except PlaywrightError as error:
            raise Recovery(
                "temporary", "A fresh accounting observation is unavailable; wait and re-observe"
            ) from error
        state = self.page.evaluate("window.appState")
        targets = self.page.locator("[data-target]").evaluate_all(
            """els => els.filter(e => e.getBoundingClientRect().width && !e.closest('#app')?.hidden).map(e => {const r=e.getBoundingClientRect();return {target:e.dataset.target,label:e.getAttribute('aria-label')||e.innerText,x:r.x+r.width/2,y:r.y+r.height/2,width:r.width,height:r.height}})"""
        )
        png = self.page.screenshot(timeout=self.timeout_ms())
        self._model_image = base64.b64encode(png).decode("ascii")
        screenshot = self.store.artifact(png) if hasattr(self.store, "artifact") else "test.png"
        shape = {"state": state, "targets": targets, "width": 1200, "height": 800}
        return Observation(
            revision=fingerprint(shape),
            timestamp=time.time(),
            screenshot=screenshot,
            state=state,
            targets=targets,
        )

    def ready(self):
        try:
            self.page.wait_for_function("window.appReady && !window.busy", timeout=self.timeout_ms())
        except PlaywrightTimeout:
            raise Recovery("temporary", "Accounting view is still loading") from None
        state = self.page.evaluate("window.appState")
        if state["dialog"]:
            kind = "known" if state["dialog"] == "info" else "unfamiliar"
            raise Recovery(kind, f"Visible {state['dialog']} dialog")
        return state

    def click_target(self, target):
        self.fence()
        self.page.locator(f'[data-target="{target}"]').click(timeout=self.timeout_ms())
        self.page.wait_for_function("!window.busy", timeout=self.timeout_ms())
        if self.page.evaluate("window.lastError || null"):
            error = self.page.evaluate("window.lastError")
            self.page.evaluate("window.lastError=null")
            raise Recovery("unfamiliar", error)
        return self.page.evaluate("window.appState")

    @adapter_contract(Company, Company)
    def ensure_company(self, company_id):
        state = self.ready()
        if state["company_id"] != company_id:
            self.click_target("company")
        if self.page.evaluate("window.appState.company_id") != company_id:
            raise PermissionError("Company identity mismatch")
        return {"company_id": company_id}

    @adapter_contract(Invoice, Invoice)
    def ensure_invoice_open(self, invoice_id):
        state = self.ready()
        if state["invoice_id"] != invoice_id or state["view"] != "invoice":
            self.click_target("invoices")
            self.ready()
            self.click_target(f"open-{invoice_id}")
        state = self.ready()
        if state["invoice_id"] != invoice_id:
            raise PermissionError("Invoice identity mismatch")
        return {"invoice_id": invoice_id}

    @adapter_contract(Empty, AccountingView)
    def ensure_editable(self):
        state = self.ready()
        if (
            state["company_id"] != self.job["company_id"]
            or state["invoice_id"] != self.job["invoice_id"]
            or state["view"] != "invoice"
        ):
            raise Recovery("unfamiliar", "Record identity changed; re-establish the scoped invoice")
        return state

    @adapter_contract(FieldValue, FieldValue)
    def set_field(self, field, value):
        self.ensure_editable()
        self.fence()
        locator = self.page.locator(f'[data-target="{field}"]')
        locator.fill(value, timeout=self.timeout_ms())
        self.fence()
        locator.press("Tab", timeout=self.timeout_ms())
        self.page.wait_for_function("!window.busy", timeout=self.timeout_ms())
        state = self.page.evaluate("window.appState")
        if state["fields"].get(field) != str(value):
            raise Recovery("unfamiliar", "Field value did not persist in the draft form")
        return {"field": field, "value": str(value)}

    def saved_result(self, expected):
        state = self.page.evaluate("window.appState")
        draft = next((d for d in state["drafts"] if d["operation_id"] == self.job["id"]), None)
        if draft and any(draft[k] != expected[k] for k in ("company_id", "invoice_id", "amount")):
            raise Recovery("ambiguous", "Existing draft does not match expected result")
        return draft

    @adapter_contract(SaveInputs, DraftResult)
    def save_and_verify(self, expected_result):
        existing = self.saved_result(expected_result)
        if existing:
            return existing
        if self.job.get("mutation") == "attempted_uncertain":
            raise Recovery(
                "ambiguous",
                "An earlier Save has no verified result; staff must reconcile before another Save",
            )
        self.ensure_editable()
        try:
            self.click_target("save")
        except PlaywrightTimeout:
            raise Recovery(
                "ambiguous", "Save timed out; reconcile the persisted result before retrying"
            ) from None
        if self.page.evaluate("window.appState.dialog"):
            raise Recovery(
                "ambiguous", "Save confirmation interrupted; inspect persisted draft before another save"
            )
        outcome = self.page.evaluate("window.appState.save_outcomes || {}").get(self.job["id"])
        if (
            outcome
            and outcome.get("status") == "confirmed_failed"
            and outcome.get("operation_id") == self.job["id"]
        ):
            if self.saved_result(expected_result):
                raise Recovery("ambiguous", "Application rejection conflicts with a persisted draft")
            raise MutationRejected(self.job["id"], outcome["reason"])
        result = self.saved_result(expected_result)
        if not result:
            raise Recovery("ambiguous", "No persisted result found after Save")
        return result

    def tool_action(self, name, args):
        if name == "observe_app":
            return self.observe().model_dump()
        if name == "click":
            obs = self.observe()
            target = args.get("target")
            if args.get("x") is not None:
                x, y = float(args["x"]), float(args["y"])
                matches = [
                    t
                    for t in obs.targets
                    if abs(x - t["x"]) <= t["width"] / 2 and abs(y - t["y"]) <= t["height"] / 2
                ]
                if not matches:
                    raise PermissionError("Correction is not an actionable scoped control")
                target = matches[-1]["target"]
            # Coordinates resolve to a known DOM control; never arbitrary script, URL, or desktop clicks.
            if target not in {
                "dialog-review",
                "dialog-keep",
                "dialog-discard",
                "dialog-acknowledge",
                "invoices",
                "company",
                f"open-{self.job['invoice_id']}",
            }:
                raise PermissionError("Click target outside assistance scope")
            self.click_target(target)
            return {"clicked": target}
        if name == "set_field":
            if args["field"] not in {"amount", "note"}:
                raise PermissionError("Field outside draft scope")
            return self.set_field(args["field"], args["value"])
        if name == "save_draft":
            return self.save_and_verify(self.job["expected"])
        raise PermissionError("Unknown tool")


class ThreadedBrowserAdapter:
    """Playwright owns one thread; LangGraph tools may execute on other threads."""

    def __init__(self, settings, store):
        from concurrent.futures import ThreadPoolExecutor

        object.__setattr__(self, "_pool", ThreadPoolExecutor(max_workers=1, thread_name_prefix="desktop"))
        object.__setattr__(self, "_adapter", self._pool.submit(BrowserAdapter, settings, store).result())

    def __getattr__(self, name):
        if name in {"job", "fence"}:
            return self._pool.submit(getattr, self._adapter, name).result()

        def call(*args, **kwargs):
            return self._pool.submit(getattr(self._adapter, name), *args, **kwargs).result()

        return call

    def __setattr__(self, name, value):
        self._pool.submit(setattr, self._adapter, name, value).result()

    def close(self):
        self._pool.submit(self._adapter.close).result()
        self._pool.shutdown()
