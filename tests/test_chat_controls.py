"""Chat controls with simulated staff/model and controlled historical outcomes."""

import pytest
from playwright.sync_api import expect, sync_playwright

from conftest import wait_for
from eas_shared.types import JobInput


@pytest.mark.browser
def test_chat_controls_and_acceptance_stay_bound_to_their_request(browser_server):
    client, store = browser_server["client"], browser_server["store"]
    session = client.get("/api/chat?role_id=invoice_correction").json()
    completed = []
    for task, kind in [
        ("Earlier reviewed result", "verified_work"),
        ("Earlier greeting", "conversation"),
        ("Another result awaiting acceptance", "verified_work"),
    ]:
        job = store.create_job(
            JobInput(task=task, conversation_id=session["conversation_id"]).model_dump(), ongoing=True
        )
        store.update_job(job["id"], {"status": "completed", "result_kind": kind})
        store.event(job["id"], "assistant_message", {"text": f"Simulated answer: {task}"})
        completed.append(job)
    import signal

    browser_server["worker"].send_signal(signal.SIGSTOP)
    response = client.post(
        "/api/chat", json={"invoice_id": "INV-1043", "task": "Report the discrepancy without saving"}
    )
    response.raise_for_status()
    job_id = response.json()["job"]["id"]
    # Hold the test worker to inspect control/acceptance UI without racing Auto.
    from eas_server.store import desktop_context

    token = desktop_context.set("development-desktop")
    try:
        store.claim("simulated-control-fixture")
    finally:
        desktop_context.reset(token)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(extra_http_headers={"Authorization": "Bearer test-staff"})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(browser_server["url"])
            expect(page.locator("#chat-composer #chat-controls")).to_be_visible()
            expect(page.locator("#review-panel")).to_have_count(0)
            expect(
                page.locator("#active-job, #job-id, #job-title, #job-status, #empty, #message-form")
            ).to_have_count(0)
            transcript = page.locator("#session-messages")
            accept = transcript.locator(f'[data-accept-request="{completed[0]["id"]}"]')
            expect(accept).to_be_attached()
            expect(transcript.locator(f'[data-accept-request="{completed[1]["id"]}"]')).to_have_count(0)
            with page.expect_response(f"**/api/jobs/{completed[0]['id']}/accept") as accepted:
                accept.click()
            assert accepted.value.status == 200
            expect(accept).to_have_count(0)
            assert store.get_job(completed[0]["id"])["accepted"]
            assert not store.get_job(job_id)["accepted"]
            assert client.get("/api/chat?role_id=invoice_correction").json()["current"]["id"] == job_id
            assert page.evaluate("active") == job_id

            takeover = page.locator("#takeover")
            with page.expect_response(f"**/api/jobs/{job_id}/takeover") as handoff:
                takeover.click()
            assert handoff.value.status == 200
            expect(takeover).to_have_text("Release control")
            assert client.get(f"/api/jobs/{job_id}").json()["lease"]["owner"] == "staff"
            expect(page.locator("#review-panel")).to_be_hidden()
            store.update_job(job_id, {"error": "Simulated UI lookup failure <script>unsafe()</script>"})
            expect(transcript).to_contain_text("The worker needs help to continue.")
            expect(transcript).not_to_contain_text("Simulated UI lookup failure")
            page.locator("#debug-mode").click()
            execution = transcript.locator(f'[data-message-id="execution-{job_id}"]')
            execution.locator("summary").click()
            expect(execution).to_contain_text(job_id)
            expect(execution).to_contain_text("skill_runs")
            expect(execution).to_contain_text("Simulated UI lookup failure")
            expect(execution.locator("script")).to_have_count(0)
            page.locator("#debug-mode").click()
            store.update_job(job_id, {"error": None})

            with page.expect_response(f"**/api/jobs/{job_id}/release") as released:
                takeover.click()
            assert released.value.status == 200
            expect(takeover).to_have_text("Take control")
            expect(page.locator("#review-panel")).to_have_count(0)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            with page.expect_response(f"**/api/jobs/{job_id}/cancel") as cancelled:
                page.locator("#cancel-job").click()
            assert cancelled.value.status == 200
            expect(page.locator("#chat-controls")).to_be_hidden()
            expect(page.locator("#review-panel")).to_be_hidden()
            expect(transcript).to_contain_text("Work stopped.")
            assert store.get_job(job_id)["status"] == "cancelled"
            browser_server["worker"].send_signal(signal.SIGCONT)
            page.locator("#chat-request").fill("Hello")
            with page.expect_response("**/api/chat") as greeting_response:
                page.locator("#chat-form button.primary").click()
            assert greeting_response.value.status == 200
            greeting_id = greeting_response.value.json()["job"]["id"]
            wait_for(client, greeting_id, lambda data: data["job"]["status"] == "completed")
            expect(transcript).to_contain_text("Simulated conversational reply", timeout=15000)
            expect(page.locator("#chat-controls")).to_be_hidden()
            expect(transcript.locator(f'[data-accept-request="{greeting_id}"]')).to_have_count(0)
            expect(transcript.locator(f'[data-accept-request="{job_id}"]')).to_have_count(0)
            # Other completed work can still await acceptance in the same chat.
            expect(transcript.locator(f'[data-accept-request="{completed[2]["id"]}"]')).to_be_attached()
            assert not errors
        finally:
            browser_server["worker"].send_signal(signal.SIGCONT)
            browser.close()
            if store.get_job(job_id)["status"] not in {
                "completed",
                "cancelled",
                "failed",
                "denied",
                "rejected",
            }:
                client.post(f"/api/jobs/{job_id}/cancel").raise_for_status()
