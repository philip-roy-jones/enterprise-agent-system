"""Protected context storage. Checkpoints remain opaque to the privileged process.

Only the planner deserializes LangGraph values. The broker derives the request
and scope from server authorization, never from serialized model state.
"""

import base64
import json
import sqlite3
from pathlib import Path
from langchain_core.messages import message_to_dict, messages_from_dict
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple, WRITES_IDX_MAP
from eas_harness.session_context import SessionContext


class ContextVault:
    def __init__(self, root):
        self.memory = SessionContext(root)
        self.path = Path(root) / "protected-checkpoints.sqlite"
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS checkpoints(
                    job TEXT, space TEXT, thread TEXT, ns TEXT, id TEXT, data TEXT,
                    PRIMARY KEY(job,space,thread,ns,id));
                CREATE TABLE IF NOT EXISTS writes(
                    job TEXT, space TEXT, thread TEXT, ns TEXT, id TEXT, task TEXT, idx INTEGER, data TEXT,
                    PRIMARY KEY(job,space,thread,ns,id,task,idx));
                CREATE TABLE IF NOT EXISTS context_authority(
                    scope TEXT PRIMARY KEY, revision TEXT, generation INTEGER);
                CREATE TABLE IF NOT EXISTS request_authority(
                    job TEXT PRIMARY KEY, revision TEXT);
            """)

    def authorized_job(self, job, revision):
        """A policy change ends the old continuation and starts fresh memory.

        The revision comes from the authenticated server, never planner input.
        Existing archives are retained for their original authorized policy;
        returning to a previous policy never resurrects an old working window.
        """
        scope = self.memory.scope(job)
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("BEGIN IMMEDIATE")
            pinned = db.execute("SELECT revision FROM request_authority WHERE job=?", (job["id"],)).fetchone()
            if pinned and pinned[0] != revision:
                raise PermissionError("Authorization changed; start a new request with clean context")
            db.execute("INSERT OR IGNORE INTO request_authority VALUES(?,?)", (job["id"], revision))
            row = db.execute(
                "SELECT revision,generation FROM context_authority WHERE scope=?", (scope,)
            ).fetchone()
            generation = row[1] + int(row[0] != revision) if row else 0
            db.execute(
                "INSERT OR REPLACE INTO context_authority VALUES(?,?,?)", (scope, revision, generation)
            )
        if generation:
            return {**job, "conversation_id": job["conversation_id"] + ":authority:" + str(generation)}
        return job

    def dispatch(self, job, request):
        if len(json.dumps(request)) > 4_000_000:
            raise ValueError("Context storage budget exceeded")
        method = request["method"]
        if method == "archive":
            raw = request["messages"]
            if (
                not isinstance(raw, list)
                or len(raw) > 1000
                or any(m.get("type") not in {"human", "ai", "tool", "system"} for m in raw)
            ):
                raise ValueError("Unsupported message data")
            messages = messages_from_dict(raw)
            self.memory.archive(job, messages)
            return [m.id for m in messages]
        if method == "window":
            self.memory.archive(job, [])
            messages, state = self.memory.window(
                job, request["runtime"], max_chars=min(192000, max(1000, int(request["max_chars"])))
            )
            return {"messages": [message_to_dict(m) for m in messages], "state": state}
        if method == "manage":
            return self.memory.manage(
                job, request["invocation"], request["notes"], request.get("new_context", False)
            )
        if method == "search":
            return self.memory.search(job, request["query"])
        if method == "read":
            return self.memory.read(job, request["entry_id"], request.get("offset", 0))
        if method not in {"checkpoint_get", "checkpoint_put", "checkpoint_writes"}:
            raise ValueError("Context method is not registered")
        config, space = request["config"], request["space"]
        thread, ns, checkpoint_id = (
            str(config["thread_id"]),
            str(config.get("checkpoint_ns", "")),
            config.get("checkpoint_id"),
        )
        if space not in {"agent", "workflow"} or not (
            thread == job["id"] or thread.startswith(job["id"] + ":")
        ):
            raise PermissionError("Checkpoint is outside the assigned request")
        key = (job["id"], space, thread, ns)
        with sqlite3.connect(self.path, timeout=30) as db:
            if method == "checkpoint_get":
                row = db.execute(
                    "SELECT id,data FROM checkpoints WHERE job=? AND space=? AND thread=? AND ns=?"
                    + (" AND id=?" if checkpoint_id else " ORDER BY id DESC LIMIT 1"),
                    key + ((checkpoint_id,) if checkpoint_id else ()),
                ).fetchone()
                if not row:
                    return None
                result = json.loads(row[1])
                result["writes"] = [
                    json.loads(r[0])
                    for r in db.execute(
                        "SELECT data FROM writes WHERE job=? AND space=? AND thread=? AND ns=? AND id=? ORDER BY task,idx",
                        key + (row[0],),
                    )
                ]
                return result
            if method == "checkpoint_put":
                data = request["data"]
                # Store JSON/base64 as data. Never call a checkpoint serializer here.
                db.execute(
                    "INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,?,?,?)",
                    key + (data["id"], json.dumps(data)),
                )
                return None
            for item in request["writes"]:
                query = "INSERT OR REPLACE" if item["idx"] < 0 else "INSERT OR IGNORE"
                db.execute(
                    query + " INTO writes VALUES(?,?,?,?,?,?,?,?)",
                    key
                    + (
                        checkpoint_id,
                        str(request["task_id"]),
                        item["idx"],
                        json.dumps({**item, "task": request["task_id"]}),
                    ),
                )
        return None


class RemoteContext:
    def __init__(self, layer):
        self.layer = layer

    def call(self, job, method, **values):
        return self.layer.call("context", job["id"], context={"method": method, **values})

    def archive(self, job, messages):
        ids = self.call(job, "archive", messages=[message_to_dict(m) for m in messages])
        for m, identity in zip(messages, ids):
            m.id = identity

    def window(self, job, runtime, *, max_chars=96000):
        result = self.call(job, "window", runtime=runtime, max_chars=max_chars)
        return messages_from_dict(result["messages"]), result["state"]

    def manage(self, job, invocation, notes, new_context=False):
        return self.call(job, "manage", invocation=invocation, notes=notes, new_context=new_context)

    def search(self, job, query):
        return self.call(job, "search", query=query)

    def read(self, job, entry_id, offset=0):
        return self.call(job, "read", entry_id=entry_id, offset=offset)


class RemoteCheckpointer(BaseCheckpointSaver):
    def __init__(self, layer, space):
        super().__init__()
        self.layer, self.space = layer, space

    def call(self, config, method, **values):
        c = config["configurable"]
        job_id = str(c["thread_id"]).split(":", 1)[0]
        return self.layer.call(
            "context",
            job_id,
            context={
                "method": method,
                "space": self.space,
                "config": {k: c[k] for k in ("thread_id", "checkpoint_ns", "checkpoint_id") if k in c},
                **values,
            },
        )

    def encode(self, value):
        kind, raw = self.serde.dumps_typed(value)
        return [kind, base64.b64encode(raw).decode("ascii")]

    def decode(self, value):
        return self.serde.loads_typed((value[0], base64.b64decode(value[1], validate=True)))

    def get_tuple(self, config):
        result = self.call(config, "checkpoint_get")
        if not result:
            return None
        c = {
            "thread_id": config["configurable"]["thread_id"],
            "checkpoint_ns": config["configurable"].get("checkpoint_ns", ""),
        }
        return CheckpointTuple(
            {"configurable": {**c, "checkpoint_id": result["id"]}},
            self.decode(result["checkpoint"]),
            result["metadata"],
            {"configurable": {**c, "checkpoint_id": result["parent"]}} if result["parent"] else None,
            [(w["task"], w["channel"], self.decode(w["value"])) for w in result["writes"]],
        )

    def put(self, config, checkpoint, metadata, new_versions):
        c = config["configurable"]
        self.call(
            config,
            "checkpoint_put",
            data={
                "id": checkpoint["id"],
                "parent": c.get("checkpoint_id"),
                "checkpoint": self.encode(checkpoint),
                "metadata": metadata,
            },
        )
        return {
            "configurable": {
                "thread_id": c["thread_id"],
                "checkpoint_ns": c.get("checkpoint_ns", ""),
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(self, config, writes, task_id, task_path=""):
        self.call(
            config,
            "checkpoint_writes",
            task_id=task_id,
            writes=[
                {"idx": WRITES_IDX_MAP.get(channel, i), "channel": channel, "value": self.encode(value)}
                for i, (channel, value) in enumerate(writes)
            ],
        )
