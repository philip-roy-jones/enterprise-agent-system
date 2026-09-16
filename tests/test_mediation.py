"""Application mediation tests; all desktops, models and people here are simulated."""

import base64
import copy
import io
import json

import httpx
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from eas_mediator.app import create_app
from eas_mediator.demobooks import project
from eas_shared.identity import fingerprint
from eas_server.security import token_hash
from eas_server.worker_api import CONTRACTS
from test_security_boundaries import secured, new_job  # noqa: F401


def node(ident, name, kind="Text", value=None, x=120, y=70):
    return dict(
        element=ident,
        automation_id=ident,
        name=name,
        type=kind,
        value=value,
        x=x,
        y=y,
        width=200,
        height=25,
        enabled=True,
        invoke=kind == "Button",
        edit=kind == "Edit",
    )


@pytest.fixture
def native_view():
    return dict(
        revision="native-1",
        pid=42,
        window=123,
        title="secret title",
        foreground=True,
        minimized=False,
        width=800,
        height=600,
        desktop_session=2,
        screenshot="THIS MUST NEVER BE USED",
        elements=[
            node("invoices", "Vendor invoices", "Button"),
            node("vendor-bank-account", "Bank 000123456789", value="000123456789", y=140),
            node("unknown", "CONFIDENTIAL", y=190),
            node("save", "Save correction draft", "Button", y=250),
            node("amount", "Correction amount", "Edit", "900.00", y=300),
            node("company-status", "Company: ACME    |    Ready", y=580),
        ],
    )


def authority(drafts=True):
    policy = dict(profile="demobooks-v1", enabled=True, allow_drafts=drafts)
    return dict(policy=policy, policy_revision=fingerprint(policy), company_id="ACME", record_id="INV-1042")


def test_projection_withholds_raw_pixels_text_values_and_containers(native_view):
    native_view["elements"].append(node("parent", "CONFIDENTIAL Bank 000123456789", "Pane"))
    view = project(native_view, authority())
    encoded = json.dumps(view)
    assert all(
        secret not in encoded for secret in ("000123456789", "CONFIDENTIAL", "secret title", "THIS MUST")
    )
    image = Image.open(io.BytesIO(base64.b64decode(view["screenshot"])))
    assert image.getpixel((21, 150)) == (20, 43, 58)
    assert view["surface"] == "mediated_application"
    assert view["mediation"]["restrictions"][0]["label"] == "Bank details restricted"


def test_geometry_and_policy_invalidate_view_and_disabled_controls_remain_described(native_view):
    a = project(native_view, authority())
    changed = copy.deepcopy(native_view)
    changed.update(revision="moved", width=1000)
    changed["elements"][0]["x"] = 320
    b = project(changed, authority())
    c = project(changed, authority(False))
    assert len({a["revision"], b["revision"], c["revision"]}) == 3
    assert b["elements"][0]["x"] == 320
    save = next(n for n in c["elements"] if n.get("mediated_target") == "save")
    assert not save["enabled"] and save["description"] and save["blocked_reason"]


@pytest.mark.parametrize("change", ["background", "ambiguous", "renamed"])
def test_untrustworthy_views_fail_closed(native_view, change):
    if change == "background":
        native_view["foreground"] = False
    elif change == "ambiguous":
        native_view["elements"].append(native_view["elements"][0])
    else:
        native_view["elements"][0]["name"] = "Execute something else"
    with pytest.raises(PermissionError):
        project(native_view, authority())


@pytest.fixture
def service(native_view, tmp_path):
    calls, office_calls = [], []

    def native(request):
        calls.append((request.url.path, json.loads(request.content or b"{}")))
        if request.url.path == "/observe":
            return httpx.Response(200, json=native_view)
        return httpx.Response(200, json=dict(executed=True, method="simulated_control"))

    def office(request):
        office_calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=authority())

    app = create_app(
        native=httpx.Client(base_url="http://native", transport=httpx.MockTransport(native)),
        office=httpx.Client(base_url="http://office", transport=httpx.MockTransport(office)),
        token="test-" + "x" * 40,
        ledger_path=tmp_path / "inputs.sqlite",
    )
    c = TestClient(app, headers={"Authorization": "Bearer test-" + "x" * 40, "X-EAS-Job": "test-job"})
    return c, calls, office_calls, app


def test_control_binding_ignores_forged_coordinates_and_deduplicates(service):
    c, calls, office_calls, _ = service
    view = c.get("/observe").json()
    body = dict(operation="click", element="invoices", revision=view["revision"], x=700, y=500)
    assert c.post("/action", json=body).status_code == 200
    assert c.post("/action", json=body).status_code == 200
    effects = [b for path, b in calls if path == "/action"]
    assert len(effects) == 1 and (effects[0]["x"], effects[0]["y"]) == (120, 70)
    assert any(b.get("target") == "invoices" for _, b in office_calls)
    assert not any(path == "/screenshot" for path, _ in calls)


