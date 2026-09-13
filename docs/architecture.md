# Architecture and trust boundaries

The accepted [agent-led plan](plans/agent-led-learning-plan.md) replaces the original graph-first and Auto-mode design.

## Software boundaries

The server owns individual identities, resource policy, authenticated conversations, requests, staff decisions, exact execution grants, evidence, maintenance scheduling and protected package distribution. It runs no agent or workflow and has no desktop credentials. The edge harness owns the Deep Agent, skill loading, graph compilation, checkpoints, operation execution, desktop adapters and bounded learner. DemoBooks is an independent synthetic Windows application; its optional API may be disabled. Campaign Desk is an independent read-only synthetic Marketing API on Ubuntu. Both live under `src/test-software/`; the optional browser ledger fixture is a separate development dependency. `src/shared/` contains contracts only.

## Durable requests and skill graphs

Staff requests carry a conversation ID and idempotent request ID. A conversation does not hold the desktop between requests. The coordinator discovers scoped skill metadata, requests approval to read the exact version, then requests approval to invoke it. A stable skill-run ID derives from the parent tool-call invocation. The child graph checkpoints its operation index independently of the agent checkpoint namespace and publishes progress to the backend.

Model-facing skill tools accept a stable skill ID. The runtime resolves a read to its scoped active version and binds later graph/resource requests to the exact approved read. Approval records still contain the full immutable version; retries reuse that binding. The model does not have to transcribe a cryptographic hash. Suspension and exact-version checks remain enforced independently.

A completed skill graph returns control to the coordinator; it does not finish the whole staff request or replace the model's answer with a fixed report template. The agent can perform another approved procedure within the same record and request budget. Further application work invalidates the previous completion marker, so final verification cannot be borrowed from an earlier partial result. A combined learned procedure retains the observed operations and verifies at its end; draft compositions still permit only one prepare/save/verify sequence.

Each child operation passes through `ExecutionLayer`; parent approval grants no child authority. A pending skill graph exclusively owns its request. On recovery it returns a structured assistance state, allowing separately approved investigation before resuming the same continuation. Recovery is bounded. A confirmed save is replayed from the ledger or independently reconciled by operation identity. An uncertain write is never repeated without an authoritative determination.

Both checkpoint stores live behind the protected edge broker. The planner serializes its own checkpoint data; privileged storage never deserializes executable checkpoint values. Reconnects use backend records; they do not depend on inspecting hidden LangGraph subgraphs. A process restart invalidates the old desktop ownership epoch and requires fresh approval of unexecuted work.

## Persistent conversation and working context

The staff console returns to one ongoing conversation per authenticated principal and work scope. New messages during active work are guidance or answers, never action approvals. Later work receives a separate internal execution record in the same conversation. Browsing older activity does not change where the main composer sends messages.

The edge stores original messages/tool exchanges, model notes and context-window transitions in `session-context.sqlite`. `manage_context` lets the model save notes and request a fresh working window; scoped `search_history` and `read_history` recover older details. A character budget forces a context transition if needed. Transitions retain the current execution state and a durable completion marker, preventing repeated resets that make no progress. Cancelled tool proposals remain archived but incomplete tool/result pairs are excluded from subsequent model input.

These are internal operations on context already held by the session, not new business reads. They require current read permission and cannot cross principal or work-scope boundaries. Model notes cannot approve actions or become organizational policy. See the [persistent-session design and Codex references](plans/persistent-session-context.md).

## Strict authority

Strict is the sole execution policy. Auto API requests fail; previously queued or active Auto work is cancelled during migration, preserving its audit. Rejection, cancellation and permission denial terminate execution. Guidance cannot change authority. The backend transactionally consumes a decision bound to the request, invocation, exact arguments, current observation and ownership epoch. Duplicate or stale decisions fail. Every direct tool and graph operation uses the same path.

The total request deadline includes staff waiting and takeover. The worker checks it on every polling path. Per-operation deadlines fence later effects without abandoning a thread that might still mutate the desktop. Each registered desktop has one exclusive lease, and handoff cannot interrupt an in-flight effect. Distinct desktops have distinct leases. Exact, short-lived signed grants are consumed once in the central ledger; service credentials cannot manufacture staff decisions.

