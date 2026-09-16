"""Versioned DemoBooks UI projection. No database or application API access.

We render an allowlisted accessibility view instead of forwarding raw screen
pixels. Unknown controls, inherited container names, and bank details never
enter the projected image or text. This is deliberately application-specific.
"""

import base64
import io
import math
import re

from PIL import Image, ImageDraw, ImageFont
from eas_shared.identity import fingerprint


CONTROLS = {
    "company": ("Acme Manufacturing  ▾", "Select the assigned company"),
    "invoices": ("Vendor invoices", "Open the invoice list"),
    "dashboard": ("Company home", "Open the company home page"),
    "purchase_orders": ("Purchase orders", "Open the purchase order list"),
    "view-invoices": ("Open vendor invoices", "Open the invoice list"),
    "save": ("Save correction draft", "Save one correction draft; the original invoice is unchanged"),
    "amount": ("Correction amount", "Set the correction draft amount"),
    "note": ("Correction explanation", "Set the correction draft explanation"),
    "dialog-acknowledge": ("Understood", "Acknowledge the accounting notice"),
    "dialog-keep": ("Keep editing", "Keep unsaved draft changes"),
    "dialog-discard": ("Discard draft changes", "Discard the unsaved draft changes"),
    "dialog-review": ("Reviewed — continue", "Acknowledge the workspace notice"),
}
LABELS = {
    "ACME MANUFACTURING  /  FINANCE",
    "Company home",
    "Vendors & accounts payable",
    "Open invoices",
    "Amount awaiting review",
    "Correction drafts",
    "Recent activity",
    "No correction drafts saved yet.",
    "Vendor invoice center",
    "Purchase order center",
    "Open a record to review its invoice and purchase order.",
    "Invoice amount",
    "Discrepancy",
    "Correction draft",
    "Correction amount",
    "Adjusted total",
    "Correction explanation",
    "Original invoice is unchanged. This saves a draft for review.",
    "Saved correction drafts",
    "No draft saved for this invoice.",
    "Accounting notice",
    "Unsaved changes",
    "Review workspace update",
    "This draft contains unsaved changes. Choose how to continue.",
    "You are working in a synthetic training company.",
    "A new review notice is available. Review it before continuing.",
    "Loading accounting records…",
}


def control(node):
    ident, name = node.get("automation_id", ""), node.get("name", "")
    if ident in CONTROLS:
        label, description = CONTROLS[ident]
        if name != label and not (ident == "amount" and name == "Adjusted total"):
            raise PermissionError("A recognized application control changed its label")
        if node["type"] != ("Edit" if ident in {"amount", "note"} else "Button"):
            raise PermissionError("A recognized application control changed its type")
        return ident, description
    if re.fullmatch(r"open-INV-\d{4}", ident) and node["type"] == "Button":
        if not re.match(r"Open " + re.escape(ident[5:]) + r"\b", name):
            raise PermissionError("Invoice control identity is inconsistent")
        return ident, "Open invoice " + ident[5:]
    return None


def safe_text(node):
    if node["type"] != "Text":
        return False
    text = node.get("name", "")
    return text in LABELS or bool(
        re.fullmatch(
            r"(?:Vendor invoice INV-\d{4}|Purchase order PO-\d{4}|\$[\d,]+\.\d{2}|"
            r"Company: ACME\s+\|[^\r\n]*|DRAFT-\d+\s+\$[\d,]+\.\d{2}\s+Draft\s+[^\r\n]+)"
            r"(?:\nDRAFT-\d+\s+\$[\d,]+\.\d{2}\s+Draft\s+[^\r\n]+)*",
            text,
        )
    )


