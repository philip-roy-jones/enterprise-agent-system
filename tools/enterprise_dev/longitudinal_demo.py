"""Operator live evaluation; all approvals are explicitly simulated staff."""

import argparse
import json
import time
import re
from pathlib import Path
from collections import Counter
import httpx
from enterprise_dev.config import Settings


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("name")
    p.add_argument("--simulate-staff", action="store_true")
    p.add_argument("--output-dir", type=Path, default=Path("runtime/agent-led-evaluation/longitudinal"))
    p.add_argument("--task", required=True)
    p.add_argument("--invoice", default="INV-1042")
    p.add_argument("--kind", choices=["report", "correction", "guidance"], required=True)
    p.add_argument("--guidance")
    p.add_argument("--timeout", type=int, default=420)
    p.add_argument("--no-learn", action="store_true")
    a = p.parse_args(argv)
    if not a.simulate_staff:
        p.error("--simulate-staff is required; this driver submits synthetic staff decisions")
    if not a.name.replace("-", "").replace("_", "").isalnum():
        p.error("Use a simple evaluation name")
    s = Settings()
    out = a.output_dir
    out.mkdir(parents=True, exist_ok=True)
    if (out / (a.name + ".json")).exists() or (out / (a.name + ".raw.json")).exists():
        p.error("Choose a new name; existing evaluation evidence is preserved")
    client = httpx.Client(
        base_url=s.backend_url, headers={"Authorization": "Bearer " + s.developer_token}, timeout=25
    )
    response = client.post("/api/jobs", json={"invoice_id": a.invoice, "task": a.task})
    response.raise_for_status()
    jid = response.json()["id"]
    print("Request", a.name, jid, flush=True)
    if a.guidance:
        client.post(
            f"/api/jobs/{jid}/messages",
            json={"text": a.guidance, "message_id": "simulated-teaching-guidance"},
        ).raise_for_status()
    deadline = time.monotonic() + a.timeout
    failure = None
    while time.monotonic() < deadline:
        data = client.get("/api/jobs/" + jid).json()
        job = data["job"]
        if job["status"] in {"completed", "failed", "denied", "rejected", "cancelled"}:
            break
        for approval in data["approvals"]:
            if approval["status"] != "pending":
                continue
            name = approval["name"]
            arguments = approval["arguments"]
            allowed = a.kind == "correction" or name not in {"prepare", "save", "save_draft", "set_field"}
            if name == "run_skill" and a.kind != "correction":
                status = client.get("/api/learning").json()
                spec = next(
                    (
                        v
                        for r in status["registries"]
                        for v in r["versions"]
                        if v["skill_id"] == arguments["skill_id"] and v["version"] == arguments["version"]
                    ),
                    None,
                )
                allowed = bool(spec and "save" not in spec["steps"])
            decision = {
                "decision": "approve" if allowed else "reject",
                "explanation": "Simulated staff decision for synthetic longitudinal evaluation; scope checked by test driver.",
            }
            if allowed and a.kind == "correction" and name == "set_field" and job.get("expected"):
                expected = job["expected"]
                desired = (
                    f"{expected['amount'] / 100:.2f}" if arguments["field"] == "amount" else expected["note"]
                )
                if arguments["value"] != desired:
                    decision.update(
                        decision="correct",
                        arguments={**arguments, "value": desired},
                        explanation="Simulated staff correction: use the verified purchase-order amount as dollars in the visible amount field, and preserve the verified explanation and unique request reference.",
                    )
            r = client.post("/api/approvals/" + approval["id"], json=decision)
            if r.status_code not in {200, 409}:
                r.raise_for_status()
            print("Simulated staff", name, decision["decision"], flush=True)
        if any(q["status"] == "pending" for q in data["conversation"]["questions"]):
            failure = "Unscripted staff question"
            client.post(f"/api/jobs/{jid}/cancel").raise_for_status()
            break
        time.sleep(0.4)
    else:
        failure = "Evaluation wall-clock timeout"
        client.post(f"/api/jobs/{jid}/cancel").raise_for_status()
    data = client.get("/api/jobs/" + jid).json()
    job = data["job"]
    states = [
        e["data"].get("result", {}).get("after", {}).get("state", {})
        for e in data["events"]
        if e["kind"] == "action_result"
    ]
    records = [
        r
        for state in states
        for r in state.get("invoices", [])
        if r["id"] == a.invoice and r["company_id"] == job["company_id"]
    ]
    verification = {
        "passed": False,
        "method": "Independent driver checks native observed record and output; not tool-return success alone",
    }
    if records and job["status"] == "completed":
        row = records[-1]
        totals = {
            "invoice_amount": row["amount"],
            "purchase_order_amount": row["po_amount"],
            "difference": row["amount"] - row["po_amount"],
        }
        verification["observed"] = dict(invoice_id=row["id"], po_id=row["po_id"], **totals)
        if a.kind == "report":
            report = job.get("verified_report", {})
            verification["passed"] = (
                all(report.get(k) == v for k, v in totals.items())
                and report.get("invoice_id") == a.invoice
                and job["mutation"] == "not_attempted"
            )
        elif a.kind == "correction":
            drafts = [
                d for st in states for d in st.get("drafts", []) if "[EAS:" + jid + "]" in d.get("note", "")
            ]
            unique = {d["id"]: d for d in drafts}
            verification["observed_drafts"] = list(unique.values())
            verification["passed"] = (
                job["mutation"] == "confirmed_succeeded"
                and len(unique) == 1
                and all(
                    d["amount"] == row["po_amount"]
                    and d["invoice_id"] == a.invoice
                    and d["company_id"] == job["company_id"]
                    for d in unique.values()
                )
            )
        else:
            answer = job.get("assistant_report", "")
            verification["answer"] = answer
            verification["passed"] = (
                f"{row['amount'] / 100:,.2f}" in answer or f"{row['amount'] / 100:.2f}" in answer
            ) and job["mutation"] == "not_attempted"
    assessed = 0
    if verification["passed"]:
        for approval in data["approvals"]:
            if approval["status"] == "executed" and approval["name"] in {
                "report",
                "save",
                "verify",
                "review_discovery",
            }:
                r = client.post(
                    f"/api/jobs/{jid}/assessments",
                    json={
                        "invocation": approval["invocation"],
                        "outcome": "correct",
                        "explanation": "Simulated staff assessment by evaluation driver: independently compared the completed output to the native observed record and unique saved-draft evidence.",
                    },
                )
                r.raise_for_status()
                assessed += 1
    learning = None
    answers = [e["data"]["text"] for e in data["events"] if e["kind"] == "assistant_message"]
    answer = answers[-1] if answers else ""
    if verification["passed"]:
        cents = {row["amount"], row["po_amount"], abs(row["amount"] - row["po_amount"])}
        dollars = {value / 100 for value in cents}
        unsupported = []
        for token in re.findall(r"(?<![\w-])\$?\d[\d,]*(?:\.\d{1,2})?(?![\w-])", answer):
            value = float(token.lstrip("$").replace(",", ""))
            permitted = dollars if token.startswith("$") else cents | dollars | {0, 1, 100}
            if value not in permitted:
                unsupported.append(token)
        verification["narrative"] = {
            "text": answer,
            "passed": bool(answer) and not unsupported,
            "unsupported_numbers": unsupported,
            "method": "Bounded numeric consistency check, not a general semantic correctness test",
        }
        verification["passed"] = verification["passed"] and verification["narrative"]["passed"]
    if verification["passed"] and not a.no_learn:
        client.post(f"/api/jobs/{jid}/accept").raise_for_status()
        until = time.monotonic() + 160
        while time.monotonic() < until:
            status = client.get("/api/learning").json()
            learning = next(
                (i for i in status["queue"] if i.get("job_id") == jid and i["kind"] == "learn"), None
            )
            if learning and learning["status"] in {"completed", "failed"}:
                break
            time.sleep(0.5)
    data = client.get("/api/jobs/" + jid).json()
    job = data["job"]
    executed = [x for x in data["approvals"] if x["status"] == "executed"]
    recoveries = [e for e in data["events"] if e["kind"] == "recovery_required"]
    reasons = Counter(e["data"]["reason"] for e in recoveries)
    result = {
        "name": a.name,
        "job_id": jid,
        "conversation_id": job["conversation_id"],
        "task": a.task,
        "invoice_id": a.invoice,
        "status": job["status"],
        "error": failure or job.get("error"),
        "model_mode": job["model_mode"],
        "model_binding": job.get("model_binding"),
        "staff_mode": "simulated",
        "application": job["application"],
        "application_version": job["app_version"],
        "verification": verification,
        "skill_runs": job.get("skill_runs", {}),
        "operations": job.get("operation_trace", []),
        "skill_reads": job.get("skill_reads", {}),
        "guidance": a.guidance,
        "learning": learning,
        "judgments": [e for e in data["events"] if e["kind"].startswith("judgment_")],
        "metrics": {
            "approval_requests": len(data["approvals"]),
            "executed_operations": len(executed),
            "approval_coverage": all(
                x.get("decision", {}).get("decision") in {"approve", "correct"} for x in executed
            ),
            "staff_corrections": sum(x.get("decision", {}).get("decision") == "correct" for x in executed),
            "teaching_messages": bool(a.guidance),
            "recoveries": len(recoveries),
            "repeated_mistakes": sum(max(0, n - 1) for n in reasons.values()),
            "model_calls": job["model_calls"],
            "tokens": job["tokens"],
            "elapsed_seconds": job["elapsed_seconds"],
            "waiting_seconds": sum(
                x["decision"]["at"] - x["created_at"] for x in data["approvals"] if x.get("decision")
            ),
            "assessed_actions": assessed,
            "incorrect_actions_reported": 0,
            "unassessed_actions": len(executed) - assessed,
        },
    }
    (out / (a.name + ".raw.json")).write_text(json.dumps(data, indent=2) + "\n")
    (out / (a.name + ".json")).write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {k: result[k] for k in ["name", "job_id", "status", "error", "verification", "metrics"]}, indent=2
        ),
        flush=True,
    )
    if learning:
        print(
            "Learning",
            learning["status"],
            learning.get("result", {}).get("status"),
            learning.get("error"),
            flush=True,
        )
    if not verification["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
