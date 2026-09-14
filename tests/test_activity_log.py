from playwright.sync_api import sync_playwright, expect
from test_agent_led import finish


def test_activity_exposes_tools_errors_and_keeps_expanded_evidence(browser_server):
    ctx = browser_server
    response = ctx["client"].post(
        "/api/chat", json={"invoice_id": "INV-1043", "task": "Report the discrepancy without saving"}
    )
    response.raise_for_status()
    job_id = response.json()["job"]["id"]
    finish(ctx, job_id)
    ctx["store"].event(
        job_id,
        "tool_arguments_rejected",
        {"name": "click", "errors": [{"msg": "Specify a target or both screen coordinates"}]},
    )
    ctx["store"].event(
        job_id, "assistant_message", {"text": "Synthetic explanation <img src=x onerror=alert(1)>"}
    )
    # Another identity's newer request must not become the staff member's
    # transcript or selected execution, even with an old browser selection.
    own_reply = ctx["client"].post("/api/chat", json={"task": "hi"})
    own_reply.raise_for_status()
    latest_id = own_reply.json()["job"]["id"]
    finish(ctx, latest_id)
    other = ctx["client"].post(
        "/api/chat", json={"task": "hello"}, headers={"Authorization": "Bearer test-developer"}
    )
    other.raise_for_status()
    foreign_id = other.json()["job"]["id"]
    import httpx

    with httpx.Client(base_url=ctx["url"], headers={"Authorization": "Bearer test-developer"}) as developer:
        finish({**ctx, "client": developer}, foreign_id)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(extra_http_headers={"Authorization": "Bearer test-staff"})
        page.add_init_script(f"localStorage.setItem('active-job', '{foreign_id}')")
        errors = []
        requested = []
        page.on("request", lambda request: requested.append(request.url))
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(ctx["url"])
        expect(page.get_by_role("heading", name="Recent activity", exact=True)).to_have_count(0)
        expect(page.locator("#job-id")).to_contain_text(latest_id[:8])
        own_activity = page.locator(f'[data-request-activity="{job_id}"]')
        expect(own_activity).to_be_visible()
        expect(page.locator(f'[data-request-activity="{foreign_id}"]')).to_have_count(0)
        assert not any(f"/api/jobs/{foreign_id}" in url for url in requested)
        own_activity.click()
        expect(page.locator("#job-id")).to_contain_text(latest_id[:8])
        transcript = page.locator("#session-messages")
        expect(transcript).to_contain_text("Simulated model")
        call = transcript.locator(".chat-debug-event").filter(has_text="run_operation → establish").first
        expect(call).to_be_visible()
        call.locator("summary").first.click()
        expect(call).to_contain_text('"operation": "establish"')
        payload = call.locator(".activity-payload")
        payload.locator("summary").click()
        ctx["store"].event(
            job_id, "staff_note", {"text": "Synthetic new activity while evidence is expanded"}
        )
        page.wait_for_timeout(3000)
        expect(call).to_have_attribute("open", "")
        expect(payload).to_have_attribute("open", "")
        expect(transcript).to_contain_text("Invalid proposal — nothing executed")
        expect(transcript).to_contain_text("Specify a target or both screen coordinates")
        expect(transcript).to_contain_text("<img src=x onerror=alert(1)>")
        expect(
            transcript.locator(".chat-debug-event").filter(has_text="Synthetic explanation")
        ).to_have_count(0)
        assert transcript.locator("img").count() == 0 and not errors
        assert not any(f"/api/jobs/{foreign_id}" in url for url in requested)
        page.reload()
        expect(page.locator("#job-id")).to_contain_text(latest_id[:8])
        browser.close()


def test_learning_view_shows_changes_evidence_and_proposals_without_executing(browser_server):
    from test_learning_feedback import guidance

    spec = guidance()
    version = {**spec, "version": "a" * 64, "active": True, "resources": list(spec["supporting_files"])}
    state = {
        "registries": [{"versions": [version], "history": []}],
        "queue": [
            {
                "id": "fixture-review",
                "kind": "learn",
                "status": "completed",
                "job_id": "episode-1",
                "result": {
                    "status": "activated",
                    "model_mode": "simulated",
                    "reason": "Synthetic staff correction teaches verification.",
                    "changes": {
                        "steps_before": [],
                        "steps_after": [],
                        "labels_before": [],
                        "labels_after": [],
                        "instructions_diff": "+ Re-observe before reporting <script>unsafe()</script>",
                        "resources_changed": ["references/verification.md"],
                    },
                    "checks": {
                        "suite": "guidance-contract-1",
                        "model_mode": "none",
                        "checks": [{"case": "scoped package", "passed": True}],
                        "behavioral_evaluation": "not performed",
                    },
                    "recommendations": [
                        {
                            "kind": "development_request",
                            "skill_ids": [],
                            "evidence_ids": ["episode-1"],
                            "reason": "A missing export operation requires development.",
                        }
                    ],
                },
            }
        ],
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(extra_http_headers={"Authorization": "Bearer test-staff"})
        page.route("**/api/learning", lambda route: route.fulfill(json=state))
        writes = []
        page.on("request", lambda request: writes.append(request.url) if request.method == "POST" else None)
        page.goto(browser_server["url"])
        page.locator("#learning-panel > details > summary").click()
        review = page.locator('[data-learning-id="review-fixture-review"]')
        review.locator("summary").first.click()
        expect(review).to_contain_text("What changed")
        expect(review).to_contain_text("not performed")
        expect(review).to_contain_text("Proposed development request")
        expect(review).to_contain_text("<script>unsafe()</script>")
        assert page.locator("#learning-content script").count() == 0
        page.wait_for_timeout(3000)
        expect(review).to_have_attribute("open", "")
        assert not writes
        browser.close()
