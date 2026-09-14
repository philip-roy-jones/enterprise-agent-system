import pytest
from pydantic import BaseModel
from eas_harness.roles import WorkerRole, ROLES
from eas_shared.types import JobInput


class PeopleInputs(BaseModel):
    case_id: str
    policy_scope: str = "onboarding"


@pytest.fixture
def people_role(monkeypatch):
    # Test-only role validates the generic platform boundary; no HR integration is claimed.
    role = WorkerRole(
        id="onboarding_review",
        department_id="people",
        department_name="People",
        name="Onboarding review",
        application="Test people workspace",
        input_model=PeopleInputs,
        adapter_factory=lambda *a: None,
        operations={},
        permissions=("read",),
        record_field="case_id",
        stages=("review",),
    )
    monkeypatch.setitem(ROLES, role.id, role)
    from eas_server.roles import ROLES as SERVER_ROLES
    from eas_shared.roles import RoleDefinition
    from dataclasses import fields

    metadata = RoleDefinition(**{f.name: getattr(role, f.name) for f in fields(RoleDefinition)})
    monkeypatch.setitem(SERVER_ROLES, role.id, metadata)
    return role


def test_department_role_uses_its_own_input_schema(store, people_role):
    job = store.create_job(
        JobInput(
            department_id="people", role_id="onboarding_review", inputs={"case_id": "CASE-12"}
        ).model_dump()
    )
    assert job["record_id"] == "CASE-12"
    assert job["department_id"] == "people"
    assert job["permissions"] == ["read"]
    assert job["task"] == "onboarding_review"
    assert job["inputs"] == {"case_id": "CASE-12", "policy_scope": "onboarding"}
    assert job["invoice_id"] is None


def test_department_cannot_select_another_departments_role(store, people_role):
    with pytest.raises(PermissionError, match="department"):
        store.create_job(
            JobInput(
                department_id="finance", role_id="onboarding_review", inputs={"case_id": "CASE-12"}
            ).model_dump()
        )


def test_role_permissions_do_not_inherit_finance_capabilities(store, people_role):
    with pytest.raises(PermissionError, match="permissions"):
        store.create_job(
            JobInput(
                department_id="people",
                role_id="onboarding_review",
                inputs={"case_id": "CASE-12"},
                permissions=["read", "draft"],
            ).model_dump()
        )


def test_episodes_do_not_cross_department_or_role_scopes(store, people_role):
    first = store.create_job(JobInput(invoice_id="INV-1042", task="Review this record").model_dump())
    store.update_job(first["id"], {"status": "completed"})
    store.accept(first["id"])
    people = store.create_job(
        JobInput(
            department_id="people",
            role_id="onboarding_review",
            inputs={"case_id": "CASE-12"},
            task="Review this record",
        ).model_dump()
    )
    finance = store.create_job(JobInput(invoice_id="INV-1043", task="Review this record").model_dump())
    with store.db() as db:
        assert store.related_learning_jobs(db, people) == []
        assert store.related_learning_jobs(db, finance) == [first["id"]]


def test_server_and_worker_share_public_contract_without_runtime_factories():
    from eas_server.roles import ROLES as server_roles

    server_role = server_roles["invoice_correction"]
    assert server_role.public() == ROLES["invoice_correction"].public()
    assert not hasattr(server_role, "graph_factory")
    assert not hasattr(server_role, "adapter_factory")
    assert not hasattr(server_role, "operations")
