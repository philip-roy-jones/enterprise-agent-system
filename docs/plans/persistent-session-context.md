# Persistent staff conversation and managed context

Accepted extension to the [agent-led learning plan](agent-led-learning-plan.md), 2026-09-12. Staff should not need to remember which chat contains earlier work.

Status: **Implemented for the agreed prototype scope.** See the [implementation audit](../plan-implementation-audit.md) for evidence and documented limits.

## User experience

Return to one ongoing conversation with the assigned worker. Clarifications during work join its current request; a later task creates a new internal execution record in the same conversation. The console shows only the authenticated staff conversation. Each request message can open its execution details; there is no separate cross-identity recent-activity list. Reconnecting restores the conversation from the server, independently of browser storage.

The chat composer accepts natural language without a record field. An execution record can initially have no invoice. The agent asks an ordinary conversational question when the target is unclear, or proposes `select_record` for the invoice described in the request or unambiguous conversation history. Selection receives a typed, correctable staff approval and is recorded transactionally before any application observation or operation. It does not activate the desktop. Once bound, that execution cannot silently switch invoices. A later request in the same conversation can select another invoice. The structured `/api/jobs` endpoint still requires the role's explicit inputs for developer fixtures and integrations.

The prototype has one authenticated staff principal and one developer principal. Each has a separate conversation per organization, department, role and company boundary. This does not implement production individual identity management. Sharing a VM does not imply a shared conversation or combined permissions for everyone using it.

## Edge context

The edge retains the original messages and tool exchanges in a scoped SQLite archive. Its active working window persists across requests and process restarts. The agent can:

- `manage_context`: keep concise model-authored notes and request a fresh working window.
- `search_history`: find earlier exchanges in its own scoped session.
- `read_history`: retrieve a referenced exchange in bounded pages.

A context transition takes effect at a model boundary, after tool responses have been archived. A configurable character budget (`EAS_CONTEXT_MAX_CHARS`, default 96000) also forces a transition before an indefinitely growing history is sent to the model. This is a conservative character bound, not an exact provider token counter. No extra summarization model call is required; without useful notes the agent must retrieve older detail. The original archive is never replaced by a generated summary.

Each model invocation receives the current request, verified values, mutation status and workflow-run IDs independently of notes. Context transitions do not create requests, transfer the desktop, replenish execution budgets, modify checkpoints, or approve anything. The archive and notes are fallible context, not current application evidence or organizational policy. A cancelled or rejected action cannot be retried by resetting context.

Searching already-held session context and managing its notes are internal context operations, like continuing to read the active transcript. They do not need a business-action approval. Recall still requires current read permission and cannot cross the session's staff/organization/department/role/company scope. Organizational knowledge searches, skill reads, workflow calls and business operations retain their Strict approval requirements.

## Relation to Codex

Codex documents an experimental context-management mode that uses notes and searchable history instead of repeatedly compressing context into one summary. The public configuration reference describes it as experimental and off by default, with ChatGPT account restrictions. It does not establish that every context transition is model-decided. [Official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

OpenAI also documents separate Responses API compaction, including a server-side threshold and opaque compacted items. That is a different mechanism from our inspectable notes/archive implementation. We continue using the configured OpenRouter model; this is not an integration with Codex's private runtime or its ChatGPT-only feature. [Official compaction guide](https://developers.openai.com/api/docs/guides/compaction).

## Validation and limits

Regression coverage includes model-requested reset and subsequent recall through the actual Deep Agent tool loop, archive deduplication, restart persistence, hard-limit transitions, scope exclusion, untrusted notes, persistent chat reconnect, and guidance delivery without action approval. These tests use explicitly simulated models and staff.

The current search ranks text matches, without embeddings. Notes can omit or misstate details, and retrieval can miss relevant history. The working window is bounded; the durable archive currently has no automated retention/deletion policy. Existing historical chats remain audit records; they are not silently merged across identities or scope boundaries. This prototype is not proof of perfect recall or enterprise isolation.