@pytest.mark.parametrize(
    "changes", [dict(element="unknown"), dict(revision="stale"), dict(operation="keys"), dict(element=None)]
)
def test_no_generic_input_or_stale_input_bypass(service, changes):
    c, calls, _, _ = service
    view = c.get("/observe").json()
    body = dict(operation="invoke", element="invoices", revision=view["revision"]) | changes
    assert c.post("/action", json=body).status_code == (409 if "revision" in changes else 403)
    assert not any(path == "/action" for path, _ in calls)


def test_uncertain_native_input_is_not_retried_after_service_restart(service, tmp_path):
    c, calls, _, app = service
    view = c.get("/observe").json()
    mediator = app.state.mediator

    def lost(request):
        if request.url.path == "/action":
            raise httpx.ReadTimeout("lost response")
        return httpx.Response(200, json=copy.deepcopy(calls) and native_snapshot)

    native_snapshot = mediator.native_call("/observe", {})
    mediator.native = httpx.Client(base_url="http://native", transport=httpx.MockTransport(lost))
    body = dict(operation="invoke", element="invoices", revision=view["revision"])
    assert c.post("/action", json=body).status_code == 409
    from eas_mediator.ledger import InputLedger

    mediator.ledger = InputLedger(tmp_path / "inputs.sqlite")
    retry = c.post("/action", json=body)
    assert retry.status_code == 403 and "uncertain" in retry.json()["error"]


@pytest.fixture
def office(secured):  # noqa: F811
    app, c, h, rpc, registry = secured
    values = json.loads(registry.read_text())
    executor = next(p for p in values["principals"] if p["id"] == "exec-a")
    mediator = copy.deepcopy(executor)
    mediator.update(id="mediator", kind="mediator", token_sha256=token_hash("test-mediator"))
    mediator["grants"][0]["actions"] = ["mediate"]
    values["principals"].append(mediator)
    registry.write_text(json.dumps(values))
    c.put("/api/employees/desktop-a/mediation-policy", headers=h("reviewer"), json={}).raise_for_status()
    job = new_job(secured)
    rpc("exec-a", "claim", "process").raise_for_status()
    return app, c, h, rpc, registry, job


def test_office_denies_cross_employee_identity_and_missing_operation(office):
    _, c, h, _, _, job = office
    body = dict(job_id=job["id"], path="/observe")
    assert c.post("/api/mediation/authorize", headers=h("mediator"), json=body).status_code == 200
    for actor in ("alice", "exec-a", "planner", "admission"):
        assert c.post("/api/mediation/authorize", headers=h(actor), json=body).status_code == 403
    assert (
        c.post(
            "/api/mediation/authorize", headers=h("mediator"), json=body | dict(path="/action", target="save")
        ).status_code
        == 403
    )
    assert c.put("/api/employees/desktop-a/mediation-policy", headers=h("alice"), json={}).status_code == 403
    other = c.post(
        "/api/jobs", headers=h("bob"), json={"invoice_id": "INV-1042", "employee_id": "desktop-b"}
    ).json()
    assert (
        c.post(
            "/api/mediation/authorize", headers=h("mediator"), json=body | dict(job_id=other["id"])
        ).status_code
        == 404
    )


def begin(office, name, arguments, revision):
    _, _, _, rpc, _, job = office
    lease = rpc("exec-a", "lease").json()
    op = CONTRACTS[name]
    invocation = job["id"] + ":mediated-test"
    proposal = dict(
        name=name,
        kind="tool",
        arguments=arguments,
        operation_spec=op,
        observation=dict(revision=revision, screenshot="", state={}),
        epoch=lease["epoch"],
        signature="simulated",
        description=op["description"],
        expected=op["expected"],
    )
    a = rpc("exec-a", "authorize_operation", job["id"], invocation, proposal)
    a.raise_for_status()
    # Exercise the actual signed grant path, not a forged executing row.
    args = [
        job["id"],
        lease["owner"],
        lease["epoch"],
        invocation,
        dict(name=name, arguments=arguments, observation_revision=revision),
        a.json()["id"],
    ]
    _, c, h, _, _, _ = office
    token = c.post("/api/execution/grant", headers=h("exec-a"), json={"args": args})
    token.raise_for_status()
    rpc("exec-a", "begin_action", *args, grant=token.json()["grant"]).raise_for_status()


