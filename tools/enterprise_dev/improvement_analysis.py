"""Evidence-derived, deterministic development analysis for the bounded prototype.

Only a resolver extension supported by a verified field demonstration is emitted.
Other gaps remain explicit findings for a developer, not guessed executable code.
This module parses source; it never imports a worker or controls a desktop.
"""

import ast
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def assignment(tree, name):
    matches = [
        n
        for n in tree.body
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one inspectable {name} assignment")
    return matches[0]


def inspect_library(root):
    root = Path(root)
    source = (root / "src/edge-harness/eas_harness/workflows/finance/procedures.py").read_text()
    tree = ast.parse(source)
    labels = ast.literal_eval(assignment(tree, "AMOUNT_LABELS").value)
    version = ast.literal_eval(assignment(tree, "GRAPH_VERSION").value)
    if not isinstance(labels, tuple) or not all(isinstance(v, str) for v in labels):
        raise ValueError("Amount resolver labels must be a literal tuple of strings")
    if not isinstance(version, str) or not re.fullmatch(r"v[0-9]+", version):
        raise ValueError("Version requires explicit migration review")
    graph_source = (root / "src/edge-harness/eas_harness/workflows/finance/graph.py").read_text()
    graph = ast.parse(graph_source)
    nodes = ast.literal_eval(assignment(graph, "NODES").value)
    runtime_path = root / "src/edge-harness/eas_harness/workflows/finance/runtime.py"
    runtime_source = runtime_path.read_text() if runtime_path.exists() else graph_source
    operations_tree = ast.parse(runtime_source)
    operation = next(
        (n for n in ast.walk(operations_tree) if isinstance(n, ast.FunctionDef) and n.name == "operation"),
        None,
    )
    prepare = (
        next(
            (
                n
                for n in ast.walk(operation)
                if isinstance(n, ast.If) and ast.unparse(n.test) == "name == 'prepare'"
            ),
            None,
        )
        if operation
        else None
    )
    if prepare is None or "prepare" not in nodes:
        raise ValueError("No existing prepare operation to reuse; developer design needed")
    # Validate the actual library consumer, not merely a function with a familiar name.
    if not any(
        isinstance(n, ast.Subscript)
        and isinstance(n.slice, ast.Constant)
        and n.slice.value == "amount_labels"
        for n in ast.walk(prepare)
    ):
        raise ValueError("Graph no longer consumes versioned amount labels")
    if not any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "set_field"
        and n.args
        and isinstance(n.args[0], ast.Constant)
        and n.args[0].value == "amount"
        for n in ast.walk(prepare)
    ):
        raise ValueError("Graph no longer uses the shared amount field operation")
    return {
        "version": version,
        "labels": list(labels),
        "nodes": nodes,
        "reused_operation": "prepare → set_field(amount) → save → verify",
        "source_hashes": {
            "src/edge-harness/eas_harness/workflows/finance/runtime.py": hashlib.sha256(
                runtime_source.encode()
            ).hexdigest(),
            "src/edge-harness/eas_harness/workflows/finance/procedures.py": hashlib.sha256(
                source.encode()
            ).hexdigest(),
            "src/edge-harness/eas_harness/workflows/finance/graph.py": hashlib.sha256(
                graph_source.encode()
            ).hexdigest(),
        },
    }


