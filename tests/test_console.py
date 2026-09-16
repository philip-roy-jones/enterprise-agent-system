import pytest
from playwright.sync_api import sync_playwright
from enterprise_dev.demo import drive

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("failure", ["network", "inflight"])
def test_failed_refresh_never_relabels_historical_state_as_fresh(browser_server, failure):
    from eas_harness.adapters.adapter import BrowserAdapter
    from eas_shared.types import Recovery

    adapter = BrowserAdapter(browser_server["settings"], browser_server["store"])
    try:
        original = adapter.observe()
        assert original.state["app_version"] == "mock-1"
        if failure == "network":
            adapter.page.route("**/api/mock/state", lambda route: route.abort())
        else:
            adapter.page.evaluate("busy = true")
        with pytest.raises(Recovery, match="fresh accounting observation"):
            adapter.observe()
    finally:
        adapter.close()


def test_chat_replaces_assessment_form_and_existing_assessments_remain_in_metrics(browser_server):
    c = browser_server["client"]
    response = c.post(
        "/api/chat", json={"invoice_id": "INV-1042", "task": "invoice_correction", "selected_mode": "auto"}
    )
    response.raise_for_status()
    job_id = response.json()["job"]["id"]
    drive(c, job_id)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(extra_http_headers={"Authorization": "Bearer test-staff"})
        page = context.new_page()
        page.goto(browser_server["url"] + "/agents/development-desktop")
        page.locator("#chat-request").wait_for()
        assert page.locator("#assessment-form").count() == 0
        assert not page.locator("#review-panel").is_visible()
        detail = c.get(f"/api/jobs/{job_id}").json()
        invocation = next(e["data"]["invocation"] for e in detail["events"] if e["kind"] == "action_result")
        # Historical/operator assessment API remains supported; staff no longer
        # need its form to teach through ordinary conversation.
        c.post(
            f"/api/jobs/{job_id}/assessments",
            json={
                "invocation": invocation,
                "outcome": "incorrect",
                "explanation": "Synthetic historical assessment",
            },
        ).raise_for_status()
        page.locator("#metrics-tab").click()
        page.locator("#metrics-tab[aria-current=page]").wait_for()
        row = page.locator("#metrics-view tr").filter(has_text="incorrect actions reported")
        row.wait_for()
        assert row.locator("td").nth(1).inner_text() == "1"
        assert page.locator("#metrics-view").inner_text().find("unassessed actions") >= 0
        page.screenshot(path=str(browser_server["data_dir"] / "assessment-console.png"))
        browser.close()
