"""Manual, isolated improvement proposals. Proposal generation never approves a release."""

import argparse
import hashlib
import hmac
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import time
import httpx
from .config import Settings
from .store import Store, uid
from .types import TERMINAL


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_development():
    if os.getenv("EAS_DEV_PERMISSIONS") != "local-improvement":
        raise PermissionError(
            "Set EAS_DEV_PERMISSIONS=local-improvement to explicitly enable isolated development work"
        )


def propose(episode, root, output, publish=False):
    require_development()
    if not episode["job"]["accepted"] or episode["job"]["status"] != "completed":
        raise ValueError("Select a staff-accepted, verified episode")
    reasons = [e["data"].get("reason", "") for e in episode["events"] if e["kind"] == "recovery_required"]
    if not any("label" in r.lower() for r in reasons):
        raise ValueError("This bounded improvement generator supports the recurring amount-label gap only")
    proposal_id = uid()[:12]
    folder = Path(output).resolve() / proposal_id
    folder.mkdir(parents=True)
    checkout = folder / "checkout"
    branch = f"improvements/amount-label-{proposal_id}"
    subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "-b", branch, str(checkout), "HEAD"],
        check=True,
        capture_output=True,
    )
    procedure = checkout / "enterprise" / "procedures.py"
    source = procedure.read_text()
    if 'AMOUNT_LABELS = ("Correction amount",)' not in source:
        raise ValueError("Expected baseline changed; review generator before applying")
    procedure.write_text(
        source.replace('GRAPH_VERSION = "v1"', 'GRAPH_VERSION = "v2"').replace(
            'AMOUNT_LABELS = ("Correction amount",)',
            'AMOUNT_LABELS = ("Correction amount", "Adjusted total")',
        )
    )
    # Only synthetic, selected evidence is committed; never copy runtime, screenshots or credentials.
    fixture = {
        "episode_id": episode["job"]["id"],
        "task": "invoice_correction",
        "app_version": episode["app_version"],
        "graph_version": episode["job"]["graph_version"],
        "reason": "The correction amount field label changed",
        "accepted": True,
        "observed_labels": ["Correction amount", "Adjusted total"],
        "model_mode": episode["job"]["model_mode"],
    }
    fixture_path = checkout / "examples" / "improvement" / "accepted-label-episode.json"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(json.dumps(fixture, indent=2) + "\n")
    test = checkout / "tests" / "test_proposed_label.py"
    test.write_text("""from enterprise.procedures import resolve_amount_label
import pytest

@pytest.mark.parametrize("labels,expected", [
    (["Correction amount", "Correction explanation"], "Correction amount"),
    (["Correction explanation", "Adjusted total"], "Adjusted total"),
    (["Balance due", "Correction explanation"], None),
])
def test_amount_label_variants(labels, expected):
    assert resolve_amount_label(labels) == expected
""")
    subprocess.run(
        [sys.executable, "-m", "ruff", "format", str(procedure), str(test)], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "add",
            "enterprise/procedures.py",
            "tests/test_proposed_label.py",
            "examples/improvement/accepted-label-episode.json",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "commit",
            "-m",
            "Recognize reviewed correction amount label across invoices",
        ],
        check=True,
        capture_output=True,
    )
    commit = git(checkout, "rev-parse", "HEAD")
    patch = subprocess.check_output(["git", "-C", str(checkout), "format-patch", "-1", "--stdout"])
    (folder / "proposal.patch").write_bytes(patch)
    # Explicit allowlist: provider keys, backend/worker tokens, HOME credentials and live data paths are absent.
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(checkout),
        "EAS_DATA_DIR": str(folder / "test-runtime"),
        "EAS_MODEL_MODE": "simulated",
        "EAS_TEST_CANDIDATE_LABELS": "1",
    }
    checks_path = folder / "checks.txt"
    with checks_path.open("w") as check_log:
        checks = subprocess.Popen(
            [sys.executable, "-m", "pytest", "-q", "-x"],
            cwd=checkout,
            env=env,
            stdout=check_log,
            stderr=subprocess.STDOUT,
            start_new_session=os.name == "posix",
        )
        try:
            checks.wait(timeout=600)
        except subprocess.TimeoutExpired:
            # Stop the isolated test servers too; retain evidence and a failed manifest.
            if os.name == "posix":
                os.killpg(checks.pid, signal.SIGKILL)
            else:
                checks.kill()
            checks.wait()
            check_log.write("\nIsolated checks exceeded the 600-second time limit.\n")
    manifest = dict(
        id=proposal_id,
        checkout=str(checkout),
        branch=branch,
        commit=commit,
        episode_id=fixture["episode_id"],
        source_sha=sha(procedure),
        patch_sha=sha(folder / "proposal.patch"),
        checks_sha=sha(folder / "checks.txt"),
        checks_passed=checks.returncode == 0,
        regression_failures=0 if checks.returncode == 0 else None,
        review="pending",
        reviewer=None,
        approved_commit=None,
        version="v2",
        labels=["Correction amount", "Adjusted total"],
    )
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    summary = f"""# Recognize a reviewed correction amount label

The accepted synthetic episode `{fixture["episode_id"]}` encountered an unfamiliar “Adjusted total” field. This proposal adds that label to the existing resolver. It changes no graph topology or business permission, and uses no record-specific coordinates.

- Base application: mock-1; proposed procedure version: v2.
- Candidate commit: `{commit}`.
- Regression checks: {"passed" if checks.returncode == 0 else "failed"}; see checks.txt.
- Evidence: examples/improvement/accepted-label-episode.json; full episode remains in the access-controlled central store.
- New-record browser coverage runs against different invoices and reordered/layout variants in an isolated test environment.
- Developer review: pending. Passing checks do not authorize deployment.
- Rollback: restore the previous release registry for future jobs; running jobs stay pinned.
"""
    (folder / "REVIEW.md").write_text(summary)
    if publish:
        if checks.returncode:
            raise RuntimeError("Checks failed; local proposal saved; refusing PR publication")
        subprocess.run(["git", "-C", str(checkout), "push", "-u", "origin", branch], check=True)
        result = subprocess.check_output(
            [
                "gh",
                "pr",
                "create",
                "--draft",
                "--base",
                "main",
                "--head",
                branch,
                "--title",
                "Recognize reviewed correction amount label across invoices",
                "--body-file",
                str(folder / "REVIEW.md"),
            ],
            cwd=checkout,
            text=True,
        )
        manifest["pull_request"] = result.strip()
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return folder


