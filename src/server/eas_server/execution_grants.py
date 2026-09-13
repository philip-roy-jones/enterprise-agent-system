"""Short-lived authority, consumed with the action ledger transaction."""

import os
import time
import json
import secrets
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from eas_shared.identity import canonical, fingerprint
from eas_shared.types import Stale


class ExecutionGrants:
    def __init__(self, security):
        self.security, self.store = security, security.store
        path = self.store.root / "execution-signing-key.pem"
        if not path.exists():
            data = Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
            except FileExistsError:
                pass
        self.key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        self.public = (
            self.key.public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode()
        )
        with self.store.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_grants(id TEXT PRIMARY KEY, payload TEXT, consumed INTEGER)"
            )

    def issue(self, p, args):
        job_id, owner, epoch, invocation, action, approval_id = args
        job = self.store.check(job_id, owner, epoch)
        a = next((a for a in self.store.approvals(job_id) if a["id"] == approval_id), None)
        if not a or a["status"] not in {"approved", "corrected"} or a["invocation"] != invocation:
            raise Stale("An available staff approval is required")
        if (
            action
            != {
                "name": a["name"],
                "arguments": a.get("corrected_arguments", a["arguments"]),
                "observation_revision": a["observation"]["revision"],
            }
            or a["epoch"] != epoch
        ):
            raise Stale("Action differs from the approved operation")
        from eas_server.worker_api import contracts_for
        from jsonschema import Draft202012Validator

        contract = contracts_for(job).get(action["name"])
        if (
            not contract
            or contract != a["operation_spec"]
            or contract["permission"] not in job["permissions"]
        ):
            raise Stale("Operation contract or permission changed")
        if not Draft202012Validator(contract["input_schema"]).is_valid(action["arguments"]):
            raise Stale("Approved arguments do not satisfy the operation contract")
        targets = {
            **job.get("inputs", {}),
            **{
                k: job.get(k)
                for k in ("organization_id", "department_id", "role_id", "company_id", "invoice_id")
            },
        }
        for field, target in targets.items():
            if field in action["arguments"] and target is not None and action["arguments"][field] != target:
                raise Stale("Approved target is outside the request's scope")
        if action["name"] in {"read_skill", "read_skill_resource", "run_workflow"}:
            package = self.security.packages.get(
                p, job, action["arguments"]["skill_id"], action["arguments"]["version"]
            )
            if action["name"] != "read_skill_resource" and not package.get("active"):
                raise Stale("Skill was suspended before execution")
        approver = self.security.get(a["decision"]["actor"])
        self.security.authorize(approver, "approve", job)
        now = int(time.time())
        payload = dict(
            iss="enterprise-agent-system",
            aud=p.id,
            worker_id=p.worker_id,
            sub=job["staff_id"],
            approver=approver.id,
            iat=now,
            exp=now + 30,
            jti=secrets.token_hex(16),
            policy=self.security.revision(),
            job_id=job_id,
            invocation=invocation,
            approval_id=approval_id,
            action_hash=fingerprint(action),
            epoch=epoch,
            owner=owner,
            scope={
                k: job.get(k)
                for k in ("organization_id", "department_id", "role_id", "company_id", "record_id")
            },
            contract_hash=fingerprint(a["operation_spec"]),
        )
        payload["skill_bindings"] = self.bindings(job)
        with self.store.db() as db:
            db.execute("INSERT INTO execution_grants VALUES(?,?,0)", (payload["jti"], canonical(payload)))
        return {
            "grant": jwt.encode(payload, self.key, algorithm="EdDSA"),
            "public_key": self.public,
            "audience": p.id,
            "protocol": 2,
        }

    def consumer(self, p, token, args):
        if not token:
            raise Stale("A server execution grant is required")
        try:
            payload = jwt.decode(
                token,
                self.key.public_key(),
                algorithms=["EdDSA"],
                audience=p.id,
                issuer="enterprise-agent-system",
                options={"require": ["exp", "iat", "jti", "aud", "sub"]},
            )
        except jwt.PyJWTError:
            raise Stale("Invalid or expired execution grant") from None
        job_id, owner, epoch, invocation, action, approval_id = args
        if any(
            payload.get(k) != v
            for k, v in dict(
                job_id=job_id,
                owner=owner,
                epoch=epoch,
                invocation=invocation,
                approval_id=approval_id,
                worker_id=p.worker_id,
                action_hash=fingerprint(action),
                policy=self.security.revision(),
            ).items()
        ):
            raise Stale("Execution grant scope changed")

        def consume(db, job, lease):
            if (
                payload.get("skill_bindings") != self.bindings(job)
                or payload["policy"] != self.security.revision()
            ):
                raise Stale("Pinned skill or authorization changed")
            row = db.execute(
                "SELECT payload,consumed FROM execution_grants WHERE id=?", (payload["jti"],)
            ).fetchone()
            if not row or row[1] or json.loads(row[0]) != payload or payload["exp"] <= time.time():
                raise Stale("Execution grant expired or consumed")
            db.execute("UPDATE execution_grants SET consumed=1 WHERE id=?", (payload["jti"],))

        return consume

    @staticmethod
    def bindings(job):
        return fingerprint(
            {
                k: {field: r[field] for field in ("skill_id", "version")}
                for k, r in job.get("workflow_runs", {}).items()
            }
        )
