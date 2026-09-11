from copy import deepcopy
from pathlib import Path
import pytest
from enterprise.development.improvement_analysis import (
    analyze,
    patch_library,
    inspect_library,
    regression_source,
)
from enterprise.development.improve import regression_failures

ROOT = Path(__file__).resolve().parents[1]
LABEL = next(
    f"Reviewed adjustment {n}"
    for n in range(1000)
    if f"Reviewed adjustment {n}" not in inspect_library(ROOT)["labels"]
)


@pytest.fixture
def episode():
    expected = {"company_id": "ACME", "invoice_id": "INV-1042", "amount": 12000, "note": "Synthetic note"}
    args = {"field": "amount", "value": "120.00"}
    state = {"company_id": "ACME", "invoice_id": "INV-1042", "fields": {"amount": "120.00"}}
    return {
        "app_version": "mock-1",
        "job": {
            "id": "synthetic-episode",
            "accepted": True,
            "status": "completed",
            "mutation": "confirmed_succeeded",
            "expected": expected,
            "model_mode": "simulated",
            "graph_version": "v1",
            "company_id": "ACME",
            "invoice_id": "INV-1042",
        },
        "events": [
            {
                "seq": 10,
                "at": 1,
                "kind": "recovery_required",
                "data": {"node": "prepare", "kind": "unfamiliar", "reason": "Unexpected control"},
            },
            {
                "seq": 20,
                "kind": "action_result",
                "data": {"result": {"value": dict(expected, operation_id="synthetic-episode")}},
            },
        ],
        "approvals": [
            {
                "id": "synthetic-decision",
                "kind": "tool",
                "status": "executed",
                "created_at": 2,
                "arguments": {"field": "note", "value": "wrong"},
                "corrected_arguments": args,
                "decision": {"decision": "correct"},
                "executed_action": {"name": "set_field", "arguments": args, "observation_revision": "fresh"},
                "observation": {
                    "revision": "fresh",
                    "state": state,
                    "targets": [
                        {"target": "amount", "label": LABEL},
                        {"target": "note", "label": "Explanation"},
                    ],
                },
                "observed_result": {"value": args, "after": {"state": state}},
            }
        ],
    }


def test_infers_actual_correction_without_label_keyword_or_canned_replacement(episode, tmp_path):
    result = analyze([episode], ROOT)
    assert result["additions"] == [LABEL]
    assert result["library"]["nodes"] and result["evidence"][0]["decision"] == "correct"
    target = tmp_path / "procedures.py"
    target.write_text((ROOT / "src/enterprise/workflows/finance/procedures.py").read_text())
    patch_library(target, result)
    namespace = {}
    exec(compile(target.read_text(), str(target), "exec"), namespace)
    assert namespace["resolve_amount_label"]([LABEL]) == LABEL
    assert namespace["GRAPH_VERSION"] == result["version"]
    assert "INV-1042" not in target.read_text()
    compile(regression_source(result["additions"]), "generated-regression.py", "exec")


def test_existing_label_produces_no_redundant_improvement(episode):
    episode["approvals"][0]["observation"]["targets"][0]["label"] = inspect_library(ROOT)["labels"][0]
    assert analyze([episode], ROOT)["change"] == "no_supported_change"


@pytest.mark.parametrize("damage", ["save", "scope", "revision", "decision", "ambiguous", "field"])
def test_incomplete_or_conflicting_evidence_never_produces_a_patch(episode, damage):
    approval = episode["approvals"][0]
    if damage == "save":
        episode["events"].pop()
    elif damage == "scope":
        approval["observation"]["state"]["invoice_id"] = "INV-9999"
    elif damage == "revision":
        approval["executed_action"]["observation_revision"] = "old"
    elif damage == "decision":
        approval["corrected_arguments"] = {"field": "amount", "value": "200.00"}
    elif damage == "ambiguous":
        approval["observation"]["targets"].append({"target": "note", "label": LABEL})
    else:
        approval["observed_result"]["value"] = {"field": "amount", "value": "200.00"}
    with pytest.raises(ValueError):
        analyze([episode], ROOT)


def test_recurring_gap_groups_selected_episodes_and_deduplicates_rules(episode):
    another = deepcopy(episode)
    another["job"]["id"] = "another"
    another["events"][1]["data"]["result"]["value"]["operation_id"] = "another"
    result = analyze([episode, another], ROOT)
    assert result["recurring_gaps"][0]["occurrences"] == 2
    assert result["additions"] == [LABEL] and len(result["evidence"]) == 2


def test_label_reason_alone_does_not_justify_a_change(episode):
    episode["events"][0]["data"]["reason"] = "The correction amount field label changed"
    episode["approvals"] = []
    assert analyze([episode], ROOT)["change"] == "no_supported_change"


def test_analysis_refuses_changed_graph_consumer(episode, tmp_path):
    (tmp_path / "src/enterprise/workflows/finance").mkdir(parents=True)
    (tmp_path / "src/enterprise/workflows/finance/procedures.py").write_text(
        (ROOT / "src/enterprise/workflows/finance/procedures.py").read_text()
    )
    (tmp_path / "src/enterprise/workflows/finance/graph.py").write_text(
        (ROOT / "src/enterprise/workflows/finance/graph.py")
        .read_text()
        .replace('job["amount_labels"]', 'job["unrelated_labels"]')
    )
    with pytest.raises(ValueError, match="no longer consumes"):
        analyze([episode], tmp_path)


def test_regression_count_uses_reported_failures_and_errors(tmp_path):
    path = tmp_path / "checks.xml"
    assert regression_failures(path) is None
    path.write_text(
        '<testsuites><testsuite failures="2" errors="1"/><testsuite failures="0" errors="1"/></testsuites>'
    )
    assert regression_failures(path) == 4


@pytest.mark.browser
def test_analysis_uses_real_recorded_browser_correction(browser_server):
    from enterprise.development.demo import drive

    c = browser_server["client"]
    c.post("/api/mock/scenario", json={"amount_label": LABEL}).raise_for_status()
    response = c.post("/api/jobs", json={"invoice_id": "INV-1042", "selected_mode": "auto"})
    response.raise_for_status()
    job_id = response.json()["id"]
    drive(c, job_id, correction=True)
    episode = c.get(f"/api/jobs/{job_id}/episode").json()
    result = analyze([episode], ROOT)
    assert result["additions"] == [LABEL]
    assert result["evidence"][0]["verified_field_and_save"]
    # Retain full evidence only in the isolated test runtime for a subsequent real proposal run.
    import json

    (browser_server["data_dir"] / "improvement-episode.json").write_text(json.dumps(episode))
