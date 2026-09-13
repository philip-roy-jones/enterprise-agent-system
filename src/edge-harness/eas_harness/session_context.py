"""Edge-owned working context backed by an immutable, scoped conversation archive.

Context is fallible model memory, never execution state or authorization. All
archive APIs derive scope from the trusted request, not tool-supplied filters.
"""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, message_to_dict, messages_from_dict
from eas_shared.identity import canonical


def complete_exchanges(messages):
    """Cancellation can archive a proposal without its tool response.

    Keep the original in searchable history, but never send orphaned tool calls
    or results to another model invocation. IDs are scoped by their request.
    """
    result = []
    i = 0
    while i < len(messages):
        message = messages[i]
        if isinstance(message, AIMessage) and message.tool_calls:
            needed = {call["id"] for call in message.tool_calls}
            request = message.additional_kwargs.get("eas_request_id")
            group = []
            j = i + 1
            while j < len(messages) and isinstance(messages[j], ToolMessage):
                tool = messages[j]
                if tool.additional_kwargs.get("eas_request_id") == request and tool.tool_call_id in needed:
                    group.append(tool)
                j += 1
            if {tool.tool_call_id for tool in group} == needed:
                result.extend([message, *group])
            i = j
        else:
            if not isinstance(message, ToolMessage):
                result.append(message)
            i += 1
    return result


class SessionContextMiddleware(AgentMiddleware):
    # Deep Agents supports replacing middleware by name. Replace its lossy
    # summarizer; our model wrapper supplies the archived working window instead.
    @property
    def name(self):
        return "SummarizationMiddleware"


