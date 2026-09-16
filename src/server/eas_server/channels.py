"""Trusted server channel bindings. Transport identities never supply authority."""

import hashlib
import json
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from eas_shared.identity import canonical
from eas_shared.types import Stale, TERMINAL
from eas_server.conversation import Conversation
from eas_server.roles import get_role


class ChannelBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    guild_id: str = Field(pattern=r"^\d{1,22}$")
    channel_id: str = Field(pattern=r"^\d{1,22}$")
    name: str = Field(min_length=1, max_length=100)
    employee_id: str
    organization_id: str
    role_id: str
    company_id: str
    # Discord user ID -> existing enabled human principal. No self-enrollment.
    members: dict[str, str] = Field(min_length=1)

    @property
    def conversation_id(self):
        # Changing the audience or employee starts a new scoped context.
        return "discord-" + hashlib.sha256(canonical(self.model_dump()).encode()).hexdigest()

    def values(self):
        role = get_role(self.role_id)
        return role.normalize(
            dict(
                organization_id=self.organization_id,
                department_id=role.department_id,
                role_id=self.role_id,
                company_id=self.company_id,
                employee_id=self.employee_id,
                conversation_id=self.conversation_id,
                communication={
                    "kind": "discord",
                    "channel_id": self.channel_id,
                    "guild_id": self.guild_id,
                    "name": self.name,
                },
            ),
            allow_unbound=True,
        )


