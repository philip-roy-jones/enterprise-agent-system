"""Adversarial HTTP clients, without relying on cooperative model behavior."""

import json
import pytest
from fastapi.testclient import TestClient
from eas_server.backend import create_app
from eas_server.config import Settings
from eas_server.security import token_hash
from eas_server.worker_api import CONTRACTS


@pytest.fixture
def secured(tmp_path):
    scope = dict(
        organization_id="acme", department_id="finance", role_id="invoice_correction", company_id="ACME"
    )
    people = []
    for name, kind, actions, worker in [
        ("alice", "human", ["request", "read", "approve", "control", "accept", "skills"], None),
        ("bob", "human", ["request", "read", "approve", "control", "accept", "skills"], None),
        ("reviewer", "human", ["read", "approve"], None),
        ("sales", "human", ["request", "read"], None),
        ("exec-a", "executor", ["execute"], "desktop-a"),
        ("exec-b", "executor", ["execute"], "desktop-b"),
        ("planner", "planner", ["execute"], "desktop-a"),
        ("admission", "admission", ["admit"], "desktop-a"),
    ]:
        grant = {
            **scope,
            "actions": actions,
            "capabilities": ["read", "navigate", "draft"],
            "own_only": kind == "human" and name != "reviewer",
        }
        if name == "sales":
            grant.update(department_id="sales", role_id="crm")
        people.append(
            dict(
                id=name,
                name=name,
                kind=kind,
                worker_id=worker,
                token_sha256=token_hash("test-" + name),
                grants=[grant],
            )
        )
    policy = tmp_path / "identities.json"
    policy.write_text(json.dumps({"principals": people}))
    app = create_app(Settings(data_dir=tmp_path, identity_file=str(policy), desktop_adapter="browser"))
    client = TestClient(app)

    def headers(who):
        return {"Authorization": "Bearer test-" + who, "X-EAS-Protocol": "2"}

    def rpc(who, method, *args, **kwargs):
        return client.post("/api/worker/" + method, headers=headers(who), json={"args": args, **kwargs})

    return app, client, headers, rpc, policy


def new_job(secured, who="alice"):
    _, client, headers, _, _ = secured
    response = client.post("/api/jobs", headers=headers(who), json={"invoice_id": "INV-1042"})
    response.raise_for_status()
    return response.json()


def proposed(secured):
    app, client, headers, rpc, _ = secured
    job = new_job(secured)
    claimed = rpc("exec-a", "claim", "forged-machine-name")
    assert claimed.status_code == 200
    lease = rpc("exec-a", "lease").json()
    op = CONTRACTS["observe_app"]
    proposal = dict(
        name="observe_app",
        kind="tool",
        arguments={},
        operation_spec=op,
        observation={"revision": "screen-1", "screenshot": "", "state": {}},
        epoch=lease["epoch"],
        signature="test",
        description=op["description"],
        expected=op["expected"],
    )
    invocation = job["id"] + ":call-1"
    a = rpc("exec-a", "proposal", job["id"], invocation, proposal)
    a.raise_for_status()
    approval = a.json()
    client.post(
        "/api/approvals/" + approval["id"], headers=headers("alice"), json={"decision": "approve"}
    ).raise_for_status()
    args = [
        job["id"],
        lease["owner"],
        lease["epoch"],
        invocation,
        {"name": "observe_app", "arguments": {}, "observation_revision": "screen-1"},
        approval["id"],
    ]
    return job, args


def test_person_object_scope_and_aggregates(secured):
    _, c, h, _, _ = secured
    job = new_job(secured)
    for path in [f"/api/jobs/{job['id']}", f"/api/jobs/{job['id']}/episode", f"/api/jobs/{job['id']}/stream"]:
        assert c.get(path, headers=h("bob")).status_code == 404
    assert c.get("/api/jobs", headers=h("bob")).json() == []
    assert c.get("/api/conversations", headers=h("bob")).json() == []
    assert c.get("/api/metrics", headers=h("bob")).json()["simulated"]["jobs"] == 0
    assert c.get(f"/api/jobs/{job['id']}", headers=h("reviewer")).status_code == 200
    assert c.post(f"/api/jobs/{job['id']}/cancel", headers=h("reviewer")).status_code == 404