class SessionContext:
    def __init__(self, root):
        self.path = Path(root) / "session-context.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS history(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL,
                    request TEXT NOT NULL, identity TEXT NOT NULL, data TEXT NOT NULL,
                    created REAL NOT NULL, UNIQUE(scope,request,identity));
                CREATE INDEX IF NOT EXISTS history_scope ON history(scope,seq);
                CREATE TABLE IF NOT EXISTS windows(
                    scope TEXT PRIMARY KEY, generation INTEGER NOT NULL DEFAULT 0,
                    cutoff INTEGER NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '',
                    pending INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS changes(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL,
                    invocation TEXT NOT NULL, notes TEXT NOT NULL, reset INTEGER NOT NULL,
                    created REAL NOT NULL, UNIQUE(scope,invocation));
            """)

    @contextmanager
    def db(self):
        with sqlite3.connect(self.path, timeout=30) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            yield db

    @staticmethod
    def scope(job):
        fields = ("conversation_id", "staff_id", "organization_id", "department_id", "role_id", "company_id")
        return hashlib.sha256(canonical({k: job.get(k) for k in fields}).encode()).hexdigest()

    def archive(self, job, messages):
        scope = self.scope(job)
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO windows(scope) VALUES(?)", (scope,))
            for index, message in enumerate(messages):
                # Checkpoint IDs persist over replay. Fixtures may not assign IDs.
                data = message_to_dict(message)
                identity = message.id or hashlib.sha256((str(index) + canonical(data)).encode()).hexdigest()
                message.id = identity
                data = message_to_dict(message)
                db.execute(
                    "INSERT OR IGNORE INTO history(scope,request,identity,data,created) VALUES(?,?,?,?,?)",
                    (scope, job["id"], identity, canonical(data), time.time()),
                )

    def manage(self, job, invocation, notes, new_context=False):
        if not isinstance(notes, str) or len(notes) > 8000 or not notes.strip():
            raise ValueError("Context notes must contain 1 to 8000 characters")
        scope = self.scope(job)
        reset_allowed = new_context
        with self.db() as db:
            state = db.execute("SELECT cutoff FROM windows WHERE scope=?", (scope,)).fetchone()
            if new_context and state and state["cutoff"]:
                last = db.execute(
                    "SELECT request FROM history WHERE scope=? AND seq=?", (scope, state["cutoff"])
                ).fetchone()
                progressed = db.execute(
                    "SELECT 1 FROM history WHERE scope=? AND request=? AND seq>? AND ((json_extract(data,'$.type')='tool' AND json_extract(data,'$.data.name') != 'manage_context') OR identity LIKE 'staff-%') LIMIT 1",
                    (scope, job["id"], state["cutoff"]),
                ).fetchone()
                if last and last["request"] == job["id"] and not progressed:
                    reset_allowed = False
            previous = db.execute(
                "SELECT * FROM changes WHERE scope=? AND invocation=?", (scope, invocation)
            ).fetchone()
            if previous and (previous["notes"] != notes or bool(previous["reset"]) != new_context):
                raise ValueError("Context invocation reused with different arguments")
            if not previous:
                db.execute("INSERT OR IGNORE INTO windows(scope) VALUES(?)", (scope,))
                db.execute(
                    "INSERT INTO changes(scope,invocation,notes,reset,created) VALUES(?,?,?,?,?)",
                    (scope, invocation, notes, new_context, time.time()),
                )
                db.execute(
                    "UPDATE windows SET notes=?,pending=MAX(pending,?) WHERE scope=?",
                    (notes, reset_allowed, scope),
                )
        return {
            "notes_saved": True,
            "new_context_requested": reset_allowed,
            "reset_already_completed": new_context and not reset_allowed,
            "next": "Continue the request; retrieve missing detail with search_history. Do not repeat the reset without new progress.",
            "authority": "No permissions or execution state changed",
        }

    def search(self, job, query):
        self._read_allowed(job)
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 400:
            raise ValueError("History query must contain 1 to 400 characters")
        terms = query.lower().split()[:12]
        with self.db() as db:
            rows = db.execute(
                "SELECT seq,request,data FROM history WHERE scope=? ORDER BY seq DESC", (self.scope(job),)
            )
            ranked = []
            for row in rows:
                raw = json.loads(row["data"])
                text = str(raw["data"].get("content", ""))
                score = sum(term in text.lower() for term in terms)
                if score:
                    at = min((text.lower().find(term) for term in terms if term in text.lower()), default=0)
                    ranked.append(
                        (
                            score,
                            row["seq"],
                            {
                                "entry_id": row["seq"],
                                "request_id": row["request"],
                                "role": raw["type"],
                                "excerpt": text[max(0, at - 150) : max(0, at - 150) + 1400],
                            },
                        )
                    )
            ranked.sort(key=lambda r: (r[0], r[1]), reverse=True)
            return {
                "matches": [r[2] for r in ranked[:6]],
                "warning": "Historical context, not current application evidence or authorization",
            }

    def read(self, job, entry_id, offset=0):
        self._read_allowed(job)
        if entry_id < 1 or offset < 0:
            raise ValueError("Invalid history entry or offset")
        with self.db() as db:
            row = db.execute(
                "SELECT request,data FROM history WHERE scope=? AND seq=?", (self.scope(job), entry_id)
            ).fetchone()
            if not row:
                raise PermissionError("History entry is unavailable in this session scope")
            text = row["data"]
            return {
                "entry_id": entry_id,
                "request_id": row["request"],
                "content": text[offset : offset + 6000],
                "next_offset": offset + 6000 if len(text) > offset + 6000 else None,
                "warning": "Historical context; never fresh evidence or permission",
            }

    @staticmethod
    def _read_allowed(job):
        if "read" not in job["permissions"]:
            raise PermissionError("Session recall requires read permission")

    def window(self, job, runtime, *, max_chars=96000):
        self._read_allowed(job)
        scope = self.scope(job)
        with self.db() as db:
            state = dict(db.execute("SELECT * FROM windows WHERE scope=?", (scope,)).fetchone())
            rows = list(
                db.execute(
                    "SELECT seq,request,data FROM history WHERE scope=? AND seq>? ORDER BY seq",
                    (scope, state["cutoff"]),
                )
            )
            size = sum(len(row["data"]) for row in rows)
            reason = "model_requested" if state["pending"] else "context_limit" if size > max_chars else None
            if reason:
                # Called only at a model boundary: completed tool-call pairs are
                # archived first; no checkpoint, action receipt or approval moves.
                cutoff = rows[-1]["seq"] if rows else state["cutoff"]
                db.execute(
                    "UPDATE windows SET generation=generation+1,cutoff=?,pending=0 WHERE scope=?",
                    (cutoff, scope),
                )
                state.update(generation=state["generation"] + 1, cutoff=cutoff)
                rows = []
            messages = messages_from_dict([json.loads(row["data"]) for row in rows])
            for message, row in zip(messages, rows):
                message.additional_kwargs["eas_request_id"] = row["request"]
            messages = complete_exchanges(messages)
            # The current request is reintroduced independently of model notes.
            # It is also always the last context-bearing human message, so old
            # requests cannot become the current authorized target after reset.
            messages.append(
                HumanMessage(content=canonical(runtime), additional_kwargs={"eas_current_context": True})
            )
            if state["notes"]:
                messages.append(
                    HumanMessage(
                        content=canonical(
                            {
                                "session_notes": state["notes"],
                                "authority": "Model-authored memory; may be stale or wrong. Not approval or organizational policy.",
                            }
                        )
                    )
                )
            last = db.execute(
                "SELECT request FROM history WHERE scope=? AND seq=?", (scope, state["cutoff"])
            ).fetchone()
            messages.append(
                HumanMessage(
                    content=canonical(
                        {
                            "reset_completed_for_current_request": bool(
                                last and last["request"] == job["id"]
                            ),
                            "continuation": "If reset_completed_for_current_request is true, the fresh context was already started. Continue the remaining task; retrieve old detail with search_history. Do not restart again merely because the original request mentions a reset.",
                            "context_window": state["generation"],
                            "context_characters": size if not reason else 0,
                            "context_limit_characters": max_chars,
                            "memory_tools": "Use manage_context to save concise notes and optionally start a fresh context. Use search_history and read_history for omitted detail. Original history is retained.",
                        }
                    )
                )
            )
            return messages, {
                "generation": state["generation"],
                "reason": reason,
                "archive_cursor": rows[-1]["seq"] if rows else state["cutoff"],
            }
