"""Versioned declarative skills. No imports, eval, shell, or generated Python execution."""

import hashlib
import json
from pathlib import Path
import sqlite3
import time
import sys
from importlib.metadata import version as package_version

from eas_shared.identity import canonical
from eas_shared.skills import SkillSpec

SCOPE = ("organization_id", "department_id", "role_id", "company_id")


def validate_spec(spec):
    spec = SkillSpec.model_validate(spec)
    steps = spec.steps
    if spec.role_id == "campaign_review":
        if spec.capability_version != "marketing-1" or spec.department_id != "marketing":
            raise ValueError("Marketing capability binding mismatch")
        if spec.steps and spec.steps != ["validate", "establish", "report", "complete"]:
            raise ValueError("Marketing workflows must validate, establish, report and complete")
        return spec
    if spec.capability_version != "finance-1":
        raise ValueError("Unknown role capability binding")
    if any(not label.strip() or len(label) > 120 for label in spec.amount_labels):
        raise ValueError("Invalid field label")
    if not steps:
        # Guidance can use existing approved tools without inventing a graph.
        return spec
    if steps[:3] != ["validate", "establish", "compare"] or steps[-1] != "complete":
        raise ValueError("Workflows must validate, establish and compare before completing")
    if len(set(steps)) != len(steps):
        raise ValueError("Repeated business operations are not permitted")
    if "save" in steps or "prepare" in steps:
        tail = [n for n in steps[3:] if n != "judge"]
        if tail not in (
            ["prepare", "save", "verify", "complete"],
            ["report", "prepare", "save", "verify", "complete"],
        ):
            raise ValueError("Draft workflows must prepare, save, verify and complete in order")
    elif [n for n in steps[3:] if n != "judge"] != ["report", "complete"]:
        raise ValueError("Read-only workflows must report and complete")
    if "judge" in steps and steps.index("judge") != 3:
        raise ValueError("Judgment requires comparison evidence")
    return spec