def test_distinct_desktops_and_no_previous_assignment_access(secured):
    app, c, h, rpc, _ = secured
    alice, bob = new_job(secured), new_job(secured, "bob")
    assert rpc("exec-a", "claim", "process-a").json()["id"] == alice["id"]
    assert rpc("exec-b", "claim", "process-b").json()["id"] == bob["id"]
    assert rpc("exec-a", "lease").json()["job_id"] == alice["id"]
    assert rpc("exec-b", "lease").json()["job_id"] == bob["id"]
    c.post(f"/api/jobs/{alice['id']}/cancel", headers=h("alice")).raise_for_status()
    next_job = new_job(secured)
    assert rpc("exec-a", "claim", "process-a").json()["id"] == next_job["id"]
    assert rpc("planner", "get_job", alice["id"]).status_code == 404
    # Old request detail never discloses a newer request's desktop ownership.
    assert c.get(f"/api/jobs/{alice['id']}", headers=h("alice")).json()["lease"]["job_id"] is None


def test_chat_teaching_publication_needs_admitted_review_and_retains_audience(secured):
    import hashlib
    from eas_shared.identity import canonical
    from eas_shared.skills import SkillSpec

    app, c, h, rpc, _ = secured
    job = new_job(secured)
    rpc("exec-a", "claim", "fixture").raise_for_status()
    store = app.state.store
    store.update_job(job["id"], {"status": "completed"})
    spec = SkillSpec(
        skill_id="chat_lesson",
        title="Response preference",
        description="A staff-taught preference",
        task="Report requested facts",
        instructions="Report only the requested facts; include currency units.",
        application_version=job["app_version"],
        evidence_ids=[job["id"]],
    ).model_dump()
    version = hashlib.sha256(canonical(spec).encode()).hexdigest()
    entry = dict(skill_id=spec["skill_id"], version=version, package=spec, active=True)
    assert rpc("admission", "skills_publish", {"versions": [entry]}).status_code == 403
    with store.db() as db:
        store.queue_chat_review(db, store._job(db, job["id"]))
    claim = rpc("admission", "learning_claim", "fixture").json()
    # A simulated isolated reviewer: the quote is validated against real chat,
    # never presented as a staff assessment or a successful operation.
    result = dict(
        status="activated",
        reason="Simulated reviewer",
        version=version,
        candidate=spec,
        model_mode="simulated",
        signals=[
            dict(
                kind="preference",
                message_id="request:" + job["id"],
                quote=job["task"],
                explanation="Simulated reusable lesson",
            )
        ],
    )
    rpc("admission", "learning_finish", claim["id"], claim["claim_id"], result).raise_for_status()
    rpc("admission", "skills_publish", {"versions": [entry]}).raise_for_status()
    assert not store.get_job(job["id"])["accepted"]
    assert "Response preference" in c.get("/api/learning", headers=h("alice")).text
    assert "Response preference" not in c.get("/api/learning", headers=h("bob")).text
    invented = {**spec, "steps": ["validate", "establish", "compare", "report", "complete"]}
    altered = dict(entry, package=invented, version=hashlib.sha256(canonical(invented).encode()).hexdigest())
    assert rpc("admission", "skills_publish", {"versions": [altered]}).status_code == 403


