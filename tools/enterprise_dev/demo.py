"""Explicit automated STAFF SIMULATOR for repeatable, non-live demonstrations."""

import argparse
import json
from pathlib import Path
import time
import httpx
from enterprise_dev.config import Settings


def drive(client, job_id, correction=False, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/jobs/{job_id}").json()
        if data["job"]["status"] in {"completed", "failed", "denied", "rejected", "cancelled"}:
            if data["job"]["status"] != "completed":
                raise AssertionError(data["job"])
            return data
        time.sleep(0.15)
    raise TimeoutError(f"Job {job_id} did not finish")


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument(
        "--simulate-staff", action="store_true", help="Explicitly authorize synthetic supervisor activation"
    )
    p.add_argument("--output", default="runtime/demo-report.json")
    args = p.parse_args(argv)
    if not args.simulate_staff:
        p.error("This demo simulates supervisor activation. Use --simulate-staff explicitly.")
    settings = Settings()
    client = httpx.Client(
        base_url=settings.backend_url, headers={"Authorization": f"Bearer {settings.staff_token}"}, timeout=20
    )
    if client.get("/api/health").json()["desktop_adapter"] != "browser":
        p.error("This demonstration is restricted to the synthetic browser fixture")
    client.post(
        "/api/employees/development-desktop/state",
        headers={"Authorization": "Bearer " + settings.developer_token},
        json={"state": "active", "reason": "Explicit simulated supervisor activation for the synthetic demo"},
    ).raise_for_status()
    results = []
    scenarios = [
        ("Known procedure / Auto", "auto", {}, "INV-1042"),
        ("Known procedure / another record", "auto", {}, "INV-1043"),
        ("Changed field / supervised assistance", "auto", {"variant": "renamed"}, "INV-1044"),
        ("Interrupted save / reconciliation", "auto", {"interrupt_save": True}, "INV-1042"),
    ]
    for title, mode, scenario, invoice in scenarios:
        client.post(
            "/api/mock/scenario",
            json=dict(
                view="dashboard",
                invoice_id=None,
                dialog=None,
                unsaved=False,
                variant="standard",
                amount_label=None,
                reordered=False,
                interrupt_save=False,
                **{},
            )
            | scenario,
        ).raise_for_status()
        r = client.post("/api/jobs", json={"invoice_id": invoice, "selected_mode": mode})
        r.raise_for_status()
        data = drive(client, r.json()["id"], correction=True)
        job = data["job"]
        results.append(
            dict(
                title=title,
                job_id=job["id"],
                status=job["status"],
                skill_runs=job.get("skill_runs", {}),
                fallback_count=job["fallback_count"],
                model_calls=job["model_calls"],
                effective_mode=job["effective_mode"],
                policy_authorizations=len(data["approvals"]),
                execution_seconds=job["elapsed_seconds"],
            )
        )
        print(f"✓ {title}: {job['id']} ({len(data['approvals'])} server authorizations)", flush=True)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"model_mode": settings.model_mode, "staff": "simulated", "results": results}, indent=2)
        + "\n"
    )
    print(
        f"Report: {path}\nImprovement evidence episode: {results[2]['job_id']}\nDeveloper review remains a separate manual step."
    )