def verify_candidate(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    checkout = Path(manifest["checkout"])
    if git(checkout, "rev-parse", "HEAD") != manifest["commit"] or git(checkout, "status", "--porcelain"):
        raise ValueError("Candidate checkout changed; rerun proposal checks and review")
    for path, field in [
        (checkout / "enterprise/procedures.py", "source_sha"),
        (folder / "proposal.patch", "patch_sha"),
        (folder / "checks.txt", "checks_sha"),
    ]:
        if sha(path) != manifest[field]:
            raise ValueError("Candidate or check evidence changed")
    if not manifest["checks_passed"]:
        raise ValueError("Candidate checks did not pass")
    return manifest


def review(folder, decision, reviewer, token, settings):
    if not hmac.compare_digest(token, settings.developer_token):
        raise PermissionError("Developer credential required")
    if not reviewer.strip():
        raise ValueError("A named developer reviewer is required")
    manifest = verify_candidate(folder)
    manifest.update(
        review=decision,
        reviewer=reviewer,
        approved_commit=manifest["commit"] if decision == "approve" else None,
        reviewed_at=time.time(),
    )
    Path(folder, "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def deploy(folder, settings, token):
    if not hmac.compare_digest(token, settings.developer_token):
        raise PermissionError("Developer credential required")
    manifest = verify_candidate(folder)
    if manifest["review"] != "approve" or manifest["approved_commit"] != manifest["commit"]:
        raise PermissionError("Deployment requires developer approval of this exact checked commit")
    if manifest.get("pull_request"):
        remote = json.loads(
            subprocess.check_output(
                ["gh", "pr", "view", manifest["pull_request"], "--json", "headRefOid,statusCheckRollup"],
                cwd=manifest["checkout"],
                text=True,
            )
        )
        if remote["headRefOid"] != manifest["commit"]:
            raise ValueError("Pull request head changed after developer review")
        checks = remote.get("statusCheckRollup") or []
        if not checks or any(
            (check.get("conclusion") != "SUCCESS" or check.get("status") != "COMPLETED")
            if check.get("__typename") == "CheckRun"
            else check.get("state") != "SUCCESS"
            for check in checks
        ):
            raise ValueError("Published proposal requires passing GitHub CI on the approved commit")
    # Load the checked library in an isolated subprocess. Do not trust editable manifest labels.
    output = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import json;from enterprise.procedures import AMOUNT_LABELS,GRAPH_VERSION,resolve_amount_label;assert resolve_amount_label(['Adjusted total']) == 'Adjusted total';print(json.dumps({'labels':list(AMOUNT_LABELS),'version':GRAPH_VERSION}))",
        ],
        cwd=manifest["checkout"],
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": manifest["checkout"]},
        text=True,
    )
    candidate = json.loads(output)
    store = Store(settings.data_dir)
    with store.db() as db:
        active = db.execute(
            "SELECT data FROM jobs WHERE json_extract(data,'$.status') NOT IN ('completed','cancelled','rejected','denied','failed')"
        ).fetchall()
        if active:
            raise ValueError("Only idle workers can receive a release; finish or cancel queued/running jobs")
        previous = json.loads(db.execute("SELECT data FROM kv WHERE key='release'").fetchone()[0])
        release = dict(candidate, commit=manifest["commit"], previous=previous, health="passed")
        db.execute("UPDATE kv SET data=? WHERE key='release'", (json.dumps(release),))
    return release