def test_source_evidence_restricts_private_package_delivery(secured):
    import hashlib
    from eas_shared.identity import canonical
    from eas_shared.skills import SkillSpec

    app, c, h, rpc, _ = secured
    teaching = new_job(secured)
    # Controlled ledger fixture for the audience test; no claim of business verification.
    with app.state.store.db() as db:
        receipt = {
            "id": "fixture-review",
            "job_id": teaching["id"],
            "name": "review_discovery",
            "status": "executed",
        }
        db.execute(
            "INSERT INTO approvals VALUES(?,?,?,?)",
            (receipt["id"], teaching["id"], "fixture-outcome", canonical(receipt)),
        )
    app.state.store.update_job(teaching["id"], {"status": "completed"})
    app.state.store.accept(teaching["id"])
    spec = SkillSpec(
        skill_id="private_lesson",
        title="Private finance method",
        description="Alice's procedure",
        instructions="Use only with current evidence.",
        application_version="mock-1",
        task="Read record",
        evidence_ids=[teaching["id"]],
    ).model_dump()
    version = hashlib.sha256(canonical(spec).encode()).hexdigest()
    item = {**spec, "version": version, "package": spec, "active": True}
    assert rpc("exec-a", "skills_publish", {"versions": [item]}).status_code == 403
    rpc("admission", "skills_publish", {"versions": [item], "history": []}).raise_for_status()
    assert "Private finance method" in c.get("/api/learning", headers=h("alice")).text
    assert "Private finance method" not in c.get("/api/learning", headers=h("bob")).text
    target = new_job(secured, "bob")
    rpc("exec-a", "claim", "process").raise_for_status()
    assert rpc("exec-a", "package_access", target["id"], "private_lesson", version).status_code == 404
    assert (
        c.post("/api/skills/private_lesson/change", headers=h("bob"), json={"version": version}).status_code
        == 404
    )


def test_worker_protocol_cannot_downgrade(secured):
    _, c, h, _, _ = secured
    response = c.post(
        "/api/worker/claim", headers={"Authorization": h("exec-a")["Authorization"]}, json={"args": ["old"]}
    )
    assert response.status_code == 426


def test_learning_claim_cannot_cross_registered_workers(secured):
    app, _, _, rpc, _ = secured
    job = new_job(secured)
    rpc("exec-b", "claim", "process-b").raise_for_status()
    with app.state.store.db() as db:
        app.state.store.queue_learning_review(db, app.state.store._job(db, job["id"]), "test")
    assert rpc("admission", "learning_claim", "desktop-b").json() is None


def test_learning_visibility_inherits_derived_evidence_owner(secured):
    from eas_shared.identity import canonical

    app, c, h, _, _ = secured
    alice, bob = new_job(secured), new_job(secured, "bob")
    own = {
        "id": "own-review",
        "job_id": alice["id"],
        "kind": "learn",
        "status": "completed",
        "result": {"evidence_ids": [alice["id"] + ":comparison"]},
    }
    other = {**own, "id": "restricted-review", "result": {"evidence_ids": [bob["id"] + ":comparison"]}}
    with app.state.store.db() as db:
        for item in (own, other):
            db.execute("INSERT INTO maintenance VALUES(?,?)", (item["id"], canonical(item)))
    queue = c.get("/api/learning", headers=h("alice")).json()["queue"]
    assert [item["id"] for item in queue] == ["own-review"]


def test_skill_read_right_is_not_lifecycle_authority(secured):
    _, c, h, _, _ = secured
    response = c.post(
        "/api/skills/private_lesson/change",
        headers=h("alice"),
        json={"version": "a" * 64, "action": "suspend"},
    )
    assert response.status_code in {403, 404}


def test_admission_cannot_invent_evidence_free_private_package(secured):
    import hashlib
    from eas_shared.identity import canonical
    from eas_shared.skills import SkillSpec

    _, _, _, rpc, _ = secured
    spec = SkillSpec(
        skill_id="invented_private_lesson",
        title="Not a bundled example",
        description="No accepted source",
        instructions="This must never be distributed.",
        application_version="mock-1",
        task="Read a record",
    ).model_dump()
    item = {
        **spec,
        "version": hashlib.sha256(canonical(spec).encode()).hexdigest(),
        "package": spec,
        "active": True,
    }
    assert rpc("admission", "skills_publish", {"versions": [item]}).status_code == 403


def test_role_and_request_identity_are_not_caller_authority(secured):
    _, c, h, _, _ = secured
    assert c.post("/api/jobs", headers=h("sales"), json={"invoice_id": "INV-1042"}).status_code == 403
    assert (
        c.post(
            "/api/jobs", headers=h("alice"), json={"invoice_id": "INV-1042", "permissions": ["admin"]}
        ).status_code
        == 403
    )
    assert (
        c.post(
            "/api/jobs", headers=h("alice"), json={"invoice_id": "INV-1042", "organization_id": "other"}
        ).status_code
        == 403
    )
    assert c.get("/api/roles", headers=h("sales")).json() == []


