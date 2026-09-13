"""A single bounded learning/reuse run with explicitly simulated staff decisions."""

import argparse
import json
from pathlib import Path
import time
from collections import Counter
import httpx
from enterprise_dev.config import Settings


def run(client, task, invoice, *, guidance=None, correct_field=False, timeout=240):
    response = client.post("/api/jobs", json={"invoice_id": invoice, "task": task})
    response.raise_for_status()
    job_id = response.json()["id"]
    if guidance:
        client.post(
            f"/api/jobs/{job_id}/messages",
            json={"text": guidance, "message_id": "simulated-teaching-guidance"},
        ).raise_for_status()
    deadline = time.monotonic() + timeout
    corrected = False
    while time.monotonic() < deadline:
        data = client.get("/api/jobs/" + job_id).json()
        if data["job"]["status"] in {"completed", "failed", "denied", "cancelled", "rejected"}:
            break
        for approval in data["approvals"]:
            if approval["status"] != "pending":
                continue
            decision = {
                "decision": "approve",
                "explanation": "Explicit simulated staff decision for synthetic learning evaluation",
            }
            if correct_field and not corrected and approval["name"] == "set_field":
                decision.update(
                    decision="correct",
                    arguments=approval["arguments"],
                    explanation="Simulated staff confirms the observed field and verified value",
                )
                corrected = True
            result = client.post("/api/approvals/" + approval["id"], json=decision)
            if result.status_code not in {200, 409}:
                result.raise_for_status()
            print("Simulated staff:", approval["name"], decision["decision"], flush=True)
        question = next((q for q in data["conversation"]["questions"] if q["status"] == "pending"), None)
        if question:
            # Do not invent domain answers to make an evaluation pass.
            client.post(f"/api/jobs/{job_id}/cancel").raise_for_status()
            raise ValueError("Evaluation requires an unscripted staff answer: " + question["question"])
        time.sleep(0.25)
    else:
        client.post(f"/api/jobs/{job_id}/cancel").raise_for_status()
        raise TimeoutError("Evaluation request exceeded its wall-clock budget")
    job = data["job"]
    if job["status"] == "completed" and (
        job.get("verified_report") or job["mutation"] == "confirmed_succeeded"
    ):
        client.post(f"/api/jobs/{job_id}/accept").raise_for_status()
    learning = None
    end = time.monotonic() + 100
    if job["status"] == "completed":
        while time.monotonic() < end:
            status = client.get("/api/learning").json()
            item = next((q for q in status["queue"] if q.get("job_id") == job_id), None)
            if item and item["status"] in {"completed", "failed"}:
                learning = item
                break
            time.sleep(0.5)
    recoveries = [e for e in data["events"] if e["kind"] == "recovery_required"]
    reasons = Counter(e["data"]["reason"] for e in recoveries)
    executed = [a for a in data["approvals"] if a["status"] == "executed"]
    return {
        "job_id": job_id,
        "conversation_id": job.get("conversation_id"),
        "task": task,
        "invoice_id": invoice,
        "model_mode": job["model_mode"],
        "model_binding": job.get("model_binding"),
        "staff_mode": "simulated",
        "application": job["application"],
        "application_version": job["app_version"],
        "status": job["status"],
        "error": job.get("error"),
        "verified_report": job.get("verified_report"),
        "mutation": job["mutation"],
        "workflow_runs": job.get("workflow_runs", {}),
        "operations": job.get("operation_trace", []),
        "metrics": {
            "approval_requests": len(data["approvals"]),
            "executed_operations": len(executed),
            "approval_coverage": all(a.get("decision") for a in executed),
            "staff_corrections": sum(a.get("decision", {}).get("decision") == "correct" for a in executed),
            "recoveries": len(recoveries),
            "repeated_mistakes": sum(max(0, n - 1) for n in reasons.values()),
            "model_calls": job["model_calls"],
            "tokens": job["tokens"],
            "elapsed_seconds": job["elapsed_seconds"],
            "waiting_seconds": round(
                sum(a["decision"]["at"] - a["created_at"] for a in data["approvals"] if a.get("decision")), 2
            ),
            "assessed_actions": 0,
            "incorrect_actions_reported": 0,
            "unassessed_actions": len(executed),
        },
        "judgments": [e for e in data["events"] if e["kind"].startswith("judgment_")],
        "desktop_input_methods": dict(
            Counter(e["data"]["method"] for e in data["events"] if e["kind"] == "desktop_input")
        ),
        "learning": learning,
    }


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--simulate-staff", action="store_true")
    p.add_argument("--task", required=True)
    p.add_argument("--invoice", default="INV-1042")
    p.add_argument("--guidance")
    p.add_argument("--correct-field", action="store_true")
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)
    if not args.simulate_staff:
        p.error("This driver submits decisions; --simulate-staff is required")
    settings = Settings()
    with httpx.Client(
        base_url=settings.backend_url, headers={"Authorization": "Bearer " + settings.staff_token}, timeout=20
    ) as client:
        result = run(
            client, args.task, args.invoice, guidance=args.guidance, correct_field=args.correct_field
        )
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ["job_id", "status", "error", "metrics"]}), flush=True)
    if result["status"] != "completed" or not result.get("learning"):
        raise SystemExit(1)
