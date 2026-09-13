"""Credential-free runtime tests for admitted read-only Marketing compositions."""

from copy import deepcopy
from types import SimpleNamespace

from eas_harness.candidate_checks import FixtureStore
from eas_harness.integrations.marketing import operation
from eas_shared.types import Recovery


def check_marketing(spec):
    checks = []
    for impressions, clicks, spend, expected_rate, expected_cost in (
        (24000, 1200, 36000, 5.0, 30.0),
        (15000, 450, 22500, 3.0, 50.0),
        (0, 0, 0, None, None),
    ):
        job = {
            "id": "admission-fixture",
            "role_id": "campaign_review",
            "company_id": spec["company_id"],
            "campaign_id": "CAM-9001",
            "permissions": ["read"],
        }
        record = {
            "campaign_id": "CAM-9001",
            "company_id": job["company_id"],
            "title": "Fixture",
            "revision": 1,
            "impressions": impressions,
            "clicks": clicks,
            "spend_cents": spend,
        }
        state = {"exists": True, "record": record}
        adapter = SimpleNamespace(observe=lambda: SimpleNamespace(state=deepcopy(state)))
        store = FixtureStore(job)
        args = {"campaign_id": job["campaign_id"], "company_id": job["company_id"], "reason": ""}
        for name in spec["steps"]:
            result = operation(store, adapter, store.job, name, args)
        assert result["verified"]
        report = store.job["verified_report"]
        assert report["click_through_percent"] == expected_rate
        assert report["cost_per_click_cents"] == expected_cost
        checks.append({"case": f"campaign metrics {impressions}/{clicks}/{spend}", "passed": True})
        record["revision"] += 1
        try:
            operation(store, adapter, store.job, "complete", args)
        except Recovery:
            checks.append({"case": "changed metrics require another report", "passed": True})
        else:
            raise AssertionError("Stale report completed")
        state["exists"] = False
        try:
            operation(store, adapter, store.job, "report", args)
        except Recovery as error:
            assert error.kind == "record_unavailable"
        else:
            raise AssertionError("Missing campaign produced a report")
    return {"suite": "marketing-runtime-1", "model_mode": "none", "checks": checks}
