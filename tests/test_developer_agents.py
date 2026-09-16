"""Developer inventory is global; business permissions remain scoped (simulated identities)."""

import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from eas_server.backend import create_app
from eas_server.config import Settings
from eas_shared.types import JobInput


@pytest.fixture
def inventory(tmp_path):
    settings = Settings(data_dir=tmp_path, desktop_adapter="none", model_mode="simulated")
    initial = create_app(settings)
    registry = initial.state.security.registry().model_dump()
    for person in registry["principals"]:
        for grant in person["grants"]:
            if "inspect_agents" not in grant["actions"]:
                grant.update(department_id="finance", role_id="invoice_correction")
    executor = next(p for p in registry["principals"] if p["kind"] == "executor")
    marketing = deepcopy(executor)
    marketing.update(
        id="marketing-service", worker_id="marketing-edge", name="Marketing agent", token_sha256=None
    )
    marketing["grants"][0].update(department_id="marketing", role_id="campaign_review", capabilities=["read"])
    disabled = deepcopy(executor)
    disabled.update(
        id="disabled-service",
        worker_id="disabled-edge",
        name="Disabled agent",
        enabled=False,
        token_sha256=None,
    )
    registry["principals"].extend([marketing, disabled])
    path = tmp_path / "identities.json"
    path.write_text(json.dumps(registry))
    app = create_app(Settings(data_dir=tmp_path, desktop_adapter="none", identity_file=str(path)))
    return app, TestClient(app, headers={"Authorization": "Bearer local-developer-demo"}), path


def test_inventory_includes_all_agents_without_granting_business_access(inventory):
    app, client, _ = inventory
    result = client.get("/api/dev/agents")
    result.raise_for_status()
    rows = {e["id"]: e for e in result.json()}
    assert set(rows) == {"development-desktop", "marketing-edge", "disabled-edge"}
    assert rows["disabled-edge"]["enabled"] is False
    assert not rows["marketing-edge"]["can_supervise"]
    assert "token_sha256" not in result.text
    assert [e["id"] for e in client.get("/api/employees").json()] == ["development-desktop"]
    assert (
        client.post(
            "/api/employees/marketing-edge/state",
            json={"state": "active", "reason": "Unauthorized promotion"},
        ).status_code
        == 403
    )
    assert client.get("/api/chat?employee_id=marketing-edge&role_id=campaign_review").status_code == 403
    assert client.get("/api/dev/agents/marketing-edge").json()["id"] == "marketing-edge"
    assert client.get("/api/dev/agents/missing").status_code == 404
    # Deep links serve an empty shell; data still requires the developer permission.
    for route in ("/", "/agents/marketing-edge", "/metrics"):
        assert client.get(route).status_code == 200
    for actor in ("staff", "worker"):
        assert (
            client.get(
                "/api/dev/agents", headers={"Authorization": "Bearer local-" + actor + "-demo"}
            ).status_code
            == 403
        )


def test_inventory_permission_is_revocable(inventory):
    _, client, path = inventory
    assert client.get("/api/dev/agents").status_code == 200
    registry = json.loads(path.read_text())
    for p in registry["principals"]:
        p["grants"] = [g for g in p["grants"] if "inspect_agents" not in g["actions"]]
    path.write_text(json.dumps(registry))
    assert client.get("/api/dev/agents").status_code == 403


def test_learning_reviews_are_filtered_by_agent_after_authorization(inventory):
    app, client, _ = inventory
    for employee in ("development-desktop", "disabled-edge"):
        job = app.state.store.create_job(
            JobInput(employee_id=employee, invoice_id="INV-1042").model_dump(), staff_id="developer"
        )
        with app.state.store.db() as db:
            app.state.store.queue_learning_review(db, job, "simulated_feedback")
    all_rows = client.get("/api/learning").json()["queue"]
    selected = client.get("/api/learning?employee_id=development-desktop").json()["queue"]
    assert len(all_rows) == 2 and len(selected) == 1
    assert app.state.store.get_job(selected[0]["job_id"])["employee_id"] == "development-desktop"


@pytest.mark.browser
def test_directory_and_agent_pages_support_deep_links_and_revocation(inventory):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright, expect

    _, client, path = inventory
    requests = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def route(route):
            url = urlsplit(route.request.url)
            requests.append(url.path)
            if url.path.endswith("/stream"):
                route.fulfill(status=200, content_type="text/event-stream", body="")
                return
            result = client.request(
                route.request.method,
                url.path + ("?" + url.query if url.query else ""),
                content=route.request.post_data_buffer,
            )
            route.fulfill(
                status=result.status_code,
                body=result.content,
                content_type=result.headers.get("content-type", "text/plain"),
            )

        page.route("**/*", route)
        page.goto("http://testserver/")
        expect(page.locator(".agent-card")).to_have_count(3)
        expect(page.locator("#chat-composer")).to_be_hidden()
        expect(page.locator("#jobs-tab")).to_have_attribute("aria-current", "page")
        assert (
            page.locator("#jobs-tab").evaluate("e => getComputedStyle(e).backgroundColor")
            != "rgba(0, 0, 0, 0)"
        )
        assert "/api/jobs" not in requests and "/api/learning" not in requests
        page.locator('a.agent-card[href="/agents/marketing-edge"]').click()
        expect(page).to_have_url("http://testserver/agents/marketing-edge")
        expect(page.locator("h1")).to_have_text("Marketing agent")
        expect(page.locator("#agent-conversation-unavailable")).to_be_visible()
        expect(page.locator("#chat-composer")).to_be_hidden()
        page.locator("#agent-details > summary").click()
        expect(page.locator("#agent-details-content")).to_contain_text("marketing-service")
        page.reload()
        expect(page.locator("h1")).to_have_text("Marketing agent")
        page.locator("#agent-back").click()
        page.locator('a.agent-card[href="/agents/development-desktop"]').click()
        expect(page.locator("#chat-composer")).to_be_visible()
        expect(page.locator("#employee-management")).to_be_visible()
        expect(page.locator("#conversation-picker")).to_be_hidden()
        assert page.locator("#chat-workspace option").count() == 1
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.locator("#metrics-tab").click()
        expect(page).to_have_url("http://testserver/metrics")
        expect(page.locator("#metrics-tab")).to_have_attribute("aria-current", "page")
        expect(page.locator("#metrics-view table")).to_be_visible()
        page.goto("http://testserver/agents/missing")
        expect(page.locator("#agent-unavailable-title")).to_have_text("Agent not found")
        expect(page.locator("#chat-composer")).to_be_hidden()
        page.goto("http://testserver/")
        expect(page.locator(".agent-card")).to_have_count(3)
        registry = json.loads(path.read_text())
        for person in registry["principals"]:
            person["grants"] = [g for g in person["grants"] if "inspect_agents" not in g["actions"]]
        path.write_text(json.dumps(registry))
        page.evaluate("refresh()")
        expect(page.locator("#agent-unavailable-title")).to_have_text("Developer access required")
        expect(page.locator(".agent-card")).to_have_count(0)
        assert not errors
        browser.close()
