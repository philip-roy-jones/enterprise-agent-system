"""Local operator migration after draining the worker; no agent-callable entry point."""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from eas_shared.identity import canonical
from eas_harness.config import Settings
from eas_harness.maintenance import subprocess_json
from eas_harness.remote import RemoteStore
from eas_harness.skill_library import SkillLibrary, validate_spec


def migrate(old_root, settings):
    old_root = Path(old_root)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    history = old_root / "session-context.sqlite"
    target = settings.data_dir / history.name
    if history.exists() and not target.exists():
        with sqlite3.connect(history) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
    library = SkillLibrary(settings.data_dir)
    old = old_root / "skills" / "registry.sqlite"
    report = {
        "history_preserved": target.exists(),
        "requalified": [],
        "quarantined": [],
        "model_mode": "none",
    }
    if old.exists():
        store = RemoteStore(settings.backend_url, settings.admission_token)
        try:
            with sqlite3.connect(old) as db:
                rows = db.execute(
                    "SELECT v.id,v.version,v.spec FROM versions v JOIN active a ON v.id=a.id AND v.version=a.version"
                ).fetchall()
            for skill_id, version, raw in rows:
                try:
                    if hashlib.sha256(raw.encode()).hexdigest() != version:
                        raise ValueError("Legacy database hash mismatch")
                    spec = validate_spec(json.loads(raw)).model_dump()
                    folder = old.parent / skill_id / version
                    if (folder / "manifest.json").read_text(encoding="utf-8").strip() != raw or (
                        folder / "SKILL.md"
                    ).read_text(encoding="utf-8") != spec["instructions"]:
                        raise ValueError("Legacy files changed")
                    for resource, contents in spec["supporting_files"].items():
                        path = folder / resource
                        if (
                            path.is_symlink()
                            or not path.resolve().is_relative_to(folder.resolve())
                            or path.read_text(encoding="utf-8") != contents
                        ):
                            raise ValueError("Legacy resource changed")
                    if not spec["evidence_ids"]:
                        # Upgrade only the exact trusted bundled seed; preserve
                        # the old immutable version as inactive history.
                        from eas_harness.skill_library import SCOPE

                        library.seed(
                            {**{k: spec[k] for k in SCOPE}, "app_version": spec["application_version"]}
                        )
                        active = next(
                            (
                                v
                                for v in library.metadata()["versions"]
                                if v["skill_id"] == skill_id and v["active"]
                            ),
                            None,
                        )
                        if active and active["version"] != version:
                            report["requalified"].append(
                                {
                                    "skill_id": skill_id,
                                    "version": active["version"],
                                    "checks": "Trusted bundled seed upgrade",
                                }
                            )
                            continue
                    checks = subprocess_json("eas_harness.admission_process", spec)
                    digest = hashlib.sha256(canonical(spec).encode()).hexdigest()
                    entry = {
                        **spec,
                        "version": digest,
                        "package": spec,
                        "active": True,
                        "migration_checks": checks,
                    }
                    # Recheck source evidence and audience before local activation.
                    store.skills_publish(
                        {"versions": library.metadata()["versions"] + [entry], "history": library.history()}
                    )
                    # Only this drained, operator-owned migration path may
                    # replace an existing dependency binding, after fresh tests.
                    with library.db() as db:
                        db.execute(
                            "UPDATE dependencies SET digest=? WHERE id=? AND version=?",
                            (library.dependency_digest(), skill_id, digest),
                        )
                    library.install(spec)
                    report["requalified"].append({"skill_id": skill_id, "version": digest, "checks": checks})
                except (ValueError, PermissionError, OSError) as error:
                    report["quarantined"].append(
                        {"skill_id": skill_id, "version": version, "reason": str(error)}
                    )
            store.skills_publish(library.metadata())
        finally:
            store.client.close()
    (settings.data_dir / "security-migration.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {
        "history_preserved": report["history_preserved"],
        "requalified": len(report["requalified"]),
        "quarantined": len(report["quarantined"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-root", required=True)
    args = parser.parse_args()
    print(json.dumps(migrate(args.from_root, Settings())))
