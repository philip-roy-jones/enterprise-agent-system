"""Simulated Discord transport and staff; no external messages are sent."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from eas_harness.session_context import SessionContext
from eas_server.backend import create_app
from eas_server.config import Settings
from eas_server.conversation import Conversation
from eas_shared.types import Stale


@pytest.fixture
def channel(tmp_path):
    settings = Settings(data_dir=tmp_path, desktop_adapter="browser", model_mode="simulated")
    first = create_app(settings)
    registry = first.state.security.registry().model_dump()
    staff = next(p for p in registry["principals"] if p["id"] == "staff")
    staff["grants"][0]["own_only"] = False
    other = deepcopy(staff)
    other.update(id="teammate", name="Teammate", token_sha256=None)
    registry["principals"].append(other)
    identities = tmp_path / "identities.json"
    identities.write_text(json.dumps(registry))
    bindings = tmp_path / "channels.json"
    bindings.write_text(
        json.dumps(
            [
                {
                    "guild_id": "100",
                    "channel_id": "200",
                    "name": "Finance team",
                    "employee_id": "development-desktop",
                    "organization_id": "acme",
                    "role_id": "invoice_correction",
                    "company_id": "ACME",
                    "members": {"1": "staff", "2": "teammate", "3": "developer"},
                }
            ]
        )
    )
    app = create_app(
        Settings(
            data_dir=tmp_path,
            identity_file=str(identities),
            discord_channels_file=str(bindings),
            desktop_adapter="browser",
            model_mode="simulated",
        )
    )
    security = app.state.security
    security.workforce.change(
        security.get("developer"),
        "development-desktop",
        {"state": "active", "reason": "Simulated supervisor"},
    )
    return app, app.state.channels, app.state.channels.get("200")


def send(channels, b, author="1", message="500", text="Hello"):
    return channels.receive(b, author_id=author, message_id=message, text=text)


def test_shared_channel_attribution_replay_and_context(channel, tmp_path):
    app, channels, b = channel
    first = send(channels, b)
    assert send(channels, b)["id"] == first["id"]
    second = send(channels, b, author="2", message="501", text="My correction")
    assert first["id"] == second["id"]
    msg = Conversation(app.state.store).read(first["id"])["messages"][0]
    assert msg["actor"] == "teammate"
    app.state.store.stop(first["id"])
    assert send(channels, b, author="2", message="501", text="My correction")["id"] == first["id"]
    next_job = send(channels, b, author="2", message="502", text="Now check the next record")
    assert next_job["staff_id"] == "teammate"
    assert SessionContext.scope(first) == SessionContext.scope(next_job)
    private = {**next_job, "communication": None, "conversation_id": "private"}
    assert SessionContext.scope(private) != SessionContext.scope(next_job)
    assert Conversation(app.state.store).read(next_job["id"])["requests"][0]["id"] == first["id"]
    with pytest.raises(ValueError):
        send(channels, b, author="1", message="501", text="Forged correction")


def test_audience_and_authority_fail_closed(channel):
    app, channels, b = channel
    channels.audience(b, ["1", "2", "3"], private=True)
    with pytest.raises(PermissionError):
        channels.audience(b, ["1"], private=False)
    with pytest.raises(PermissionError):
        channels.audience(b, ["1", "999"], private=True)
    with pytest.raises(PermissionError):
        send(channels, b, author="999")
    path = app.state.security.path
    registry = json.loads(path.read_text())
    next(p for p in registry["principals"] if p["id"] == "teammate")["enabled"] = False
    path.write_text(json.dumps(registry))
    with pytest.raises(HTTPException):
        channels.audience(b, ["1", "2"], private=True)
    assert app.state.store.list_jobs() == []


def test_outbound_only_public_messages_and_persisted_cursor(channel):
    app, channels, b = channel
    job = send(channels, b)
    store = app.state.store
    store.event(job["id"], "model_call", {"private": "do not post"})
    store.event(job["id"], "assistant_message_delta", {"text": "partial"})
    store.event(job["id"], "assistant_message", {"text": "@everyone The result"})
    store.event(job["id"], "assistant_question", {"text": "Which record?"})
    items = channels.pending(b)
    assert len(items) == 2 and all(i["text"].startswith("[Simulated employee]") for i in items)
    channels.delivered(items[0]["identity"], "900")
    from eas_server.channels import Channels

    assert len(Channels(app.state.security).pending(b)) == 1
    rebound = b.model_copy(update={"members": {"1": "staff"}})
    assert rebound.conversation_id != b.conversation_id
    assert channels.pending(rebound) == []


def test_discord_web_debug_and_reserved_room_id(channel):
    app, channels, b = channel
    client = TestClient(app)
    headers = {"Authorization": "Bearer local-staff-demo"}
    job = send(channels, b)
    result = client.get("/api/channels", headers=headers).json()
    assert result[0]["conversation_id"] == job["conversation_id"]
    assert client.get("/api/jobs/" + job["id"], headers=headers).status_code == 200
    assert (
        client.post(
            "/api/jobs",
            headers=headers,
            json={
                "conversation_id": b.conversation_id,
                "invoice_id": "INV-1042",
            },
        ).status_code
        == 403
    )


def test_shadow_channel_only_mentor_teaches_and_cannot_execute(channel):
    app, channels, b = channel
    sec = app.state.security
    sec.workforce.change(
        sec.get("developer"), b.employee_id, {"state": "shadowing", "reason": "Simulated mentoring"}
    )
    with pytest.raises(Stale):
        send(channels, b)
    job = sec.workforce.start(
        sec.get("developer"),
        b.employee_id,
        {
            "role_id": b.role_id,
            "company_id": b.company_id,
            "task": "Demonstrate inspection",
            "channel_id": b.channel_id,
        },
        "simulated",
    )
    assert job["conversation_id"] == b.conversation_id
    assert send(channels, b, author="3", text="Watch this field")["id"] == job["id"]
    with pytest.raises(PermissionError):
        send(channels, b, author="1", message="777", text="Click save")
    assert not app.state.store.approvals(job["id"])


def test_discord_delivery_suppresses_mentions_and_uses_retry_nonce(channel, monkeypatch):
    pytest.importorskip("discord")
    from eas_server.discord_bridge import make_client

    client = make_client(channel[1])
    calls = []

    async def request(route, **kwargs):
        calls.append(kwargs)
        return {"id": "900"}

    monkeypatch.setattr(client.http, "request", request)
    asyncio.run(client.send_public(SimpleNamespace(id=200), "event-1", "@everyone result"))
    assert calls[0]["json"]["allowed_mentions"]["parse"] == []
    assert calls[0]["json"]["enforce_nonce"] is True
    assert len(calls[0]["json"]["nonce"]) <= 25


@pytest.mark.browser
def test_console_can_debug_the_same_shared_room(channel):
    from playwright.sync_api import sync_playwright, expect

    app, channels, binding = channel
    job = send(channels, binding, text="Team request visible in the console")
    app.state.store.event(
        job["id"], "model_step", {"call": 1, "available_tools": ["observe_app"], "record_id": None}
    )
    with TestClient(app) as server, sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route(request):
            from urllib.parse import urlsplit

            url = urlsplit(request.request.url)
            if url.path.endswith("/stream"):
                request.fulfill(status=200, body="", content_type="text/event-stream")
                return
            response = server.request(
                request.request.method,
                url.path + ("?" + url.query if url.query else ""),
                headers={"Authorization": "Bearer local-staff-demo"},
                content=request.request.post_data_buffer,
            )
            request.fulfill(
                status=response.status_code,
                body=response.content,
                content_type=response.headers.get("content-type", "text/plain"),
            )

        page.route("**/*", route)
        from eas_server.developer_agents import FLEET_SCOPE
        from eas_server.security import Grant

        registry = json.loads(app.state.security.path.read_text())
        next(p for p in registry["principals"] if p["id"] == "staff")["grants"].append(
            Grant(**FLEET_SCOPE, actions=["inspect_agents"], own_only=False).model_dump()
        )
        app.state.security.path.write_text(json.dumps(registry))
        page.goto("http://testserver/agents/development-desktop")
        page.locator('#chat-workspace option[value="discord/200"]').wait_for(state="attached")
        page.locator("#chat-workspace").select_option("discord/200")
        expect(page.locator("#session-messages")).to_contain_text("Team request visible in the console")
        expect(page.locator("#chat-request")).to_be_disabled()
        page.locator("#debug-mode").click()
        expect(page.locator("#session-messages")).to_contain_text("Model call")
        assert not errors
        browser.close()