def test_office_enforces_exact_operation_revision_policy_and_pause(office):
    _, c, h, _, _, job = office
    config = c.get("/api/employees/desktop-a/mediation-policy", headers=h("reviewer")).json()
    begin(office, "set_field", {"field": "amount", "value": "900.00"}, "screen-1")
    body = dict(
        job_id=job["id"],
        path="/action",
        target="amount",
        value="900.00",
        revision="screen-1",
        policy_revision=config["policy_revision"],
    )
    assert c.post("/api/mediation/authorize", headers=h("mediator"), json=body).status_code == 200
    for changes in (
        dict(value="9000.00"),
        dict(target="save"),
        dict(revision="stale"),
        dict(policy_revision="old"),
    ):
        assert (
            c.post("/api/mediation/authorize", headers=h("mediator"), json=body | changes).status_code == 403
        )
    c.put(
        "/api/employees/desktop-a/mediation-policy", headers=h("reviewer"), json={"allow_drafts": False}
    ).raise_for_status()
    config = c.get("/api/employees/desktop-a/mediation-policy", headers=h("reviewer")).json()
    assert (
        c.post(
            "/api/mediation/authorize",
            headers=h("mediator"),
            json=body | dict(policy_revision=config["policy_revision"]),
        ).status_code
        == 403
    )


def test_published_view_is_scoped_and_cleared_on_policy_change(office, native_view):
    _, c, h, _, _, job = office
    view = project(native_view, authority())
    c.post(
        "/api/mediation/view", headers=h("mediator"), json=dict(job_id=job["id"], view=view)
    ).raise_for_status()
    assert c.get("/api/employees/desktop-a/mediated-view", headers=h("alice")).status_code == 200
    assert c.get("/api/employees/desktop-a/mediated-view", headers=h("bob")).status_code == 404
    c.put(
        "/api/employees/desktop-a/mediation-policy", headers=h("reviewer"), json={"allow_drafts": False}
    ).raise_for_status()
    assert c.get("/api/employees/desktop-a/mediated-view", headers=h("alice")).status_code == 404


def test_shadowing_may_observe_but_cannot_activate_or_input(office):
    _, c, h, _, registry, job = office
    values = json.loads(registry.read_text())
    next(p for p in values["principals"] if p["id"] == "reviewer")["grants"][0]["actions"].append("request")
    registry.write_text(json.dumps(values))
    c.post(f"/api/jobs/{job['id']}/cancel", headers=h("alice")).raise_for_status()
    c.post(
        "/api/employees/desktop-a/state",
        headers=h("reviewer"),
        json={"state": "shadowing", "reason": "Simulated mentor demonstration"},
    ).raise_for_status()
    demo = c.post(
        "/api/employees/desktop-a/demonstrations",
        headers=h("reviewer"),
        json={
            "role_id": "invoice_correction",
            "company_id": "ACME",
            "task": "Demonstrate reading an invoice",
        },
    )
    demo.raise_for_status()
    for path in ("/observe", "/screenshot", "/activate", "/action"):
        r = c.post(
            "/api/mediation/authorize",
            headers=h("mediator"),
            json={"job_id": demo.json()["id"], "path": path},
        )
        assert r.status_code == (200 if path in {"/observe", "/screenshot"} else 403)


def test_office_revocation_and_operation_deadline_fail_closed(office):
    app, c, h, _, registry, job = office
    config = c.get("/api/employees/desktop-a/mediation-policy", headers=h("reviewer")).json()
    begin(office, "click", {"target": "invoices"}, "screen-1")
    body = dict(
        job_id=job["id"],
        path="/action",
        target="invoices",
        revision="screen-1",
        policy_revision=config["policy_revision"],
    )
    with app.state.store.db() as db:
        db.execute("UPDATE events SET at=0 WHERE job_id=? AND kind='action_started'", (job["id"],))
    assert c.post("/api/mediation/authorize", headers=h("mediator"), json=body).status_code == 403
    values = json.loads(registry.read_text())
    next(p for p in values["principals"] if p["id"] == "mediator")["enabled"] = False
    registry.write_text(json.dumps(values))
    assert (
        c.post(
            "/api/mediation/authorize", headers=h("mediator"), json=body | {"path": "/observe"}
        ).status_code
        == 401
    )


def test_office_outage_never_reads_native_desktop(service):
    c, calls, _, app = service
    app.state.mediator.office = httpx.Client(
        base_url="http://office", transport=httpx.MockTransport(lambda r: httpx.Response(503))
    )
    assert c.get("/observe").status_code == 403
    assert calls == []


def test_other_company_and_other_record_are_not_disclosed_or_edited(native_view, service):
    other = copy.deepcopy(native_view)
    other["elements"][-1]["name"] = "Company: OTHER    |    Ready"
    with pytest.raises(PermissionError, match="company"):
        project(other, authority())
    with pytest.raises(PermissionError, match="company"):
        project(native_view, authority() | {"company_id": "OTHER"})
    c, calls, _, _ = service
    view = c.get("/observe").json()
    # This view has no identified invoice; an authorized edit cannot be applied
    # to some other page merely because the same field ID is present.
    r = c.post(
        "/action",
        json=dict(operation="set_value", element="amount", value="900.00", revision=view["revision"]),
    )
    assert r.status_code == 403 and not any(path == "/action" for path, _ in calls)
