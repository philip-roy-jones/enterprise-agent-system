"""DemoBooks workflow over external Windows accessibility and desktop input.

All business observations are decoded from visible UI controls. No application
API, database, process memory, or hidden accounting state is used. Other legacy
applications need their own observable labels, navigation, and verification rules.
"""

import base64
from dataclasses import replace
from decimal import Decimal, InvalidOperation
import re
import time

from eas_shared.types import Observation, Recovery, Stale
from eas_harness.adapters.windows_adapter import WindowsAdapter, WindowsBridge
from eas_harness.contracts import adapter_contract, SaveInputs, DraftResult


def cents(text):
    try:
        value = Decimal(text.replace("$", "").replace(",", "").strip()) * 100
        if value != value.to_integral_value():
            raise ValueError("Amount has fractional cents")
        return int(value)
    except (InvalidOperation, ValueError):
        raise Recovery("unfamiliar", "The displayed accounting amount could not be read") from None


def decode_observation(raw):
    nodes = raw["elements"]
    # Containers can inherit a child's accessible name; read displayed text once.
    names = [n["name"] for n in nodes if n["type"] == "Text"]
    title = next((n for n in names if re.fullmatch(r"Vendor invoice INV-\d{4}", n)), None)
    invoice_id = title.rsplit(" ", 1)[-1] if title else None
    view = (
        "invoice"
        if title
        else "invoices"
        if "Vendor invoice center" in names
        else "purchase_orders"
        if "Purchase order center" in names
        else "dashboard"
        if "Company home" in names
        else "unknown"
    )
    # Company identity comes from visible title/labels, not the assigned job.
    company = next((m[1] for name in names if (m := re.match(r"Company:\s*([A-Z0-9_-]+)\s+\|", name))), None)
    dialog = next(
        (
            kind
            for label, kind in [
                ("Accounting notice", "info"),
                ("Unsaved changes", "unsaved"),
                ("Review workspace update", "unfamiliar"),
            ]
            if label in names
        ),
        None,
    )
    known_labels = {
        "Acme Manufacturing  ▾": "company",
        "Vendor invoices": "invoices",
        "Company home": "dashboard",
        "Purchase orders": "purchase_orders",
        "Save correction draft": "save",
        "Correction amount": "amount",
        "Adjusted total": "amount",
        "Correction explanation": "note",
        "Understood": "dialog-acknowledge",
        "Keep editing": "dialog-keep",
        "Discard draft changes": "dialog-discard",
        "Reviewed — continue": "dialog-review",
    }
    targets = []
    for node in nodes:
        if node["type"] not in {"Button", "Edit"}:
            continue
        target = known_labels.get(node["name"])
        match = re.match(r"Open (INV-\d{4})\b", node["name"])
        if match:
            target = "open-" + match[1]
        if target:
            targets.append(dict(node, target=target, label=node["name"]))
    fields = {
        field: next((n["value"] or "" for n in targets if n["target"] == field), "")
        for field in ("amount", "note")
    }

    def money_below(label):
        labels = [n for n in nodes if n["name"] == label]
        if len(labels) != 1:
            raise Recovery("unfamiliar", "Accounting label is missing or ambiguous: " + label)
        anchor = labels[0]
        # Match by alignment and relative position, independent of screen origin.
        left = anchor["x"] - anchor["width"] / 2
        candidates = [
            n
            for n in nodes
            if re.fullmatch(r"\$[\d,]+\.\d{2}", n["name"])
            and abs(n["x"] - n["width"] / 2 - left) < 8
            and n["y"] > anchor["y"]
        ]
        if not candidates:
            raise Recovery("unfamiliar", "No visible amount below " + label)
        return cents(min(candidates, key=lambda n: n["y"])["name"])

    invoices = []
    if invoice_id:
        po = next((n for n in names if re.fullmatch(r"Purchase order PO-\d{4}", n)), None)
        if po:
            invoices.append(
                dict(
                    id=invoice_id,
                    company_id=company,
                    po_id=po.rsplit(" ", 1)[-1],
                    amount=money_below("Invoice amount"),
                    po_amount=money_below(po),
                )
            )
    drafts = []
    for name in names:
        for line in name.splitlines():
            match = re.fullmatch(r"(DRAFT-\d+)\s+(\$[\d,]+\.\d{2})\s+Draft\s+(.+)", line)
            if match:
                drafts.append(
                    dict(
                        id=match[1],
                        amount=cents(match[2]),
                        note=match[3],
                        invoice_id=invoice_id,
                        company_id=company,
                    )
                )
    state = dict(
        company_id=company,
        invoice_id=invoice_id,
        view=view,
        dialog=dialog,
        loading_until=time.time() + 0.25 if any("Loading accounting records" in n for n in names) else 0,
        fields=fields,
        invoices=invoices,
        drafts=drafts,
        record_catalog_complete=False,
        unsaved=any("Unsaved" in n for n in names),
        foreground=raw["foreground"],
        app_version="demobooks-windows-accessibility-1",
        observation_source="Windows UI Automation",
        revision=raw["revision"],
        desktop_session=raw["desktop_session"],
        **({"mediation": raw["mediation"]} if raw.get("mediation") else {}),
    )
    return state, targets


