from dataclasses import replace
import pytest
from eas_harness.config import Settings
from eas_harness.workflows.roles import ROLES
from eas_shared.types import JobInput
from eas_harness.worker import validate_assignment, run_worker


@pytest.mark.parametrize(
    "updates",
    [
        {"organization_id": "other"},
        {"role_id": "sales"},
        {"department_id": "sales"},
        {"permissions": ["read", "admin"]},
        {"invoice_id": "INV-1044"},
    ],
)
def test_receiver_rejects_inconsistent_or_unauthorized_assignment(store, updates):
    job = store.create_job(JobInput(invoice_id="INV-1042").model_dump())
    with pytest.raises(PermissionError):
        validate_assignment(Settings(), job | updates)


def test_misrouted_job_never_initializes_desktop_or_graph(store, monkeypatch, tmp_path):
    job = store.create_job(JobInput(organization_id="other", invoice_id="INV-1042").model_dump())
    store.claim("dispatcher")
    monkeypatch.setattr("eas_harness.worker.RemoteStore", lambda *args: store)
    monkeypatch.setattr(store, "claim", lambda *args: job)

    def forbidden(*args):
        pytest.fail("Misrouted job initialized a desktop or graph")

    monkeypatch.setitem(
        ROLES,
        "invoice_correction",
        replace(ROLES["invoice_correction"], adapter_factory=forbidden, graph_factory=forbidden),
    )
    run_worker(Settings(data_dir=tmp_path / "edge"), once=True)
    result = store.get_job(job["id"])
    assert result["status"] == "denied"
    assert result["model_calls"] == 0 and result["mutation"] == "not_attempted"


def test_multiple_explicitly_authorized_roles_can_share_a_worker(store, monkeypatch):
    role = replace(ROLES["invoice_correction"], id="invoice_review")
    monkeypatch.setitem(ROLES, role.id, role)
    from eas_server.roles import ROLES as SERVER_ROLES
    from eas_shared.roles import RoleDefinition
    from dataclasses import fields

    metadata = RoleDefinition(**{f.name: getattr(role, f.name) for f in fields(RoleDefinition)})
    monkeypatch.setitem(SERVER_ROLES, role.id, metadata)
    job = store.create_job(JobInput(role_id=role.id, invoice_id="INV-1042").model_dump())
    with pytest.raises(PermissionError):
        validate_assignment(Settings(), job)
    assert (
        validate_assignment(Settings(worker_role_ids=("invoice_correction", "invoice_review")), job) is role
    )
