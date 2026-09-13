"""Trusted local provisioning. No administrative mutation endpoint is exposed to agents."""

import argparse
import json
import os
from pathlib import Path
import secrets
from eas_server.security import Grant, Principal, Registry, token_hash


def private_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value)


def save_registry(path, registry):
    temporary = path.with_suffix(".pending")
    private_write(temporary, registry.model_dump_json(indent=2) + "\n")
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    human = commands.add_parser("add-human")
    human.add_argument("--id", required=True)
    human.add_argument("--name", required=True)
    human.add_argument("--grants", type=Path, required=True, help="JSON array of explicit grants")
    human.add_argument("--development-token-file", type=Path)
    invite = commands.add_parser("invite-human", help="Create a one-hour password setup/reset link")
    invite.add_argument("--id", required=True)
    invite.add_argument("--email", required=True)
    invite.add_argument("--data-dir", type=Path, required=True)
    invite.add_argument("--public-url", required=True)
    invite.add_argument("--setup-file", type=Path, required=True)
    worker = commands.add_parser("enroll-worker")
    worker.add_argument("--id", required=True, help="Unique physical desktop identity")
    worker.add_argument("--profile", type=Path, required=True)
    worker.add_argument("--backend-url", required=True)
    worker.add_argument("--output", type=Path, required=True)
    worker.add_argument("--development", action="store_true")
    revoke = commands.add_parser("revoke")
    revoke.add_argument("--id", required=True, help="Person, service principal, or entire worker ID")
    args = parser.parse_args()
    if args.command == "init":
        private_write(args.registry, Registry(principals=[]).model_dump_json(indent=2) + "\n")
        print("Created empty identity registry; no identities are authorized yet.")
        return
    registry = Registry.model_validate_json(args.registry.read_text())
    if args.command == "invite-human":
        from urllib.parse import urlencode
        from eas_server.config import Settings
        from eas_server.security import Security
        from eas_server.store import Store

        if args.setup_file.exists():
            raise ValueError("Setup output already exists; choose a new protected file")
        security = Security(
            Settings(
                data_dir=args.data_dir,
                identity_file=str(args.registry),
                public_url=args.public_url,
                auth_mode="password",
            ),
            Store(args.data_dir),
        )
        token = security.accounts.invite(args.id, args.email)
        # Fragment keeps the credential out of server/proxy request logs.
        private_write(
            args.setup_file,
            args.public_url.rstrip("/") + "/#" + urlencode({"setup": token, "email": args.email}) + "\n",
        )
        print("One-hour setup link written to the protected output file; no email was sent.")
        return
    if args.command == "revoke":
        found = [p for p in registry.principals if p.id == args.id or p.worker_id == args.id]
        if not found:
            raise ValueError("Identity not found")
        for p in found:
            p.enabled = False
    elif args.command == "add-human":
        token = secrets.token_urlsafe(48) if args.development_token_file else None
        person = Principal(
            id=args.id,
            kind="human",
            name=args.name,
            token_sha256=token_hash(token) if token else None,
            grants=[Grant.model_validate(g) for g in json.loads(args.grants.read_text())],
        )
        if any(p.id == person.id for p in registry.principals):
            raise ValueError("Identity already exists; edit its grant file deliberately")
        registry.principals.append(person)
        if token:
            private_write(args.development_token_file, token + "\n")
    else:
        from urllib.parse import urlsplit

        if not args.development and urlsplit(args.backend_url).scheme != "https":
            raise ValueError("Managed worker enrollment requires HTTPS")
        if any(p.worker_id == args.id for p in registry.principals):
            raise ValueError("Worker identity already exists; replicas need distinct identities")
        profile = json.loads(args.profile.read_text())
        grant = Grant.model_validate({**profile, "actions": ["execute"], "own_only": False})
        if "*" in (grant.organization_id, grant.department_id, grant.role_id, grant.company_id):
            raise ValueError("Worker enrollment requires an explicit environment scope")
        tokens = {kind: secrets.token_urlsafe(48) for kind in ("planner", "executor", "admission")}
        for kind, token in tokens.items():
            registry.principals.append(
                Principal(
                    id=args.id + "-" + kind,
                    name=args.id + " " + kind,
                    kind=kind,
                    worker_id=args.id,
                    token_sha256=token_hash(token),
                    grants=[
                        grant.model_copy(update={"actions": ["admit" if kind == "admission" else "execute"]})
                    ],
                )
            )
        for kind in ("planner", "executor"):
            values = {
                "EAS_BACKEND_URL": args.backend_url,
                "EAS_WORKER_TOKEN": tokens[kind],
                "EAS_WORKER_ORGANIZATION_ID": grant.organization_id,
                "EAS_WORKER_ROLE_IDS": grant.role_id,
                "EAS_SECURITY_PROFILE": "development" if args.development else "managed",
            }
            if kind == "planner":
                values["EAS_EXECUTOR_URL"] = "http://127.0.0.1:8767"
            else:
                values["EAS_ADMISSION_TOKEN"] = tokens["admission"]
            private_write(
                args.output / (kind + ".env"), "".join(k + "=" + v + "\n" for k, v in values.items())
            )
    save_registry(args.registry, registry)
    print(
        "Identity registry updated. Credentials, where requested, were written only to protected output files."
    )


if __name__ == "__main__":
    main()