class SkillLibrary:
    def __init__(self, root):
        self.root = Path(root) / "skills"
        self.root.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS versions(id TEXT, version TEXT, spec TEXT, created REAL, PRIMARY KEY(id,version))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS dependencies(id TEXT, version TEXT, digest TEXT, PRIMARY KEY(id,version))"
            )
            db.execute("CREATE TABLE IF NOT EXISTS active(id TEXT PRIMARY KEY, version TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS changes(seq INTEGER PRIMARY KEY, data TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS processed(episode TEXT PRIMARY KEY, result TEXT)")

    @staticmethod
    def dependency_digest():
        root = Path(__file__).parent
        files = [
            "execution.py",
            "screenshots.py",
            "executor.py",
            "adapters/adapter.py",
            "adapters/windows_adapter.py",
            "adapters/accessibility_adapter.py",
            "skill_runtime.py",
            "integrations/finance/runtime.py",
            "integrations/finance/operations.py",
            "judgment.py",
            "contracts.py",
            "integrations/marketing.py",
        ]
        hashes = {f: hashlib.sha256((root / f).read_bytes()).hexdigest() for f in files}
        hashes["skill_schema"] = hashlib.sha256(canonical(SkillSpec.model_json_schema()).encode()).hexdigest()
        hashes.update(
            {
                name: package_version(name)
                for name in ("langgraph", "deepagents", "enterprise-agent-contracts")
            }
        )
        return hashlib.sha256(canonical(hashes).encode()).hexdigest()

    def db(self):
        return sqlite3.connect(self.root / "registry.sqlite", timeout=30)

    def install(self, spec, *, expected_previous=None, seed=False, admission=None):
        spec = validate_spec(spec).model_dump()
        payload = canonical(spec)
        version = hashlib.sha256(payload.encode()).hexdigest()
        key = spec["skill_id"]
        with self.db() as db:
            current = db.execute("SELECT version FROM active WHERE id=?", (key,)).fetchone()
            if expected_previous is not None and (current[0] if current else "") != expected_previous:
                raise ValueError("Skill changed while candidate was being evaluated")
            db.execute("INSERT OR IGNORE INTO versions VALUES(?,?,?,?)", (key, version, payload, time.time()))
            db.execute(
                "INSERT OR IGNORE INTO dependencies VALUES(?,?,?)", (key, version, self.dependency_digest())
            )
            bound = db.execute(
                "SELECT digest FROM dependencies WHERE id=? AND version=?", (key, version)
            ).fetchone()
            if bound[0] != self.dependency_digest():
                raise ValueError("Existing package requires requalification after dependency change")
            folder = self.root / key / version
            folder.mkdir(parents=True, exist_ok=True)
            # Source of truth is the hash-checked database row; files are portable exports.
            (folder / "manifest.json").write_text(payload + "\n", encoding="utf-8")
            (folder / "SKILL.md").write_text(spec["instructions"], encoding="utf-8")
            for resource, content in spec.get("supporting_files", {}).items():
                path = folder / resource
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
                    raise PermissionError("Supporting file escapes its package")
                path.write_text(content, encoding="utf-8")
            db.execute("INSERT OR REPLACE INTO active VALUES(?,?)", (key, version))
            if admission:
                result = {
                    **admission["result"],
                    "status": "activated",
                    "skill_id": key,
                    "version": version,
                    "previous": current[0] if current else None,
                }
                db.execute(
                    "INSERT OR REPLACE INTO processed VALUES(?,?)", (admission["episode"], canonical(result))
                )
            db.execute(
                "INSERT INTO changes(data) VALUES(?)",
                (
                    canonical(
                        dict(
                            skill_id=key,
                            version=version,
                            previous=current[0] if current else None,
                            action="seeded" if seed else "activated",
                            at=time.time(),
                        )
                    ),
                ),
            )
        return version

    def seed(self, job):
        if job["role_id"] != "invoice_correction":
            return
        # Trusted bundled procedure, not learned evidence. Never overwrite a learned revision.
        name = "invoice_correction"
        previous = ""
        with self.db() as db:
            if db.execute("SELECT 1 FROM versions WHERE id=?", (name,)).fetchone():
                from importlib.resources import files

                legacy = json.loads(files("eas_shared").joinpath("finance_seed_legacy.json").read_text())
                active = db.execute(
                    "SELECT v.version,v.spec FROM versions v JOIN active a ON a.id=v.id AND a.version=v.version WHERE v.id=?",
                    (name,),
                ).fetchone()
                if not active:
                    return
                spec = json.loads(active[1])
                if {
                    k: v for k, v in spec.items() if k not in {*SCOPE, "application_version"}
                } != legacy or any(spec[k] != job[k] for k in SCOPE):
                    return
                previous = active[0]
        folder = Path(__file__).resolve().parent.parent / "skills" / name
        if not folder.exists():
            folder = Path(sys.prefix) / "share" / "enterprise-agent-system" / "skills" / name
        data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        data.update(
            instructions=(folder / "SKILL.md").read_text(encoding="utf-8"),
            application_version=job["app_version"],
            **{k: job[k] for k in SCOPE},
        )
        self.install(data, seed=True, expected_previous=previous)

    def get(self, skill_id, version, job, *, active_only=False):
        with self.db() as db:
            row = db.execute(
                "SELECT spec FROM versions WHERE id=? AND version=?", (skill_id, version)
            ).fetchone()
            active = db.execute("SELECT version FROM active WHERE id=?", (skill_id,)).fetchone()
            dependency = db.execute(
                "SELECT digest FROM dependencies WHERE id=? AND version=?", (skill_id, version)
            ).fetchone()
        if not row or hashlib.sha256(row[0].encode()).hexdigest() != version:
            raise PermissionError("Unknown or modified skill version")
        if not dependency or dependency[0] != self.dependency_digest():
            raise PermissionError("Skill dependencies changed after admission")
        folder = self.root / skill_id / version
        if (
            not folder.exists()
            or (folder / "manifest.json").read_text(encoding="utf-8").strip() != row[0]
            or (folder / "SKILL.md").read_text(encoding="utf-8") != json.loads(row[0])["instructions"]
        ):
            raise PermissionError("Installed skill files changed after admission")
        spec = validate_spec(json.loads(row[0])).model_dump()
        for resource, content in spec.get("supporting_files", {}).items():
            path = folder / resource
            if (
                path.is_symlink()
                or not path.resolve().is_relative_to(folder.resolve())
                or not path.is_file()
                or path.read_text(encoding="utf-8") != content
            ):
                raise PermissionError("Installed supporting file changed after admission")
        if any(spec[k] != job[k] for k in SCOPE) or spec["application_version"] != job["app_version"]:
            raise PermissionError("Skill is outside this request's scope or application version")
        if active_only and (not active or active[0] != version):
            raise PermissionError("Skill version is not active")
        return spec

    def catalog(self, job):
        with self.db() as db:
            rows = db.execute("SELECT id,version FROM active").fetchall()
        result = []
        for key, version in rows:
            try:
                s = self.get(key, version, job, active_only=True)
            except PermissionError:
                continue
            result.append(
                {k: s[k] for k in ("skill_id", "title", "description", "task")}
                | {"version": version, "has_graph": bool(s["steps"])}
            )
        return result

    def resource(self, skill_id, version, path, job):
        if job.get("skill_reads", {}).get(skill_id) != version:
            raise PermissionError("Read this exact skill version before its supporting files")
        spec = self.get(skill_id, version, job)
        if path not in spec.get("supporting_files", {}):
            raise PermissionError("Unknown supporting file in this skill version")
        text = spec["supporting_files"][path]
        return {
            "skill_id": skill_id,
            "version": version,
            "path": path,
            "text": text,
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
        }

    def change(self, skill_id, version=None):
        if version:
            with self.db() as db:
                row = db.execute(
                    "SELECT spec FROM versions WHERE id=? AND version=?", (skill_id, version)
                ).fetchone()
            if not row:
                raise ValueError("Unknown skill version")
            spec = json.loads(row[0])
            self.get(skill_id, version, {**spec, "app_version": spec["application_version"]})
        with self.db() as db:
            previous = db.execute("SELECT version FROM active WHERE id=?", (skill_id,)).fetchone()
            if (
                version
                and not db.execute(
                    "SELECT 1 FROM versions WHERE id=? AND version=?", (skill_id, version)
                ).fetchone()
            ):
                raise ValueError("Unknown skill version")
            db.execute("DELETE FROM active WHERE id=?", (skill_id,))
            if version:
                db.execute("INSERT INTO active VALUES(?,?)", (skill_id, version))
            db.execute(
                "INSERT INTO changes(data) VALUES(?)",
                (
                    canonical(
                        dict(
                            skill_id=skill_id,
                            version=version,
                            previous=previous[0] if previous else None,
                            action="rollback" if version else "suspended",
                            at=time.time(),
                        )
                    ),
                ),
            )

    def history(self):
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM changes ORDER BY seq")]

    def metadata(self):
        with self.db() as db:
            active = dict(db.execute("SELECT id,version FROM active"))
            versions = []
            for key, version, payload, created in db.execute("SELECT * FROM versions"):
                spec = json.loads(payload)
                versions.append(
                    {
                        k: spec[k]
                        for k in (
                            *SCOPE,
                            "skill_id",
                            "title",
                            "description",
                            "application_version",
                            "evidence_ids",
                            "steps",
                        )
                    }
                    | {
                        "version": version,
                        "created_at": created,
                        "active": active.get(key) == version,
                        "instructions": spec["instructions"],
                        "resources": list(spec.get("supporting_files", {})),
                        "package": spec,
                    }
                )
        return {"versions": versions, "history": self.history()}
