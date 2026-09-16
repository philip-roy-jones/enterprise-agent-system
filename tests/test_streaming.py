"""Public streaming behavior with a simulated model and simulated staff."""

import threading
from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langgraph.checkpoint.memory import InMemorySaver
from eas_harness.coordinator import Coordinator, SimulatedCoordinator
from eas_harness.execution import ExecutionLayer
from eas_harness.streaming import PUBLIC_CHAT, stream_agent
from eas_shared.types import JobInput
from test_chat_records import NoDesktop


def test_coordinator_emits_text_before_model_finishes_and_keeps_one_final_reply(store, tmp_path, monkeypatch):
    release = threading.Event()
    received = threading.Event()
    errors = []
    original_event = store.event

    def event(job_id, kind, data):
        original_event(job_id, kind, data)
        if kind == "assistant_message_delta":
            received.set()

    monkeypatch.setattr(store, "event", event)

    class StreamingModel(SimulatedCoordinator):
        def _stream(self, messages, **kwargs):
            yield ChatGenerationChunk(message=AIMessageChunk(content="Hello"))
            assert release.wait(5), "Test did not receive the first chunk before generation ended"
            yield ChatGenerationChunk(message=AIMessageChunk(content=" there."))

    monkeypatch.setattr("eas_harness.coordinator.SimulatedCoordinator", StreamingModel)
    job = store.create_job(JobInput(task="Hello").model_dump(), ongoing=True)
    store.claim("simulated-worker")
    coordinator = Coordinator(
        SimpleNamespace(
            data_dir=tmp_path, model_mode="simulated", model_provider="", model_id="", max_model_calls=3
        ),
        store,
        ExecutionLayer(store, NoDesktop()),
        InMemorySaver(),
        InMemorySaver(),
    )

    def run():
        try:
            coordinator.tick(store.get_job(job["id"]))
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert received.wait(5), errors
        assert not any(e["kind"] == "assistant_message" for e in store.events(job["id"]))
    finally:
        release.set()
        thread.join(10)
    assert not errors and not thread.is_alive()
    events = store.events(job["id"])
    parts = [e["data"] for e in events if e["kind"] == "assistant_message_delta"]
    final = [e["data"] for e in events if e["kind"] == "assistant_message"]
    assert len(final) == 1 and final[0]["text"] == "Hello there."
    assert "".join(p["text"] for p in parts) == final[0]["text"]
    assert {p["message_id"] for p in parts} == {final[0]["message_id"]}
    assert store.get_job(job["id"])["status"] == "completed"
    assert not store.approvals(job["id"])


def test_partial_failure_excludes_reasoning_tool_arguments_and_other_models(store, job):
    class Graph:
        def stream(self, *args, **kwargs):
            metadata = {"tags": [PUBLIC_CHAT], "langgraph_node": "model"}
            yield (
                "messages",
                (AIMessageChunk(id="private", content="private judgment"), {**metadata, "tags": []}),
            )
            yield (
                "messages",
                (
                    AIMessageChunk(id="nested", content="private tool result"),
                    {**metadata, "langgraph_node": "tools"},
                ),
            )
            yield (
                "messages",
                (
                    AIMessageChunk(
                        id="answer",
                        content=[
                            {"type": "reasoning", "reasoning": "private reasoning"},
                            {"type": "text", "text": "Checking"},
                        ],
                        tool_call_chunks=[
                            {"name": "tool", "args": '{"private":"arguments"}', "id": "tool-call", "index": 0}
                        ],
                    ),
                    metadata,
                ),
            )
            raise RuntimeError("Simulated provider disconnection")

    with pytest.raises(RuntimeError, match="disconnection"):
        stream_agent(Graph(), {}, {}, store, job["id"])
    events = store.events(job["id"])
    parts = [e["data"] for e in events if e["kind"] == "assistant_message_delta"]
    assert parts == [{"message_id": "answer", "text": "Checking"}]
    assert any(e["kind"] == "assistant_stream_end" for e in events)
    assert not any(e["kind"] == "assistant_message" for e in events)


