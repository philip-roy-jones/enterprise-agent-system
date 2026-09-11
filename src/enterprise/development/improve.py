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
from enterprise.shared.config import Settings
from enterprise.server.store import Store
from enterprise.shared.identity import uid
from enterprise.development.improvement_analysis import analyze, patch_library, regression_source


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def regression_failures(path):
    from xml.etree import ElementTree

    if not Path(path).exists():
        return None
    tree = ElementTree.parse(path)
    return sum(
        int(suite.get("failures", 0)) + int(suite.get("errors", 0)) for suite in tree.iter("testsuite")
    )


def require_development():
    if os.getenv("EAS_DEV_PERMISSIONS") != "local-improvement":
        raise PermissionError(
            "Set EAS_DEV_PERMISSIONS=local-improvement to explicitly enable isolated development work"
        )


def propose(episode, root, output, publish=False):
    require_development()
    episodes = episode if isinstance(episode, list) else [episode]
    # Inspect the committed baseline used by the isolated checkout. Never silently
    # discard uncommitted implementation while constructing a reviewed candidate.
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Commit the development baseline before generating a proposal")
    analysis = analyze(episodes, root)
    if not analysis["additions"]:
        raise ValueError(analysis["rationale"])
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
    procedure = checkout / "src/enterprise/workflows/finance/procedures.py"
    patch_library(procedure, analysis)
    # Export only selected synthetic semantics and evidence hashes, never full
    # episodes, business values, screenshots, runtime paths or credentials.
    fixture = analysis
    fixture_path = checkout / "examples" / "improvement" / f"analysis-{proposal_id}.json"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(json.dumps(fixture, indent=2) + "\n")
    test = checkout / "tests" / f"test_learned_{proposal_id}.py"
    test.write_text(regression_source(analysis["additions"]))
    subprocess.run(
        [sys.executable, "-m", "ruff", "format", str(procedure), str(test)], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "add",
            "src/enterprise/workflows/finance/procedures.py",
            str(test.relative_to(checkout)),
            str(fixture_path.relative_to(checkout)),
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
        "PYTHONPATH": str(checkout / "src"),
        "EAS_DATA_DIR": str(folder / "test-runtime"),
        "EAS_MODEL_MODE": "simulated",
        "EAS_TEST_CANDIDATE_LABELS": "1",
    }
    checks_path = folder / "checks.txt"
    with checks_path.open("w") as check_log:
        checks = subprocess.Popen(
            [sys.executable, "-m", "pytest", "-q", "--junitxml=" + str(folder / "checks.xml")],
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
        episode_id=episodes[0]["job"]["id"],
        episode_ids=[e["job"]["id"] for e in episodes],
        analysis_sha=sha(fixture_path),
        analysis_file=str(fixture_path.relative_to(checkout)),
        source_sha=sha(procedure),
        patch_sha=sha(folder / "proposal.patch"),
        checks_sha=sha(folder / "checks.txt"),
        checks_passed=checks.returncode == 0,
        regression_failures=regression_failures(folder / "checks.xml"),
        review="pending",
        reviewer=None,
        approved_commit=None,
        version=analysis["version"],
        labels=analysis["library"]["labels"] + analysis["additions"],
    )
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    summary = f"""# Extend the amount resolver from verified staff demonstrations

{analysis["rationale"]}

The proposal adds {", ".join(repr(label) for label in analysis["additions"])}. Analysis joins the staff decision, executed field action, bound observation, field result, and final saved result. It inspects the existing graph and operation library before choosing this change.

- Proposed procedure version: {analysis["version"]}; candidate commit: `{commit}`.
- Selected episodes: {", ".join(e["job"]["id"] for e in episodes)}.
- Evidence and source hashes: `{fixture_path.relative_to(checkout)}`.
- Recurring failure groups: {json.dumps(analysis["recurring_gaps"])}.
- Regression checks: {"passed" if checks.returncode == 0 else "failed"}; see checks.txt and checks.xml.
- Generated browser regressions use the learned labels on fresh jobs for two records, reordered rows, and different layouts. No coordinates or invoice identifiers enter the reusable library.
- Developer review: pending. Passing checks do not authorize deployment.
- Rollback: restore the previous release registry for future jobs; running jobs stay pinned.

{analysis["limits"]}
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


def candidate_library(checkout):
    """Locate a pinned candidate's library, including pre-src proposal checkouts."""
    checkout = Path(checkout)
    current = checkout / "src/enterprise/workflows/finance/procedures.py"
    if current.is_file():
        return current, checkout / "src", "enterprise.workflows.finance.procedures"
    return checkout / "enterprise/procedures.py", checkout, "enterprise.procedures"


def verify_candidate(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    checkout = Path(manifest["checkout"])
    if git(checkout, "rev-parse", "HEAD") != manifest["commit"] or git(checkout, "status", "--porcelain"):
        raise ValueError("Candidate checkout changed; rerun proposal checks and review")
    for path, field in [
        (candidate_library(checkout)[0], "source_sha"),
        (folder / "proposal.patch", "patch_sha"),
        (folder / "checks.txt", "checks_sha"),
    ]:
        if sha(path) != manifest[field]:
            raise ValueError("Candidate or check evidence changed")
    if (
        manifest.get("analysis_file")
        and sha(checkout / manifest["analysis_file"]) != manifest["analysis_sha"]
    ):
        raise ValueError("Analysis evidence changed")
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
    _, candidate_path, candidate_module = candidate_library(manifest["checkout"])
    output = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import json;from "
            + candidate_module
            + " import AMOUNT_LABELS,GRAPH_VERSION,resolve_amount_label;assert AMOUNT_LABELS and all(resolve_amount_label([label]) == label for label in AMOUNT_LABELS);print(json.dumps({'labels':list(AMOUNT_LABELS),'version':GRAPH_VERSION}))",
        ],
        cwd=manifest["checkout"],
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": str(candidate_path)},
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


def rollback(settings, token):
    if not hmac.compare_digest(token, settings.developer_token):
        raise PermissionError("Developer credential required")
    store = Store(settings.data_dir)
    with store.db() as db:
        active = db.execute(
            "SELECT 1 FROM jobs WHERE json_extract(data,'$.status') NOT IN ('completed','cancelled','rejected','denied','failed') LIMIT 1"
        ).fetchone()
        if active:
            raise ValueError("Wait until workers are idle")
        release = json.loads(db.execute("SELECT data FROM kv WHERE key='release'").fetchone()[0])
        if not release.get("previous"):
            raise ValueError("No previous release")
        db.execute("UPDATE kv SET data=? WHERE key='release'", (json.dumps(release["previous"]),))
        return release["previous"]


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["improve", "review", "deploy", "rollback"])
    parser.add_argument(
        "--episode", action="append", help="Accepted episode ID; repeat to analyze recurring gaps"
    )
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
            episodes = []
            for episode_id in args.episode:
                response = client.get(f"/api/jobs/{episode_id}/episode")
                response.raise_for_status()
                episodes.append(response.json())
        print(propose(episodes, Path.cwd(), settings.data_dir / "proposals", args.publish))
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
        print(json.dumps(rollback(settings, args.developer_token), indent=2))