def analyze(episodes, root):
    library = inspect_library(root)
    evidence, findings, gaps = [], [], Counter()
    for episode in episodes:
        job = episode["job"]
        if (
            not job.get("accepted")
            or job.get("status") != "completed"
            or job.get("mutation") != "confirmed_succeeded"
        ):
            raise ValueError("Select staff-accepted episodes with verified saved results")
        app = episode.get("app_version", "")
        if not (app.startswith("mock-") or app.startswith("demobooks-")):
            raise ValueError("Only explicitly synthetic application evidence can become fixtures")
        failures = [e for e in episode["events"] if e["kind"] == "recovery_required"]
        for failure in failures:
            gaps[(failure["data"].get("node"), failure["data"].get("kind"))] += 1
        prepare_failures = [e for e in failures if e["data"].get("node") == "prepare"]
        if not prepare_failures:
            findings.append(
                {
                    "episode_id": job["id"],
                    "finding": "No failed prepare operation; no resolver change inferred",
                }
            )
            continue
        expected = job.get("expected") or {}
        for approval in episode["approvals"]:
            decision = approval.get("decision") or {}
            action = approval.get("executed_action") or {}
            arguments = action.get("arguments", {})
            if (
                approval.get("kind") != "tool"
                or approval.get("status") != "executed"
                or action.get("name") != "set_field"
                or arguments.get("field") != "amount"
                or decision.get("decision") not in {"approve", "correct"}
            ):
                continue
            approved = approval.get("corrected_arguments", approval.get("arguments"))
            if arguments != approved:
                raise ValueError("Executed field action differs from the staff-approved arguments")
            before = approval["observation"]
            result = approval.get("observed_result") or {}
            after = result.get("after", {}).get("state", {})
            if any(
                before["state"].get(k) != job.get(k) or after.get(k) != job.get(k)
                for k in ("company_id", "invoice_id")
            ):
                raise ValueError("Demonstration identity does not match the accepted job")
            try:
                amount_matches = Decimal(arguments["value"]) * 100 == expected.get("amount")
            except (InvalidOperation, KeyError):
                amount_matches = False
            if (
                not amount_matches
                or after.get("fields", {}).get("amount") != arguments.get("value")
                or result.get("value") != arguments
            ):
                raise ValueError("Field demonstration lacks a matching verified result")
            if action.get("observation_revision") != before.get("revision"):
                raise ValueError("Executed action is not bound to the recorded observation")
            targets = [t for t in before["targets"] if t.get("target") == "amount"]
            if len(targets) != 1:
                raise ValueError("Amount target is missing or ambiguous; no label can be learned")
            label = targets[0].get("label", "")
            if not isinstance(label, str) or not 1 <= len(label) <= 100 or not label.isprintable():
                raise ValueError("Target label is not suitable for a synthetic regression fixture")
            if any(t.get("target") != "amount" and t.get("label") == label for t in before["targets"]):
                raise ValueError("Label is shared by another control; resolver extension is unsafe")
            # Final status alone is insufficient: independently inspect the saved business evidence.
            drafts = [
                d
                for e in episode["events"]
                if e["kind"] == "action_result"
                for d in [e["data"].get("result", {}).get("value", {})]
                if isinstance(d, dict) and d.get("operation_id") == job["id"]
            ]
            if not any(
                all(d.get(k) == expected.get(k) for k in ("company_id", "invoice_id", "amount", "note"))
                for d in drafts
            ):
                raise ValueError("No recorded saved result corroborates staff acceptance")
            if not any(e.get("at", 0) <= approval.get("created_at", 0) for e in prepare_failures):
                raise ValueError("Demonstration predates the failure it supposedly resolves")
            evidence.append(
                {
                    "episode_id": job["id"],
                    "approval_id": approval["id"],
                    "label": label,
                    "decision": decision["decision"],
                    "model_mode": job["model_mode"],
                    "app_version": app,
                    "graph_version": job["graph_version"],
                    "episode_sha256": digest(episode),
                    "observation_revision": before["revision"],
                    "failure_sequences": [e["seq"] for e in prepare_failures],
                    "verified_field_and_save": True,
                }
            )
    additions = sorted({e["label"] for e in evidence} - set(library["labels"]))
    return {
        "change": "extend_amount_resolver" if additions else "no_supported_change",
        "library": library,
        "additions": additions,
        "version": f"v{int(library['version'][1:]) + 1}" if additions else library["version"],
        "evidence": evidence,
        "findings": findings,
        "recurring_gaps": [{"node": k[0], "kind": k[1], "occurrences": v} for k, v in gaps.items()],
        "rationale": "Reuse the existing prepare operation and its verification; only the observed, approved amount label is missing. No new node or business permission is needed."
        if additions
        else "Evidence does not establish a missing supported resolver rule; do not manufacture a patch.",
        "limits": "Deterministic analysis supports verified amount-target gaps. Other gap families require developer implementation. One accepted episode suggests a candidate, not proof of generality; generated tests cover new records and layouts.",
    }


def patch_library(path, analysis):
    path = Path(path)
    source = path.read_text()
    if (
        hashlib.sha256(source.encode()).hexdigest()
        != analysis["library"]["source_hashes"][
            "src/edge-harness/eas_harness/workflows/finance/procedures.py"
        ]
    ):
        raise ValueError("Inspected source changed before patching")
    tree = ast.parse(source)
    replacements = {
        "GRAPH_VERSION": repr(analysis["version"]),
        "AMOUNT_LABELS": repr(tuple(analysis["library"]["labels"] + analysis["additions"])),
    }
    lines = source.splitlines(keepends=True)
    for node in sorted([assignment(tree, key) for key in replacements], key=lambda n: n.lineno, reverse=True):
        name = node.targets[0].id
        lines[node.lineno - 1 : node.end_lineno] = [f"{name} = {replacements[name]}\n"]
    path.write_text("".join(lines))


def regression_source(additions):
    return (
        '''"""Generated from verified synthetic demonstrations; uses fresh records and layouts."""
import pytest
from eas_harness.workflows.finance.procedures import AMOUNT_LABELS, GRAPH_VERSION, resolve_amount_label

LEARNED_LABELS = '''
        + repr(additions)
        + """

@pytest.mark.parametrize("label", LEARNED_LABELS)
def test_learned_resolver(label):
    assert resolve_amount_label(["Correction explanation", label]) == label
    assert resolve_amount_label([label, "Unrelated control"]) == label
    assert resolve_amount_label(["Unreviewed arbitrary field"]) is None

@pytest.mark.browser
@pytest.mark.parametrize("label", LEARNED_LABELS)
@pytest.mark.parametrize("invoice,variant", [("INV-1043", "standard"), ("INV-1044", "layout")])
def test_learned_label_on_fresh_job(browser_server, label, invoice, variant):
    from enterprise_dev.demo import drive
    c = browser_server["client"]
    browser_server["store"].put_value("release", {"version": GRAPH_VERSION, "labels": list(AMOUNT_LABELS), "previous": None})
    c.post("/api/mock/scenario", json={"amount_label": label, "variant": variant, "view": "purchase_orders", "reordered": True}).raise_for_status()
    created = c.post("/api/jobs", json={"invoice_id": invoice, "selected_mode": "auto"})
    created.raise_for_status()
    result = drive(c, created.json()["id"])
    assert result["job"]["fallback_count"] == result["job"]["model_calls"] == 0
    assert result["job"]["mutation"] == "confirmed_succeeded"
    assert result["job"]["graph_version"] == GRAPH_VERSION
"""
    )
