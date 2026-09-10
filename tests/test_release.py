import json
import subprocess
import pytest
from enterprise.config import Settings
from enterprise.improve import deploy, review, sha, verify_candidate, require_development
from enterprise.store import Store
from enterprise.types import JobInput


@pytest.fixture
def candidate(tmp_path):
    folder = tmp_path / "proposal"
    checkout = folder / "checkout"
    (checkout / "enterprise").mkdir(parents=True)
    (checkout / "enterprise" / "__init__.py").write_text("")
    source = checkout / "enterprise" / "procedures.py"
    source.write_text(
        'GRAPH_VERSION="v2"\nAMOUNT_LABELS=("Correction amount","Adjusted total")\ndef resolve_amount_label(labels):\n    return next((l for l in AMOUNT_LABELS if l in labels),None)\n'
    )
    (checkout / ".gitignore").write_text("__pycache__/\n")
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "-qm",
            "Checked test candidate",
        ],
        check=True,
    )
    commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    (folder / "proposal.patch").write_text("Synthetic fixture patch")
    (folder / "checks.txt").write_text("Synthetic fixture checks passed")
    manifest = {
        "checkout": str(checkout),
        "commit": commit,
        "source_sha": sha(source),
        "patch_sha": sha(folder / "proposal.patch"),
        "checks_sha": sha(folder / "checks.txt"),
        "checks_passed": True,
        "review": "pending",
        "approved_commit": None,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder


def test_proposal_generation_requires_explicit_development_scope(monkeypatch):
    monkeypatch.delenv("EAS_DEV_PERMISSIONS", raising=False)
    with pytest.raises(PermissionError):
        require_development()


def test_deployment_requires_separate_developer_approval(candidate, tmp_path):
    settings = Settings(data_dir=tmp_path / "live")
    with pytest.raises(PermissionError, match="Developer credential"):
        review(candidate, "approve", "Reviewer", settings.worker_token, settings)
    with pytest.raises(PermissionError, match="approval"):
        deploy(candidate, settings, settings.developer_token)
    review(candidate, "approve", "Test developer", settings.developer_token, settings)
    result = deploy(candidate, settings, settings.developer_token)
    assert result["version"] == "v2" and "Adjusted total" in result["labels"]
    assert result["previous"]["version"] == "v1"


def test_new_job_pins_release_and_active_job_blocks_deployment(candidate, tmp_path):
    settings = Settings(data_dir=tmp_path / "live")
    store = Store(settings.data_dir)
    old = store.create_job(JobInput(invoice_id="INV-1042").model_dump())
    review(candidate, "approve", "Test developer", settings.developer_token, settings)
    with pytest.raises(ValueError, match="idle"):
        deploy(candidate, settings, settings.developer_token)
    store.stop(old["id"])
    deploy(candidate, settings, settings.developer_token)
    new = store.create_job(JobInput(invoice_id="INV-1043").model_dump())
    assert old["graph_version"] == "v1" and new["graph_version"] == "v2"
    assert store.get_job(old["id"])["amount_labels"] == ["Correction amount"]


@pytest.mark.parametrize("decision", ["reject", "request_changes"])
def test_rejected_or_changes_requested_candidate_cannot_deploy(candidate, tmp_path, decision):
    settings = Settings(data_dir=tmp_path / "live")
    review(candidate, decision, "Test developer", settings.developer_token, settings)
    with pytest.raises(PermissionError):
        deploy(candidate, settings, settings.developer_token)


@pytest.mark.parametrize("artifact", ["checks.txt", "proposal.patch", "checkout/enterprise/procedures.py"])
def test_changed_candidate_or_evidence_invalidates_review(candidate, tmp_path, artifact):
    settings = Settings(data_dir=tmp_path / "live")
    review(candidate, "approve", "Test developer", settings.developer_token, settings)
    path = candidate / artifact
    path.write_text(path.read_text() + "\nchanged")
    with pytest.raises(ValueError):
        verify_candidate(candidate)


def test_published_candidate_requires_remote_ci_on_approved_commit(candidate, tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "live")
    manifest = review(candidate, "approve", "Test developer", settings.developer_token, settings)
    manifest["pull_request"] = "https://github.com/example/fixture/pull/1"
    (candidate / "manifest.json").write_text(json.dumps(manifest))
    original = subprocess.check_output

    def failing_ci(command, **kwargs):
        if command[0] == "gh":
            return json.dumps(
                {
                    "headRefOid": manifest["commit"],
                    "statusCheckRollup": [
                        {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}
                    ],
                }
            )
        return original(command, **kwargs)

    monkeypatch.setattr(subprocess, "check_output", failing_ci)
    with pytest.raises(ValueError, match="GitHub CI"):
        deploy(candidate, settings, settings.developer_token)