class Channels:
    def __init__(self, security):
        self.security, self.store = security, security.store
        self.path = security.settings.discord_channels_file
        with self.store.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS channel_deliveries(
                    identity TEXT PRIMARY KEY, external_id TEXT NOT NULL);
            """)

    def bindings(self):
        if not self.path:
            return []
        raw = json.loads(Path(self.path).read_text())
        if not isinstance(raw, list):
            raise ValueError("Discord channel configuration must be a list")
        result = [ChannelBinding.model_validate(b) for b in raw]
        if len({b.channel_id for b in result}) != len(result):
            raise ValueError("Duplicate Discord channel binding")
        return result

    def get(self, channel_id):
        binding = next((b for b in self.bindings() if b.channel_id == str(channel_id)), None)
        if not binding:
            raise PermissionError("Channel is not enrolled")
        return binding

    def member(self, binding, discord_id):
        identity = binding.members.get(str(discord_id))
        if not identity:
            raise PermissionError("Discord user is not linked to staff")
        person = self.security.get(identity)
        if person.kind != "human":
            raise PermissionError("A channel member must be a human identity")
        values = binding.values()
        self.security.request(person, values)
        # A shared conversation needs explicit team grants, not own-only access.
        for action in ("read", "request"):
            if not any(g.matches(values) and action in g.actions and not g.own_only for g in person.grants):
                raise PermissionError("Shared channels require explicit team read/request grants")
        self.security.workforce.resolve(person, values, active=False)
        return person

    def audience(self, binding, visible_ids, *, private):
        if not private or not visible_ids:
            raise PermissionError("A dedicated private channel with known viewers is required")
        for identity in visible_ids:
            self.member(binding, identity)

    def jobs(self, binding):
        return [j for j in self.store.list_jobs() if j.get("conversation_id") == binding.conversation_id]

    def receive(self, binding, *, author_id, message_id, text):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
            raise ValueError("Send 1 to 4000 characters of text")
        person = self.member(binding, author_id)
        values = binding.values()
        request_id = "discord-" + str(message_id)
        # Guidance replay remains guidance even after the active turn ends.
        with self.store.db() as db:
            old = db.execute(
                "SELECT j.data,e.data FROM events e JOIN jobs j ON j.id=e.job_id "
                "WHERE e.kind IN ('staff_message','mentor_message') AND "
                "json_extract(e.data,'$.message_id')=? AND json_extract(j.data,'$.conversation_id')=?",
                (request_id, binding.conversation_id),
            ).fetchone()
        if old:
            job, msg = json.loads(old[0]), json.loads(old[1])
            if msg.get("actor") != person.id or msg["text"] != text:
                raise ValueError("Discord message identity reused with different content")
            return job
        employee = self.security.workforce.get(binding.employee_id)
        if employee["state"] == "shadowing":
            demos = [j for j in self.jobs(binding) if j["status"] == "shadowing"]
            if not demos:
                raise Stale("Start a demonstration in the supervisor console before teaching here")
            job = demos[0]
            if person.id != job["staff_id"] or not self.security.workforce.permits(
                person, employee, "supervise"
            ):
                raise PermissionError("Only the demonstration's mentor may teach")
            with self.store.db() as db:
                current = self.store._job(db, job["id"])
                if current["status"] != "shadowing":
                    raise Stale("Demonstration ended")
                self.store._event(
                    db,
                    job["id"],
                    "mentor_message",
                    {
                        "text": text,
                        "actor": person.id,
                        "message_id": request_id,
                    },
                )
            return job
        self.security.workforce.resolve(person, values)
        values.update(task=text, request_id=request_id, staff_name=person.name)
        try:
            job = self.store.create_job(
                values,
                self.security.settings.model_mode,
                self.security.settings.job_timeout,
                staff_id=person.id,
                ongoing=True,
            )
        except Stale:
            job = next((j for j in self.jobs(binding) if j["status"] not in TERMINAL), None)
            if not job:
                raise
            self.security.authorize(person, "control", job)
            conversation = Conversation(self.store)
            question = next(
                (
                    q
                    for q in conversation.read(job["id"], require_read=False)["questions"]
                    if q["status"] == "pending"
                ),
                None,
            )
            conversation.message(
                job["id"],
                {
                    "text": text,
                    "message_id": request_id,
                    "reply_to": question["question_id"] if question else None,
                },
                actor=person.id,
            )
        self.security.audit(person, "discord_message", f"{binding.channel_id}/{message_id}")
        return job

    def pending(self, binding):
        """Export public conversation events only; never model/debug/learning payloads."""
        pending = []
        for job in sorted(self.jobs(binding), key=lambda j: j["created_at"]):
            events = self.store.events(job["id"])
            shares = {
                e["data"]["invocation"]
                for e in events
                if e["kind"] == "action_started"
                and e["data"].get("action", {}).get("name") == "share_screenshot"
            }
            for event in events:
                kind, data = event["kind"], event["data"]
                text = ""
                artifact = None
                if kind in {"assistant_message", "assistant_question"}:
                    text = data.get("text", "")
                elif kind == "shadow_notes":
                    text = data.get("question") or ""
                elif kind == "shadow_unavailable":
                    text = data.get("message", "")
                elif kind == "action_result" and data.get("invocation") in shares:
                    attachment = data.get("result", {}).get("value", {}).get("data", {})
                    name = attachment.get("screenshot", "")
                    with self.store.db() as db:
                        owner = db.execute(
                            "SELECT job_id FROM artifact_owners WHERE id=?", (name,)
                        ).fetchone()
                    if not owner or owner[0] != job["id"] or Path(name).name != name:
                        continue
                    artifact = self.store.root / "artifacts" / name
                    if not artifact.is_file():
                        continue
                    text = attachment.get("caption") or "Desktop screenshot"
                    if attachment.get("annotations"):
                        text += "\nAnnotations: " + json.dumps(attachment["annotations"], ensure_ascii=False)
                if not text:
                    continue
                prefix = "[Simulated employee] " if job["model_mode"] == "simulated" else ""
                text = prefix + text
                for index in range(0, len(text), 1800):
                    identity = f"{binding.conversation_id}:{event['seq']}:{index}"
                    with self.store.db() as db:
                        sent = db.execute(
                            "SELECT 1 FROM channel_deliveries WHERE identity=?", (identity,)
                        ).fetchone()
                    if not sent:
                        pending.append(
                            {
                                "identity": identity,
                                "text": text[index : index + 1800],
                                "job": job,
                                "artifact": artifact if index == 0 else None,
                            }
                        )
        return pending

    def delivered(self, identity, external_id):
        with self.store.db() as db:
            db.execute("INSERT OR IGNORE INTO channel_deliveries VALUES(?,?)", (identity, str(external_id)))


def install_channels(app, security):
    from eas_server.access import current

    channels = Channels(security)
    app.state.channels = channels

    @app.get("/api/channels")
    def available():
        person = current.get()
        result = []
        for b in channels.bindings():
            ids = [k for k, v in b.members.items() if v == person.id]
            if not ids:
                continue
            try:
                channels.member(b, ids[0])
            except (PermissionError, HTTPException):
                continue
            result.append({**b.values(), "channel_id": b.channel_id, "name": b.name})
        return result
