"""Inline debugging with controlled events and simulated staff; no live model."""

import pytest
from playwright.sync_api import expect, sync_playwright

from eas_shared.types import JobInput


@pytest.mark.browser
def test_chat_debug_history_streaming_and_reload(browser_server):
    store = browser_server["store"]
    client = browser_server["client"]
    session = client.get("/api/chat?role_id=invoice_correction").json()
    earlier = store.create_job(
        JobInput(task="Earlier simulated request", conversation_id=session["conversation_id"]).model_dump(),
        ongoing=True,
    )
    store.update_job(earlier["id"], {"status": "completed", "model_calls": 1})
    store.event(earlier["id"], "model_step", {"call": 1, "available_tools": ["read_skill"]})
    store.event(
        earlier["id"],
        "agent_tool_call",
        {"name": "read_skill", "invocation": "previous-read", "arguments": {"skill_id": "invoice_report"}},
    )
    previous_call = store.events(earlier["id"])[-1]
    store.event(earlier["id"], "agent_tool_result", {"name": "read_skill", "result": "Simulated skill text"})
    store.event(
        earlier["id"],
        "model_response",
        {"call": 1, "tokens": 42, "tool_calls": [], "public_summary": ["Earlier simulated answer"]},
    )
    model_response = store.events(earlier["id"])[-1]
    store.event(earlier["id"], "assistant_message", {"text": "Earlier simulated answer"})
    earlier_answer = store.events(earlier["id"])[-1]

    foreign = store.create_job(
        JobInput(task="Other staff private request").model_dump(), staff_id="developer", ongoing=True
    )
    store.update_job(foreign["id"], {"status": "completed"})
    store.event(foreign["id"], "agent_tool_result", {"name": "Private staff tool result"})

    job = store.create_job(
        JobInput(task="Current simulated request", conversation_id=session["conversation_id"]).model_dump(),
        ongoing=True,
    )
    store.claim("debug-fixture")
    lease = store.lease()
    store.transfer(job["id"], "staff", lease["epoch"])
    store.event(
        job["id"],
        "agent_tool_call",
        {
            "name": "run_operation",
            "invocation": "current-call",
            "arguments": {"operation": "observe", "note": "<script>unsafe()</script>"},
        },
    )
    current_call = store.events(job["id"])[-1]
    current_selector = f'[data-message-id="debug-{job["id"]}-{current_call["seq"]}"]'
    previous_selector = f'[data-message-id="debug-{earlier["id"]}-{previous_call["seq"]}"]'

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(extra_http_headers={"Authorization": "Bearer test-staff"})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(browser_server["url"])
            page.wait_for_function("id => active === id && renderedSession !== null", arg=job["id"])
            toggle = page.locator("#debug-mode")
            transcript = page.locator("#session-messages")
            expect(toggle).to_have_attribute("aria-pressed", "false")
            expect(
                page.locator("#debug-controls, #activity-filter, #activity-search, #activity-counts")
            ).to_have_count(0)
            expect(transcript.locator(".chat-debug-event")).to_have_count(0)
            expect(page.locator("#timeline")).to_have_count(0)
            toggle.click()
            expect(toggle).to_have_attribute("aria-pressed", "true")
            expect(page.locator(previous_selector)).to_be_attached()
            expect(transcript).not_to_contain_text("Other staff private request")
            expect(transcript).not_to_contain_text("Private staff tool result")
            expect(transcript.locator(f'a[href="/api/jobs/{earlier["id"]}/episode"]')).to_have_count(1)
            expect(transcript).to_contain_text("Simulated model")
            response_row = page.locator(f'[data-message-id="debug-{earlier["id"]}-{model_response["seq"]}"]')
            response_row.locator(":scope > summary").click()
            response_row.locator(".activity-payload summary").click()
            expect(response_row).to_contain_text('"tokens": 42')
            expect(response_row).not_to_contain_text("Earlier simulated answer")
            expect(response_row).not_to_contain_text("public_summary")
            assert transcript.text_content().count("Earlier simulated answer") == 1
            assert model_response["data"]["public_summary"] == ["Earlier simulated answer"]
            order = transcript.locator(":scope > [data-message-id]").evaluate_all(
                "nodes => nodes.map(node => node.dataset.messageId)"
            )
            assert (
                order.index(f"request-{earlier['id']}")
                < order.index(f"debug-{earlier['id']}-{previous_call['seq']}")
                < order.index(f"event-{earlier_answer['seq']}")
                < order.index(f"request-{job['id']}")
            )

            current = page.locator(current_selector)
            current.locator(":scope > summary").click()
            expect(current).to_contain_text("Proposed arguments")
            expect(current).to_contain_text("<script>unsafe()</script>")
            expect(current.locator("script")).to_have_count(0)
            payload = current.locator(".activity-payload")
            payload.locator("summary").click()
            expect(payload).to_have_attribute("open", "")
            current.evaluate("node => { window.savedDebugRow = node; }")

            # SSE must deliver both new activity and text with polling disabled.
            page.evaluate("window.refresh = async () => {}")
            store.event(job["id"], "record_unavailable", {"message": "Simulated missing record"})
            expect(transcript).to_contain_text("Simulated missing record")
            store.event(
                job["id"], "assistant_message_delta", {"message_id": "debug-reply", "text": "Checking"}
            )
            reply = transcript.locator('[data-message-id="reply-debug-reply"]')
            expect(reply.locator("p")).to_have_text("Checking")
            expect(current).to_have_attribute("open", "")
            expect(payload).to_have_attribute("open", "")
            assert current.evaluate("node => node === window.savedDebugRow")
            store.event(
                job["id"], "assistant_message", {"message_id": "debug-reply", "text": "Checking done."}
            )
            expect(reply.locator("p")).to_have_text("Checking done.")
            expect(reply).to_have_count(1)
            expect(
                transcript.locator(".chat-debug-event").filter(has_text="assistant message delta")
            ).to_have_count(0)

            toggle.click()
            expect(transcript.locator(".chat-debug-event")).to_have_count(0)
            expect(reply).to_have_count(1)
            toggle.click()
            expect(current).to_have_attribute("open", "")
            expect(current.locator(".activity-payload")).to_have_attribute("open", "")
            toggle.click()
            expect(transcript.locator(".chat-debug-event")).to_have_count(0)
            transcript.locator(f'[data-request-activity="{earlier["id"]}"]').click()
            expect(toggle).to_have_attribute("aria-pressed", "true")
            assert page.evaluate("active") == job["id"]
            page.wait_for_function(
                "selector => { const node = document.querySelector(selector); "
                "const box = node.closest('.session-messages').getBoundingClientRect(); "
                "const row = node.getBoundingClientRect(); return row.bottom > box.top && row.top < box.bottom; }",
                arg=previous_selector,
            )
            page.reload()
            expect(toggle).to_have_attribute("aria-pressed", "true")
            expect(page.locator(previous_selector)).to_be_attached()
            expect(reply).to_have_count(1)
            page.set_viewport_size({"width": 390, "height": 844})
            current.locator(":scope > summary").click()
            current.locator(".activity-payload summary").click()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            assert not errors
        finally:
            browser.close()
            client.post(f"/api/jobs/{job['id']}/cancel").raise_for_status()
