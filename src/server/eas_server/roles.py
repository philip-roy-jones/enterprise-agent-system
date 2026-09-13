"""Trusted server role catalog; contains no edge execution code."""

import importlib
import os
from eas_shared.marketing import MARKETING_ROLE
from eas_shared.roles import RoleDefinition, InvoiceCorrectionInputs


ROLES: dict[str, RoleDefinition] = {}


def register_role(role: RoleDefinition):
    if role.id in ROLES:
        raise ValueError(f"Role already registered: {role.id}")
    ROLES[role.id] = role


register_role(
    RoleDefinition(
        id="invoice_correction",
        department_id="finance",
        department_name="Finance",
        name="Invoice correction",
        application="DemoBooks Desktop (Windows)"
        if os.getenv("EAS_DESKTOP_ADAPTER") in {"windows", "windows_accessibility"}
        else "Ledger (synthetic)",
        input_model=InvoiceCorrectionInputs,
        permissions=("read", "navigate", "draft"),
        record_field="invoice_id",
        stages=("validate", "establish", "compare", "prepare", "save", "verify", "complete"),
    )
)


register_role(MARKETING_ROLE)

_loaded = False


def load_roles():
    global _loaded
    if not _loaded:
        for module in filter(None, os.getenv("EAS_SERVER_ROLE_MODULES", "").split(",")):
            importlib.import_module(module.strip())
        _loaded = True
    return ROLES


def get_role(role_id):
    try:
        return load_roles()[role_id]
    except KeyError:
        raise ValueError("Workflow is not installed on this server") from None