class AccessibilityAdapter(WindowsAdapter):
    def __init__(self, settings, store):
        self.store = store
        self.bridge = WindowsBridge(
            replace(
                settings,
                windows_bridge_url=settings.mediator_url or settings.desktop_agent_url,
                windows_token=settings.mediator_token
                if settings.mediator_url
                else settings.desktop_agent_token,
            )
        )
        self.bridge.call("/health")
        self.input_mode = settings.desktop_input_mode
        if self.input_mode not in {"accessibility", "mouse_keyboard"}:
            raise ValueError("EAS_DESKTOP_INPUT_MODE must be accessibility or mouse_keyboard")
        self.job = None
        if settings.mediator_url:
            self.bridge.request_context = lambda: self.job["id"] if self.job else None
        self.fence = lambda: (_ for _ in ()).throw(PermissionError("No active operation"))

    def correction_note(self, note):
        return f"{note} [EAS:{self.job['id']}]"

    def capture_screen(self):
        self.fence()
        return self.bridge.call("/screenshot", {})

    def read_state(self):
        return decode_observation(self.bridge.call("/observe", {"screenshot": False}))[0]

    def observe(self):
        raw = self.bridge.call("/observe")
        self._model_image = raw["screenshot"] if raw["foreground"] else None
        state, targets = decode_observation(raw)
        if not raw["screenshot"]:
            raise Recovery("temporary", "The assigned desktop window has no available screenshot")
        artifact = self.store.artifact(base64.b64decode(raw["screenshot"]))
        return Observation(
            revision=raw["revision"],
            timestamp=time.time(),
            screenshot=artifact,
            width=raw["width"],
            height=raw["height"],
            state=state,
            targets=targets,
        )

    def _action(self, name, args):
        self.fence()
        raw = self.bridge.call("/observe", {"screenshot": False})
        approved = getattr(self, "approved_observation", None)
        if approved is not None and raw["revision"] != approved.revision:
            raise Stale("The desktop changed after the tool approval; a fresh decision is required")
        state, targets = decode_observation(raw)
        target = args.get("target") if name == "click" else args.get("field")
        allowed = {
            "company",
            "invoices",
            "dialog-review",
            "dialog-keep",
            "dialog-discard",
            "dialog-acknowledge",
            f"open-{self.job['invoice_id']}",
            "amount",
            "note",
            "save",
        }
        if target not in allowed:
            raise PermissionError("Desktop target is outside this invoice workflow")
        if state["dialog"] and not target.startswith("dialog-"):
            raise Recovery("unfamiliar", "Resolve the visible dialog before another action")
        if target in {"amount", "note", "save"} and (
            state["company_id"] != self.job["company_id"] or state["invoice_id"] != self.job["invoice_id"]
        ):
            raise PermissionError("Desktop company or invoice differs from the assigned record")
        matches = [n for n in targets if n["target"] == target and n["enabled"]]
        if len(matches) != 1:
            raise Recovery("unfamiliar", "Desktop control is missing or ambiguous: " + str(target))
        node = matches[0]
        action = dict(revision=raw["revision"], element=node["element"])
        if name == "field":
            if target not in {"amount", "note"}:
                raise PermissionError("Only draft fields can receive text")
            action.update(
                operation="set_value", value=str(args["value"]), keyboard=self.input_mode == "mouse_keyboard"
            )
        elif name == "click":
            if self.input_mode == "mouse_keyboard":
                action.update(operation="click", x=node["x"], y=node["y"])
            else:
                action.update(operation="invoke")
        else:
            raise PermissionError("Unsupported desktop action")
        self.fence()
        result = self.bridge.call("/action", action)
        self.store.event(
            self.job["id"],
            "desktop_input",
            dict(target=target, method=result["method"], observation_revision=raw["revision"]),
        )
        # Accessibility invocation and SendInput enqueue UI work asynchronously.
        time.sleep(0.15)
        return self.read_state()

    def saved_result(self, expected):
        if not expected:
            return None
        state = self.read_state()
        if state["company_id"] != expected["company_id"] or state["invoice_id"] != expected["invoice_id"]:
            return None
        matches = [d for d in state["drafts"] if f"[EAS:{self.job['id']}]" in d["note"]]
        if len(matches) > 1:
            raise Recovery("ambiguous", "Multiple visible drafts contain this job reference")
        if not matches:
            return None
        draft = matches[0]
        if draft["amount"] != expected["amount"] or draft["note"] != expected["note"]:
            raise Recovery("ambiguous", "Visible saved draft differs from the verified business result")
        return dict(
            draft,
            operation_id=self.job["id"],
            verification="visible saved draft and unique explanation reference",
        )

    @adapter_contract(SaveInputs, DraftResult)
    def save_and_verify(self, expected_result):
        saved = self.saved_result(expected_result)
        if saved:
            return saved
        if self.job.get("mutation") == "attempted_uncertain":
            raise Recovery(
                "ambiguous",
                "An earlier Save has no verified result; staff must reconcile before another Save",
            )
        state = self.ensure_editable()
        if (
            cents(state["fields"]["amount"]) != expected_result["amount"]
            or state["fields"]["note"] != expected_result["note"]
        ):
            raise PermissionError(
                "Visible draft fields must match the verified purchase order and job reference before Save"
            )
        self.click_target("save")
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            saved = self.saved_result(expected_result)
            if saved:
                return saved
            time.sleep(0.2)
        raise Recovery(
            "ambiguous", "Save was issued but no matching draft is visible; reconcile without another Save"
        )
