"""Trusted department workflow registry; the invoice workflow is the first example plugin.

Role modules are application code, not model-generated imports. Configure the same
EAS_ROLE_MODULES on backend and workers to register additional department workflows.
"""

from dataclasses import dataclass
import importlib
import os
from typing import Callable
from pydantic import BaseModel, Field
from .operations import OPERATIONS


class InvoiceCorrectionInputs(BaseModel):
    company_id: str = "ACME"
    invoice_id: str = Field(pattern=r"^INV-\d{4}$")


@dataclass(frozen=True)
class WorkerRole:
    id: str
    department_id: str
    department_name: str
    name: str
    application: str
    input_model: type[BaseModel]
    graph_factory: Callable
    adapter_factory: Callable
    operations: dict
    permissions: tuple[str, ...]
    record_field: str
    stages: tuple[str, ...] = ()

    def normalize(self, job):
        values = dict(job.get("inputs", {}))
        # Compatibility with the original invoice-demo API, confined to this role's schema.
        for field in self.input_model.model_fields:
            if job.get(field) is not None and field not in values:
                values[field] = job[field]
        inputs = self.input_model.model_validate(values).model_dump()
        if job["department_id"] != self.department_id:
            raise PermissionError("Workflow does not belong to the requested department")
        permissions = job.get("permissions") if job.get("permissions") is not None else list(self.permissions)
        if set(permissions) - set(self.permissions):
            raise PermissionError("Requested permissions exceed this worker role")
        return dict(
            job,
            inputs=inputs,
            permissions=permissions,
            task=job.get("task") or self.id,
            record_id=str(inputs[self.record_field]),
            role_name=self.name,
            department_name=self.department_name,
            application=self.application,
            **inputs,
        )

    def public(self):
        return {
            "id": self.id,
            "department_id": self.department_id,
            "department_name": self.department_name,
            "name": self.name,
            "application": self.application,
            "input_schema": self.input_model.model_json_schema(),
            "permissions": list(self.permissions),
            "stages": list(self.stages),
        }


ROLES: dict[str, WorkerRole] = {}


def register_role(role: WorkerRole):
    if role.id in ROLES:
        raise ValueError(f"Role already registered: {role.id}")
    ROLES[role.id] = role


def _invoice_graph(*args, **kwargs):
    from .graph import RoleGraph

    return RoleGraph(*args, **kwargs)


def _browser_adapter(settings, store):
    if settings.desktop_adapter == "windows":
        from .windows_adapter import WindowsAdapter

        return WindowsAdapter(settings, store)
    if settings.desktop_adapter != "browser":
        raise ValueError("EAS_DESKTOP_ADAPTER must be browser or windows")
    from .adapter import ThreadedBrowserAdapter

    return ThreadedBrowserAdapter(settings, store)


register_role(
    WorkerRole(
        id="invoice_correction",
        department_id="finance",
        department_name="Finance",
        name="Invoice correction",
        application="DemoBooks Desktop (Windows)"
        if os.getenv("EAS_DESKTOP_ADAPTER") == "windows"
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
        for module in filter(None, os.getenv("EAS_ROLE_MODULES", "").split(",")):
            importlib.import_module(module.strip())
        _loaded = True
    return ROLES


def get_role(role_id):
    try:
        return load_roles()[role_id]
    except KeyError:
        raise ValueError("Workflow is not installed on this backend or worker") from None