def idle_scheduler_interface():
    """A scheduler may call propose after checking configured scope. No schedule is installed."""
    return {
        "enabled": False,
        "command": "enterprise improve --episode EPISODE_ID",
        "requires": "EAS_DEV_PERMISSIONS=local-improvement",
    }


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["improve", "review", "deploy", "rollback"])
    parser.add_argument("--episode")
    parser.add_argument("--proposal")
    parser.add_argument("--decision", choices=["approve", "request_changes", "reject"])
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--developer-token", default="")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "improve":
        if not args.episode:
            parser.error("--episode is required")
        with httpx.Client(
            base_url=settings.backend_url, headers={"Authorization": f"Bearer {settings.staff_token}"}
        ) as client:
            response = client.get(f"/api/jobs/{args.episode}/episode")
            response.raise_for_status()
        print(propose(response.json(), Path.cwd(), settings.data_dir / "proposals", args.publish))
    elif args.command == "review":
        if not args.proposal or not args.decision:
            parser.error("--proposal and --decision are required")
        print(
            json.dumps(
                review(args.proposal, args.decision, args.reviewer, args.developer_token, settings), indent=2
            )
        )
    elif args.command == "deploy":
        if not args.proposal:
            parser.error("--proposal is required")
        print(json.dumps(deploy(args.proposal, settings, args.developer_token), indent=2))
    elif args.command == "rollback":
        if not hmac.compare_digest(args.developer_token, settings.developer_token):
            raise PermissionError("Developer credential required")
        store = Store(settings.data_dir)
        if any(j["status"] not in TERMINAL for j in store.list_jobs()):
            raise ValueError("Wait until workers are idle")
        release = store.get_value("release")
        if not release.get("previous"):
            raise ValueError("No previous release")
        store.put_value("release", release["previous"])
        print(json.dumps(release["previous"], indent=2))
