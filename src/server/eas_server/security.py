"""Resource authorization. Network callers never supply their own authority."""

import hashlib
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from eas_shared.identity import canonical

SCOPE = ("organization_id", "department_id", "role_id", "company_id")


class Grant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: str
    department_id: str
    role_id: str
    company_id: str
    actions: list[str]
    capabilities: list[str] = Field(default_factory=list)
    own_only: bool = True

    def matches(self, resource):
        return all(getattr(self, k) == "*" or getattr(self, k) == resource.get(k) for k in SCOPE)


class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    kind: str = Field(pattern=r"^(human|planner|executor|admission)$")
    name: str
    enabled: bool = True
    token_sha256: str | None = None
    worker_id: str | None = None
    grants: list[Grant] = Field(default_factory=list)

    def permits(self, action, resource):
        return self.enabled and any(
            action in g.actions
            and g.matches(resource)
            and (not g.own_only or not resource.get("staff_id") or resource["staff_id"] == self.id)
            for g in self.grants
        )


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    principals: list[Principal]


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Security:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.path = Path(settings.identity_file) if settings.identity_file else None
        if not self.path and (
            settings.bind_host not in {"127.0.0.1", "::1", "localhost"}
            or urlsplit(settings.public_url).hostname not in {"127.0.0.1", "::1", "localhost"}
        ):
            raise ValueError(
                "Remote development requires an explicit identity registry; default demo credentials are loopback-only"
            )
        if settings.auth_mode not in {"development", "password"}:
            raise ValueError("EAS_AUTH_MODE must be development or password")
        if settings.auth_mode == "password" and not self.path:
            raise ValueError("Password login requires an explicit identity registry")
        if settings.auth_mode == "password" and (
            urlsplit(settings.public_url).hostname not in {"127.0.0.1", "::1", "localhost"}
            and urlsplit(settings.public_url).scheme != "https"
        ):
            raise ValueError("Remote password login requires HTTPS")
        with store.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS security_sessions(id TEXT PRIMARY KEY, principal TEXT, expires REAL,
                    csrf TEXT, revision TEXT);
                CREATE TABLE IF NOT EXISTS security_audit(seq INTEGER PRIMARY KEY, at REAL, actor TEXT,
                    action TEXT, resource TEXT);
                CREATE TABLE IF NOT EXISTS artifact_owners(id TEXT PRIMARY KEY, job_id TEXT, producer TEXT);
            """)
        self.registry()  # Bad or missing configuration fails at startup.
        from eas_server.packages import Packages

        self.packages = Packages(self)
        from eas_server.accounts import Accounts

        self.accounts = Accounts(self)
        from eas_server.employees import Workforce

        self.workforce = Workforce(self)
        store.workforce = self.workforce

    def registry(self):
        if self.path:
            data = Registry.model_validate_json(self.path.read_text())
        else:
            if self.settings.auth_mode != "development":
                raise ValueError("Explicit identities required")
            # Explicit development fixtures only; no password-mode fallback.
            base = dict(
                organization_id="acme",
                department_id="*",
                role_id="*",
                company_id="*",
                capabilities=["read", "navigate", "draft"],
            )
            humans = [
                "request",
                "read",
                "approve",
                "control",
                "accept",
                "knowledge",
                "skills",
                "manage_skills",
            ]
            entries = [
                ("staff", "human", self.settings.staff_token, humans, True),
                ("developer", "human", self.settings.developer_token, humans + ["supervise"], False),
                ("development-executor", "executor", self.settings.worker_token, ["execute"], False),
                ("development-planner", "planner", self.settings.planner_token, ["execute"], False),
                ("development-admission", "admission", self.settings.admission_token, ["admit"], False),
            ]
            data = Registry(
                principals=[
                    Principal(
                        id=i,
                        kind=k,
                        name="Development fixture: " + i,
                        token_sha256=token_hash(t),
                        worker_id="development-desktop" if k != "human" else None,
                        grants=[Grant(**base, actions=a, own_only=own)],
                    )
                    for i, k, t, a, own in entries
                ]
            )
        ids = [p.id for p in data.principals]
        tokens = [p.token_sha256 for p in data.principals if p.token_sha256]
        if len(ids) != len(set(ids)) or len(tokens) != len(set(tokens)):
            raise ValueError("Duplicate security identity or credential")
        if any(p.kind != "human" and not p.worker_id for p in data.principals):
            raise ValueError("Service identities require a registered worker_id")
        if data.version != 1:
            raise ValueError("Unsupported identity registry version")
        if self.settings.auth_mode == "password":
            demo_hashes = {
                token_hash("local-" + name + "-demo")
                for name in ("staff", "developer", "worker", "planner", "admission")
            }
            if any(p.token_sha256 in demo_hashes for p in data.principals):
                raise ValueError("Managed identities cannot use known development credentials")
        return data

    def revision(self):
        return token_hash(canonical(self.registry().model_dump()))

    def get(self, identity):
        p = next((p for p in self.registry().principals if p.id == identity and p.enabled), None)
        if not p:
            raise HTTPException(401, "Identity unavailable")
        return p

    def authenticate_token(self, token):
        if not isinstance(token, str) or not token or len(token) > 20000:
            raise HTTPException(401, "Authentication required")
        for p in self.registry().principals:
            if p.enabled and p.token_sha256 and secrets.compare_digest(token_hash(token), p.token_sha256):
                if p.kind == "human" and self.settings.auth_mode != "development":
                    break
                return p
        raise HTTPException(401, "Identity unavailable")

    def principal(self, request):
        bearer = request.headers.get("authorization", "")
        if bearer:
            if not bearer.startswith("Bearer "):
                raise HTTPException(401, "Bearer authentication required")
            return self.authenticate_token(bearer[7:])
        token = request.cookies.get("eas_session", "")
        with self.store.db() as db:
            row = db.execute("SELECT * FROM security_sessions WHERE id=?", (token_hash(token),)).fetchone()
        if not row or row["expires"] <= time.time() or row["revision"] != self.revision():
            raise HTTPException(401, "Sign in required")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if not secrets.compare_digest(request.headers.get("x-eas-csrf", ""), row["csrf"]):
                raise HTTPException(403, "CSRF validation failed")
        return self.get(row["principal"])

    def session(self, token):
        return self.create_session(self.authenticate_token(token))

    def create_session(self, p, *, db=None):
        if p.kind != "human":
            raise HTTPException(403, "Human sign-in required")
        session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        from contextlib import nullcontext

        with nullcontext(db) if db is not None else self.store.db() as connection:
            connection.execute(
                "INSERT INTO security_sessions VALUES(?,?,?,?,?)",
                (token_hash(session), p.id, time.time() + 3600, csrf, self.revision()),
            )
        return p, session, csrf

    def authorize(self, p, action, resource):
        p = self.get(p.id)
        if not p.permits(action, resource):
            raise HTTPException(403, "Access denied")
        return p

    def job(self, p, job_id, action="read"):
        try:
            job = self.store.get_job(job_id)
        except ValueError:
            raise HTTPException(404, "Resource unavailable") from None
        if not self.get(p.id).permits(action, job):
            raise HTTPException(404, "Resource unavailable")
        return job

    def jobs(self, p):
        p = self.get(p.id)
        return [j for j in self.store.list_jobs() if p.permits("read", j)]

    def request(self, p, values):
        self.authorize(p, "request", values)
        capabilities = {
            c for g in p.grants if "request" in g.actions and g.matches(values) for c in g.capabilities
        }
        if set(values["permissions"]) - capabilities:
            raise HTTPException(403, "Requested capability is not permitted")
        return values

    def audit(self, p, action, resource):
        with self.store.db() as db:
            db.execute(
                "INSERT INTO security_audit(at,actor,action,resource) VALUES(?,?,?,?)",
                (time.time(), p.id, action, str(resource)),
            )

    def learning(self, p):
        visible = {j["id"] for j in self.jobs(p)}
        status = self.store.learning_status()

        def references(value):
            result = set()
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"episode_id", "job_id"} and isinstance(item, str):
                        result.add(item)
                    elif key in {"evidence_ids", "related_job_ids"} and isinstance(item, list):
                        result.update(x for x in item if isinstance(x, str))
                    else:
                        result.update(references(item))
            elif isinstance(value, list):
                for item in value:
                    result.update(references(item))
            # A judgment cites derived evidence such as "<request>:comparison".
            # Its confidentiality is inherited from the owning request.
            return {identity.split(":", 1)[0] for identity in result}

        queue = [i for i in status["queue"] if i.get("job_id") in visible and references(i) <= visible]
        registries = []
        for r in status["registries"]:
            versions = [v for v in r.get("versions", []) if self.packages.allowed(p, v)]
            # Remaining registry fields can carry historical private package content.
            registries.append(
                {
                    "versions": versions,
                    "history": [
                        h
                        for h in r.get("history", [])
                        if any(
                            v["skill_id"] == h.get("skill_id") and v["version"] == h.get("version")
                            for v in versions
                        )
                    ],
                    "active": {
                        k: v
                        for k, v in r.get("active", {}).items()
                        if any(s["skill_id"] == k for s in versions)
                    },
                }
            )
        versions = [v for r in registries for v in r["versions"]]
        queue.extend(
            i
            for i in status["queue"]
            if i.get("kind") == "skill_change"
            and any(
                v["skill_id"] == i.get("skill_id")
                and v.get("worker_id") == i.get("target_worker_id")
                and (i.get("version") is None or v["version"] == i["version"])
                for v in versions
            )
        )
        return {"queue": queue, "registries": registries}
