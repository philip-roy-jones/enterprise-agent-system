"""Public workflow descriptions and job input validation, with no runtime factories."""

from dataclasses import dataclass
from pydantic import BaseModel, Field


class InvoiceCorrectionInputs(BaseModel):
    company_id: str = "ACME"
    invoice_id: str = Field(pattern=r"^INV-\d{4}$")


@dataclass(frozen=True, kw_only=True)
class RoleDefinition:
    id: str
    department_id: str
    department_name: str
    name: str
    application: str
    input_model: type[BaseModel]
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