def test_worker_assignment_and_separate_service_authority(secured):
    _, c, h, rpc, _ = secured
    job = new_job(secured)
    assert rpc("exec-a", "claim", "desktop-b").status_code == 200
    assert rpc("exec-b", "get_job", job["id"]).status_code == 404
    assert rpc("exec-b", "lease").json()["job_id"] is None
    assert rpc("exec-a", "skills_publish", {"versions": []}).status_code == 403
    assert rpc("planner", "begin_action", job["id"], "script", 1, "call", {}, "approval").status_code == 403
    assert rpc("planner", "update_job", job["id"], {"status": "completed"}).status_code == 403
    assert rpc("exec-a", "event", job["id"], "staff_decision", {"decision": "approve"}).status_code == 403
    assert rpc("exec-a", "finish_action", job["id"], "fake", {"value": "success"}).status_code == 403
    assert rpc("exec-a", "update_job", job["id"], {"permissions": ["admin"]}).status_code == 403
    assert c.post("/api/jobs", headers=h("exec-a"), json={"invoice_id": "INV-1042"}).status_code == 403
    assert c.post("/api/mock/action", headers=h("planner"), json={"name": "save"}).status_code == 403


def test_grant_required_bound_and_single_use(secured):
    _, c, h, rpc, _ = secured
    _, args = proposed(secured)
    assert rpc("exec-a", "begin_action", *args).status_code == 409
    response = c.post("/api/execution/grant", headers=h("exec-a"), json={"args": args})
    response.raise_for_status()
    grant = response.json()["grant"]
    altered = list(args)
    altered[4] = {**args[4], "arguments": {"company_id": "OTHER"}}
    assert rpc("exec-a", "begin_action", *altered, grant=grant).status_code == 409
    assert rpc("exec-b", "begin_action", *args, grant=grant).status_code == 404
    assert rpc("exec-a", "begin_action", *args, grant=grant).status_code == 200
    assert rpc("exec-a", "begin_action", *args, grant=grant).status_code == 409


def test_revoked_policy_invalidates_grant_and_identity(secured):
    _, c, h, rpc, path = secured
    _, args = proposed(secured)
    grant = c.post("/api/execution/grant", headers=h("exec-a"), json={"args": args}).json()["grant"]
    registry = json.loads(path.read_text())
    registry["principals"][0]["enabled"] = False
    path.write_text(json.dumps(registry))
    assert c.get("/api/jobs", headers=h("alice")).status_code == 401
    assert rpc("exec-a", "begin_action", *args, grant=grant).status_code == 401


def test_session_is_opaque_csrf_protected_and_revocable(secured):
    _, c, _, _, path = secured
    login = c.post("/api/session", json={"token": "test-alice"})
    login.raise_for_status()
    assert c.cookies["eas_session"] != "test-alice"
    assert c.get("/api/jobs").status_code == 200
    assert c.post("/api/jobs", json={"invoice_id": "INV-1042"}).status_code == 403
    assert (
        c.post(
            "/api/jobs", json={"invoice_id": "INV-1042"}, headers={"X-EAS-CSRF": login.json()["csrf"]}
        ).status_code
        == 200
    )
    registry = json.loads(path.read_text())
    registry["principals"][0]["grants"] = []
    path.write_text(json.dumps(registry))
    assert c.get("/api/jobs").status_code == 401


def test_artifacts_are_bound_to_assignment_and_owner(secured):
    _, c, h, rpc, _ = secured
    job = new_job(secured)
    rpc("exec-a", "claim", "nonce").raise_for_status()
    headers = {**h("exec-a"), "X-EAS-Job": job["id"]}
    name = c.post("/api/worker-artifacts", headers=headers, content=b"\x89PNG\r\n\x1a\nfixture").json()["id"]
    assert c.get("/api/artifacts/" + name, headers=h("alice")).status_code == 200
    assert c.get("/api/artifacts/" + name, headers=h("bob")).status_code == 404
    assert (
        c.post(
            "/api/worker-artifacts",
            headers={**h("exec-b"), "X-EAS-Job": job["id"]},
            content=b"\x89PNG\r\n\x1a\n",
        ).status_code
        == 404
    )
