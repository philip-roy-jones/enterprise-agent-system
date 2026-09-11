import pytest
from playwright.sync_api import sync_playwright
from enterprise.development.demo import drive

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("failure", ["network", "inflight"])
def test_failed_refresh_never_relabels_historical_state_as_fresh(browser_server, failure):
    from enterprise.harness.adapters.adapter import BrowserAdapter
    from enterprise.shared.types import Recovery

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


def test_staff_assessment_updates_metrics_in_rendered_console(browser_server):
    c = browser_server["client"]
    response = c.post("/api/jobs", json={"invoice_id": "INV-1042", "selected_mode": "auto"})
    response.raise_for_status()
    job_id = response.json()["id"]
    drive(c, job_id)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(extra_http_headers={"Authorization": "Bearer test-staff"})
        page = context.new_page()
        page.add_init_script(f"localStorage.setItem('active-job', '{job_id}')")
        page.goto(browser_server["url"])
        page.locator("#assessment-operation option").first.wait_for(state="attached")
        page.get_by_text("Assess an executed operation", exact=True).click()
        page.locator("#assessment-outcome").select_option("incorrect")
        page.locator("#assessment-explanation").fill("Synthetic reviewer reports an incorrect result")
        with page.expect_response(f"**/api/jobs/{job_id}/assessments") as response:
            page.get_by_role("button", name="Record assessment", exact=True).click()
        assert response.value.status == 200
        page.locator("#metrics-tab").click()
        page.locator("#metrics-tab[aria-current=page]").wait_for()
        row = page.locator("#metrics-view tr").filter(has_text="incorrect actions reported")
        row.wait_for()
        assert row.locator("td").nth(1).inner_text() == "1"
        assert page.locator("#metrics-view").inner_text().find("unassessed actions") >= 0
        page.screenshot(path=str(browser_server["data_dir"] / "assessment-console.png"))
        browser.close()
