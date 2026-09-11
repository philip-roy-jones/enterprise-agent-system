"""Generated from verified synthetic demonstrations; uses fresh records and layouts."""

import pytest
from enterprise.procedures import AMOUNT_LABELS, GRAPH_VERSION, resolve_amount_label

LEARNED_LABELS = ["Reviewed adjustment 0"]


@pytest.mark.parametrize("label", LEARNED_LABELS)
def test_learned_resolver(label):
    assert resolve_amount_label(["Correction explanation", label]) == label
    assert resolve_amount_label([label, "Unrelated control"]) == label
    assert resolve_amount_label(["Unreviewed arbitrary field"]) is None


@pytest.mark.browser
@pytest.mark.parametrize("label", LEARNED_LABELS)
@pytest.mark.parametrize("invoice,variant", [("INV-1043", "standard"), ("INV-1044", "layout")])
def test_learned_label_on_fresh_job(browser_server, label, invoice, variant):
    from enterprise.demo import drive

    c = browser_server["client"]
    browser_server["store"].put_value(
        "release", {"version": GRAPH_VERSION, "labels": list(AMOUNT_LABELS), "previous": None}
    )
    c.post(
        "/api/mock/scenario",
        json={"amount_label": label, "variant": variant, "view": "purchase_orders", "reordered": True},
    ).raise_for_status()
    created = c.post("/api/jobs", json={"invoice_id": invoice, "selected_mode": "auto"})
    created.raise_for_status()
    result = drive(c, created.json()["id"])
    assert result["job"]["fallback_count"] == result["job"]["model_calls"] == 0
    assert result["job"]["mutation"] == "confirmed_succeeded"
    assert result["job"]["graph_version"] == GRAPH_VERSION