A registered operation may contain disclosed internal navigation. Arbitrary model instructions cannot define a new operation. Runtime screenshots used to prepare approvals are evidence capture; model-requested observations require approval.

## Skill packages and learning

`src/edge-harness/skills/` contains the bundled correction skill. Installed packages export a manifest and Markdown instructions alongside the edge's SQLite registry. Content-addressed versions bind instructions, scope and graph specifications. A separate digest binds the trusted operation/runtime code and installed graph dependencies. Retrieval checks both the registry and exported files.

An accepted, verified episode enters the server's maintenance queue once. This includes observed answers with a staff-reviewed outcome, as well as reports and saved drafts. Repeated related failures, later incorrect-action assessments, and explicit capability gaps queue bounded feedback reviews with related evidence. Failure reviews can propose investigation, consolidation, suspension or retirement; they cannot admit a successful procedure or change permissions. Low usage alone is not a retirement reason.

The edge claims its own bounded maintenance work while idle. In the isolated Windows and Ubuntu deployments the learner runs under a separate non-admin, noninteractive OS account, receiving bounded JSON evidence and returning untrusted candidates. The planner uses another noninteractive account; the executor and admission runtime own privileged application access and validation. The loopback browser fixture remains a trusted integrated development mode. See the [security boundary and access matrix](security.md).

The candidate can compose the registered operations for its authorized role. Marketing admission also checks different campaign values, zero denominators, changed revisions and missing records. It cannot introduce imports, shell commands, new Python functions, scope changes or permissions. Admission independently matches successful steps to executed approvals and staff-accepted evidence, preserves prior supported steps/labels, rejects memorized record identifiers, and runs trusted synthetic cases in a credential-free process. New record amounts include positive, negative and zero discrepancies; stale comparisons and wrong current records must fail. Candidate-authored claims cannot replace these checks.

Guidance-only packages have no graph steps. They teach use of existing approved tools and can receive instruction-only revisions. Their admission checks validate contracts and provenance; they explicitly report that behavioral evaluation was not performed. Optional bounded text resources live under `references/`, `templates/`, `assets/` or `tests/`. Reading a resource requires a separate approval and the previously read exact package version. Resource text is hash checked and never executed. The staff learning view shows instruction diffs, changed steps/resources, evidence, checks and lifecycle suggestions.

An eligible package activates automatically. Activation and its processed-episode record commit together, so an acknowledgement retry does not generate another version. The server records provenance and changes but cannot execute skill code. No historical PR is automatically promoted. Suspension removes future retrieval; rollback changes the active pointer; existing runs retain the version they approved unless explicitly cancelled. Changed dependencies fail closed and require requalification.

## Scoped model judgment

The optional judgment operation uses a versioned prompt, typed comparison input and output, an explicit evidence identifier, no coordinator transcript and no tools. Input names both invoice and purchase-order totals, the signed difference, and cents/USD units. Inputs, model/settings, output and validation failures are recorded. Invalid output has a two-attempt bound within the request's model budget; explicit insufficient evidence escalates immediately. Downstream effects still require their own approval. The example checks discrepancy classification against arithmetic; it demonstrates context separation, not an advanced accounting judgment.

## Prototype limits

The deployment has a Windows Finance desktop and an Ubuntu Marketing API worker, each with isolated planner/learner accounts and distinct service credentials. Staff use individual email/password accounts with server-enforced scoped authorization. Concurrent live requests, different-record skill reuse and actual OS access probes are recorded in [validation](security-validation.md). This is bounded evidence, not full fleet orchestration or generic Linux GUI support. The learned surface covers synthetic Finance operations and Marketing metrics. Automatic arbitrary-code learning, autonomy optimization, model-switch replay campaigns, general application understanding and fleet replication remain outside the milestone. Skill text can still mislead a model; structural checks and approvals do not establish enterprise reliability.
