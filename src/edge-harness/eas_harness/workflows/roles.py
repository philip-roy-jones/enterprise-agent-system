"""Trusted department workflow registry; the invoice workflow is the first example plugin.

Role modules are application code, not model-generated imports. EAS_WORKFLOW_MODULES loads edge-only runtime plugins. Register matching public
role definitions separately on the server with EAS_SERVER_ROLE_MODULES.
"""

from dataclasses import dataclass
import importlib
import os
from typing import Callable
from eas_shared.roles import RoleDefinition, InvoiceCorrectionInputs
from eas_harness.workflows.finance.operations import OPERATIONS


@dataclass(frozen=True, kw_only=True)
class WorkerRole(RoleDefinition):
    graph_factory: Callable
    adapter_factory: Callable
    operations: dict


ROLES: dict[str, WorkerRole] = {}


def register_role(role: WorkerRole):
    if role.id in ROLES:
        raise ValueError(f"Role already registered: {role.id}")
    ROLES[role.id] = role


def _invoice_graph(*args, **kwargs):
    from eas_harness.workflows.finance.graph import RoleGraph

    return RoleGraph(*args, **kwargs)


def _browser_adapter(settings, store):
    if settings.desktop_adapter == "windows_accessibility":
        from eas_harness.adapters.accessibility_adapter import AccessibilityAdapter

        return AccessibilityAdapter(settings, store)
    if settings.desktop_adapter == "windows":
        from eas_harness.adapters.windows_adapter import WindowsAdapter

        return WindowsAdapter(settings, store)
    if settings.desktop_adapter != "browser":
        raise ValueError("EAS_DESKTOP_ADAPTER must be browser, windows, or windows_accessibility")
    from eas_harness.adapters.adapter import ThreadedBrowserAdapter

    return ThreadedBrowserAdapter(settings, store)


register_role(
    WorkerRole(
        id="invoice_correction",
        department_id="finance",
        department_name="Finance",
        name="Invoice correction",
        application="DemoBooks Desktop (Windows)"
        if os.getenv("EAS_DESKTOP_ADAPTER") in {"windows", "windows_accessibility"}
        else "Ledger (synthetic)",
        input_model=InvoiceCorrectionInputs,
        graph_factory=_invoice_graph,
        adapter_factory=_browser_adapter,
        operations=OPERATIONS,
        permissions=("read", "navigate", "draft"),
        record_field="invoice_id",
        stages=("validate", "establish", "compare", "prepare", "save", "verify", "complete"),
    )
)


_loaded = False


def load_roles():
    global _loaded
    if not _loaded:
        for module in filter(
            None, os.getenv("EAS_WORKFLOW_MODULES", os.getenv("EAS_ROLE_MODULES", "")).split(",")
        ):
            importlib.import_module(module.strip())
        _loaded = True
    return ROLES


def get_role(role_id):
    try:
        return load_roles()[role_id]
    except KeyError:
        raise ValueError("Workflow is not installed on this backend or worker") from None