@pytest.mark.browser
def test_browser_streams_reconnects_and_recovers_partial_text(browser_server):
    server = browser_server
    import json
    import httpx
    from playwright.sync_api import sync_playwright, expect

    store = server["store"]
    # Hold the synthetic desktop so the fixture worker cannot complete the
    # request while this controlled stream exercises the real SSE transport.
    session = server["client"].get("/api/chat?role_id=invoice_correction").json()
    job = store.create_job(
        JobInput(task="Explain this workspace", conversation_id=session["conversation_id"]).model_dump(),
        ongoing=True,
    )
    store.claim("stream-fixture")
    lease = store.lease()
    store.transfer(job["id"], "staff", lease["epoch"])
    first = {"message_id": "stream-browser", "text": "Here is"}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(extra_http_headers={"Authorization": "Bearer test-staff"})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(server["url"])
        page.locator("#chat-request").wait_for()
        page.wait_for_function("id => active === id && renderedSession !== null", arg=job["id"])
        # Disable polling: token updates must arrive through SSE itself.
        page.evaluate("window.refresh = async () => {}")
        store.event(job["id"], "assistant_message_delta", first)
        bubble = page.locator('[data-message-id="reply-stream-browser"]')
        expect(bubble.locator("p")).to_have_text("Here is")
        expect(bubble.locator(".stream-status")).to_have_text("Responding…")
        assert not any(e["kind"] == "assistant_message" for e in store.events(job["id"]))
        page.evaluate("source.close()")
        store.event(job["id"], "assistant_message_delta", {**first, "text": " the answer."})
        page.evaluate("connectStream()")
        expect(bubble.locator("p")).to_have_text("Here is the answer.")
        store.event(job["id"], "assistant_message", {**first, "text": "Here is the answer."})
        store.event(job["id"], "assistant_stream_end", {"message_id": first["message_id"]})
        expect(bubble).to_have_count(1)
        expect(bubble.locator(".stream-status")).to_have_count(0)
        store.event(
            job["id"],
            "assistant_message_delta",
            {"message_id": "interrupted", "text": "<script>unsafe()</script>"},
        )
        store.event(job["id"], "assistant_stream_end", {"message_id": "interrupted"})
        partial = page.locator('[data-message-id="reply-interrupted"]')
        expect(partial.locator(".stream-status")).to_have_text("Response interrupted")
        assert partial.locator("script").count() == 0
        page.reload()
        expect(page.locator('[data-message-id="reply-stream-browser"] p')).to_have_text("Here is the answer.")
        expect(page.locator('[data-message-id="reply-stream-browser"]')).to_have_count(1)
        expect(page.locator('[data-message-id="reply-interrupted"] .stream-status')).to_have_text(
            "Response interrupted"
        )
        assert not errors
        browser.close()
    rows = store.events(job["id"])
    cursor = next(e["seq"] for e in rows if e["kind"] == "assistant_message_delta")
    with httpx.Client(base_url=server["url"], headers={"Authorization": "Bearer test-staff"}) as client:
        with client.stream(
            "GET", f"/api/jobs/{job['id']}/stream?after=0", headers={"Last-Event-ID": str(cursor)}
        ) as response:
            assert response.headers["x-accel-buffering"] == "no"
            row = next(json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: "))
            assert row["seq"] > cursor
        assert (
            client.get(f"/api/jobs/{job['id']}/stream", headers={"Last-Event-ID": "invalid"}).status_code
            == 400
        )
    server["client"].post(f"/api/jobs/{job['id']}/cancel").raise_for_status()


def test_streamed_tool_arguments_finish_before_the_stateful_approval(store, tmp_path, monkeypatch):
    class StreamingModel(SimulatedCoordinator):
        def _stream(self, messages, **kwargs):
            yield ChatGenerationChunk(message=AIMessageChunk(content="Checking the requested record."))
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": "select_record",
                            "args": '{"invoice_id":"INV-',
                            "id": "select-one",
                            "index": 0,
                        }
                    ],
                )
            )
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="", tool_call_chunks=[{"name": None, "args": '1042"}', "id": None, "index": 0}]
                )
            )

    monkeypatch.setattr("eas_harness.coordinator.SimulatedCoordinator", StreamingModel)
    job = store.create_job(JobInput(task="Check invoice INV-1042").model_dump(), ongoing=True)
    store.claim("simulated-worker")
    coordinator = Coordinator(
        SimpleNamespace(
            data_dir=tmp_path, model_mode="simulated", model_provider="", model_id="", max_model_calls=3
        ),
        store,
        ExecutionLayer(store, NoDesktop()),
        InMemorySaver(),
        InMemorySaver(),
    )
    from conftest import staged_authorization

    with staged_authorization(store, handled=True):
        coordinator.tick(store.get_job(job["id"]))
    approvals = store.approvals(job["id"])
    assert len(approvals) == 1 and approvals[0]["status"] == "authorized"
    assert approvals[0]["arguments"] == {"invoice_id": "INV-1042"}
    events = store.events(job["id"])
    assert not any(e["kind"] == "action_started" for e in events)
    assert (
        "".join(e["data"]["text"] for e in events if e["kind"] == "assistant_message_delta")
        == "Checking the requested record."
    )
    store.stop(job["id"])
    assert store.get_job(job["id"])["status"] == "cancelled"
    assert store.get_job(job["id"])["record_id"] is None