def project(raw, authority):
    # The first profile supports this synthetic company only. Do not disclose a
    # different company's screen while trying to navigate back into scope.
    companies = [
        re.match(r"Company:\s*([A-Z0-9_-]+)\s+\|", n.get("name", ""))
        for n in raw["elements"]
        if n.get("type") == "Text"
    ]
    visible_companies = {m[1] for m in companies if m}
    if authority.get("company_id") != "ACME" or visible_companies != {"ACME"}:
        raise PermissionError("Application company is outside the mediated profile")
    width, height = raw["width"], raw["height"]
    if not raw["foreground"] or raw["minimized"]:
        raise PermissionError("The assigned application must be visible; no other desktop is disclosed")
    if not (64 <= width <= 4096 and 64 <= height <= 4096) or len(raw["elements"]) > 1000:
        raise PermissionError("Application surface exceeds the mediation limit")
    elements, restrictions, seen = [], [], set()
    for node in raw["elements"]:
        geometry = [node[k] for k in ("x", "y", "width", "height")]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in geometry):
            raise PermissionError("Invalid control geometry")
        x, y, w, h = geometry
        if w <= 0 or h <= 0 or w > width * 2 or h > height * 2:
            continue
        identity = control(node)
        if node.get("automation_id") == "vendor-bank-account":
            restrictions.append(dict(x=x, y=y, width=w, height=h, label="Bank details restricted"))
            continue
        if identity:
            target, description = identity
            if target in seen:
                raise PermissionError("Application control is ambiguous")
            seen.add(target)
            allowed = authority["policy"]["allow_drafts"] or target not in {
                "amount",
                "note",
                "save",
                "dialog-discard",
            }
            elements.append(
                {
                    k: node[k]
                    for k in (
                        "element",
                        "automation_id",
                        "name",
                        "type",
                        "value",
                        "x",
                        "y",
                        "width",
                        "height",
                        "invoke",
                        "edit",
                    )
                }
                | dict(
                    enabled=bool(node["enabled"] and allowed),
                    description=description,
                    mediated_target=target,
                    blocked_reason=None if allowed else "Office policy is read-only",
                )
            )
        elif safe_text(node):
            elements.append(
                {
                    k: node[k]
                    for k in ("element", "automation_id", "name", "type", "x", "y", "width", "height")
                }
                | dict(value=None, enabled=False, invoke=False, edit=False)
            )
    # Raw revision binds position, foreground and native identity. Policy changes
    # also invalidate prior views. No raw text or pixels escape this function.
    revision = fingerprint([raw["revision"], authority["policy_revision"]])
    image = Image.new("RGB", (width, height), "#f3f5f7")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=14)
    for node in elements:
        x, y, w, h = [node[k] for k in ("x", "y", "width", "height")]
        box = (int(x - w / 2), int(y - h / 2), int(x + w / 2), int(y + h / 2))
        tile = Image.new(
            "RGB", (max(1, int(w)), max(1, int(h))), "#ffffff" if node["type"] != "Text" else "#f3f5f7"
        )
        ink = ImageDraw.Draw(tile)
        if node["type"] != "Text":
            ink.rectangle((0, 0, tile.width - 1, tile.height - 1), outline="#9eacb7")
        ink.text(
            (3, 2),
            node.get("value") if node["type"] == "Edit" else node["name"],
            font=font,
            fill="#22333f" if node["enabled"] or node["type"] == "Text" else "#7c8791",
        )
        image.paste(tile, box[:2])
    for area in restrictions:
        x, y, w, h = [area[k] for k in ("x", "y", "width", "height")]
        draw.rectangle((x - w / 2, y - h / 2, x + w / 2, y + h / 2), fill="#142b3a")
        draw.text((x - w / 2 + 3, y - h / 2 + 2), area["label"], fill="white", font=font)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return {
        k: raw[k] for k in ("pid", "window", "foreground", "minimized", "width", "height", "desktop_session")
    } | dict(
        revision=revision,
        title="DemoBooks · mediated view",
        elements=elements,
        screenshot=base64.b64encode(output.getvalue()).decode(),
        surface="mediated_application",
        mediation=dict(
            profile="demobooks-v1",
            policy_revision=authority["policy_revision"],
            rendering="accessibility_projection",
            restrictions=restrictions,
            unknown_content="withheld",
        ),
    )
