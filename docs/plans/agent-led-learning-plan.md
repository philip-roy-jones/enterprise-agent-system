# Enterprise Agent System: agent-led execution and cumulative learning

Status: **Complete for the accepted prototype scope.** 2026-09-12.

The [implementation audit](../plan-implementation-audit.md) maps the delivered functionality. The [cumulative learning validation](../cumulative-learning-validation.md) and [recorded evidence](../evidence/cumulative-learning.json) cover both task families, guidance-only learning, regressions, failures, restart, rollback and version pinning. Completion is not a claim of enterprise readiness or failure-free model behavior.

## Outcome

Staff describe work in a conversation with a Deep Agent. The agent uses versioned skills, durable LangGraph workflows, and reusable operations to carry it out. Staff retain stateful approval, correction, rejection, cancellation, and desktop takeover. Successful teaching accumulates into validated capabilities that improve later runs.

All business execution remains under Strict approval. Learning improves the available procedures and their correctness; it does not earn permission to execute without approval. Designing how autonomy is granted, maintained, reduced, or revoked is outside this milestone.

The primary milestone is demonstrating cumulative learning across fresh sessions and changed records. Moving the chat box or rearranging graph calls alone does not satisfy this plan.

This changes the original prompt's graph-first/Deep-Agent-fallback ordering and its mandatory developer-review gate for learned improvements. The revised learning policy permits automatic skill activation after runtime-owned checks, while retaining human approval for business execution. Keep [the original prompt](original-prompt.txt) as historical requirements and document the new ordering explicitly. Enterprise Agent System remains a prototype, with Finance as its first example and no claim of production readiness.

## 1. Architecture and ownership

Retain three independently installed applications and the shared contract library:

| Component | Responsibility after the change |
| --- | --- |
| `src/server/` | Conversation UI, authenticated dispatch, approval records, progress, evidence, skill metadata, review and release records. No agent or workflow execution. |
| `src/edge-harness/` | Conversational Deep Agent, skill retrieval, workflow runtime, isolated LLM nodes, shared operation execution, desktop adapters, and bounded learning maintenance. |
| `src/test-software/demobooks/` | Independent synthetic Windows accounting application. |
| `src/shared/` | Versioned API/data contracts. No execution, persistence, credentials, or environment loading. |

The developer machine hosts the server; the Windows VM/PC hosts the harness and DemoBooks. Use the existing single Windows VM for development. Do not require one VM per staff member or additional department VMs for this milestone. Application credentials and operating-system isolation remain separate from staff approval policy. Deployment addresses stay configurable.

The Deep Agent selects and parameterizes capabilities. Installed graphs control the repeatable sequence. Shared typed functions implement reusable operations across graphs. Simple calculations and lookups do not need their own graphs.

Preserve the existing execution layer, action ledger, observation binding, deadline checks, exclusive desktop lease, and uncertain-write reconciliation. Adapt their callers rather than rebuilding those protections.

## 2. Conversation and durable workflow tools

The default frontend becomes a conversation with visible workflow progress and approval cards. One ongoing staff conversation contains multiple work requests over time; staff need not manage separate chats. The accepted [persistent-session extension](persistent-session-context.md) adds edge-owned notes, searchable original history, and model-requested working-context transitions. A running request has its own execution budget; an idle conversation does not reserve the desktop indefinitely.

An installed workflow is exposed as a typed tool with a registered description and input schema. The runtime validates permissions and inputs independently of the model. Skill text cannot register arbitrary executable code or grant authority.

Each invocation records the conversation, request, tool-call ID, workflow-run ID, parent invocation, workflow/skill version, and checkpoint location. Resuming the same call must resume the existing run rather than create another job.

Use explicit persisted states: `queued`, `running`, `awaiting_approval`, `awaiting_staff`, `needs_assistance`, and terminal outcomes. UI reconnects reconstruct these from backend records. Checkpoint execution remains on the edge; publish enough progress through the API that the frontend does not depend on discovering graphs hidden inside agent tools.

Only one execution owner may control the desktop. While a workflow is pending, the coordinator cannot issue competing desktop actions. Chat messages may provide guidance, request status, cancel, or request takeover; they do not implicitly resume execution.

A workflow that encounters an unfamiliar condition returns a structured assistance request and suspends its continuation. The coordinator may investigate through approved tools within the same scope. Resume requires independent verification of the graph's preconditions. Bound assistance attempts and prevent recursive workflow/agent calls from multiplying jobs or bypassing rejection.

## 3. Stateful approval policy

Strict is the only execution policy. Remove Auto mode and the ability to switch into it; do not replace it with confidence thresholds or implicit exceptions for familiar, inexpensive, or previously successful operations.

| Boundary | Required decision |
| --- | --- |
| Deep Agent requests skill content or organizational knowledge | Individual approval of the scoped read |
| Deep Agent requests a workflow invocation | Staff approve its exact scope and inputs |
| Executable operation inside an installed graph | Individual approval |
| Deep Agent directly calls a read, navigation, or mutation tool | Individual approval |
| Standalone LLM judgment node inside a graph | Approve invocation and disclosed inputs |
| Activating a learned skill version | Automatic admission checks; no mandatory human PR review |

Ordinary conversation and internal routing do not require a permission prompt. Runtime evidence capture needed to prepare an approval remains distinct from a model-requested read operation. Workflow invocation approval is not blanket approval of its internal operations. Group the parent request and child decisions in the UI so staff can understand both.

Approval applies to a meaningful registered operation, including its disclosed internal steps, rather than every implementation-level function or click. Unexpected effects, changed arguments, or changed evidence require a fresh decision. A graph, skill, or helper cannot package arbitrary work into a broad approval to evade the internal operation gates. Scope-filtered catalog metadata may support routing; fetching skill instructions is a separate approved read.

Remove the mode selector and Auto defaults from the frontend, server, harness, API contracts, configuration, and active documentation. Requests to select Auto must fail explicitly. Retain historical mode values in audit records, but stop or drain existing Auto runs before rollout; they must not silently resume with unapproved actions. Resuming interrupted work requires the new approval policy while retaining its pinned procedure version and mutation history. Migrate or retire mode-switch tests and replace them with coverage proving every executable path requires approval.

Bind decisions to the exact run, invocation, arguments, target record, relevant evidence revision, ownership epoch, and pinned version. Persist original proposals, corrections, decisions, executed arguments, and outcomes separately. Corrected arguments must pass the same schema and scope checks as original arguments.

Before resuming, recheck job status, deadline, permissions, desktop ownership, and application state. Changed evidence invalidates the decision. Duplicate decisions cannot execute twice. Keep the documented total request deadline, including staff waiting, and enforce it during every paused path.

Rejection, permission denial, and cancellation terminate the affected execution path. The model cannot retry it through a different graph, API, or click tool. A fresh staff request may establish new authority explicitly; the agent cannot create that authority itself.

Checkpoint replay must not repeat a confirmed write. Preserve the four mutation outcomes and reconcile uncertain writes using the original business operation identity.

## 4. Separate LLM judgment nodes

Prefer a dedicated model call for narrow judgments inside a graph, rather than calling back into the coordinating Deep Agent's conversation.

- Define a versioned prompt and typed input/output schema per node.
- Supply explicit task inputs and selected, scoped evidence. Do not inherit the coordinator's transcript or general tools.
- Record model identifier/settings, prompt revision, actual input context, output, validation failures, usage, and evidence references. Apply existing credential redaction and access controls to these records.
- Permit bounded retries and explicit abstention or escalation when evidence is insufficient.
- Validate the output before routing or acting. Cite evidence identifiers where the judgment depends on documents or observed facts.
- Downstream effects still pass through the common execution and approval layer.

The same model/provider can serve both roles; a separate context does not require a separate model subscription or VM. This improves inspectability, not determinism. Replay uses recorded outputs to reproduce execution behavior; a fresh model evaluation is a separate, potentially different run. Prompt/skill/version changes cannot rewrite an in-flight node's context silently.

## 5. Automatically maintained skill packages

Use portable file packages inspired by Hermes, with database records for governance.

The agreed source location is `src/edge-harness/skills/` in this repository. The implementation now uses a bundled declarative correction package and an edge-local version registry. Keep the harness runtime, enforcement, adapters, and reusable operation library under `src/edge-harness/`. Keep skill packages colocated with the harness in this repository, with manifests identifying compatible harness capabilities. No additional running service is introduced.

This is a source/release boundary, not a runtime separation. Released skills are installed on and loaded by the same edge harness that runs the Deep Agent, graphs, and tools. The harness includes the agent loop, context and skill loading, checkpoint execution, and tool dispatch as well as control and monitoring. Do not add a remote skills execution service or require a separate repository for this milestone.

A proposed package contains:

| Content | Purpose |
| --- | --- |
| `SKILL.md` | Applicability, prerequisites, procedure guidance, pitfalls, workflow selection, and verification expectations |
| Manifest | Stable skill ID, version, scope, registered workflow entry points, dependency versions, file hashes, and provenance |
| Workflow specifications | Optional validated compositions compiled into checkpointed LangGraph workflows |
| Reusable operations | References to registered shared functions; new implementations remain harness development in the first slice |
| `references/`, `templates/`, `assets/` | Supporting material loaded as needed |
| Tests and evaluation cases | Behavioral checks and evidence for promotion |

Executable content must stay within the runtime-enforced execution surface; automatic activation cannot rely on a generated package voluntarily honoring approval wrappers. Do not add a general shell tool to the business agent merely because a package contains scripts. Skill loading must not execute embedded shell snippets.

For the first automatic executable skills, use constrained graph specifications composed from registered operations, validated and compiled to LangGraph by trusted harness code. Markdown can guide the Deep Agent; the specification defines executable steps. Do not import arbitrary learner-generated Python into the trusted worker. New operation implementations remain ordinary harness development. Automatically executing newly generated Python/functions would require a demonstrated isolation boundary that denies direct desktop, application, credential, and authority-store access and brokers effects through the approval service; a Python wrapper or separate process alone is insufficient. That broader code-execution capability is deferred from this first slice.

The server stores metadata, immutable version references, admission status, scope, and evidence links. The edge installs verified released packages and exposes only authorized capabilities. Keep unpublished candidates out of the active skill catalog.

Retrieve concise skill metadata first, then relevant content. Enforce organizational, department, role, and application scope before retrieval. Start with transparent metadata/text matching; add more complex retrieval only if evaluation shows a need.

Pin the package and its executable dependencies per run. Markdown is behavior-affecting content: version it, check applicability, and retain rollback even though updates do not require human review. A published package can be superseded or rolled back; active runs retain their pinned version or are explicitly stopped. Never silently migrate active checkpoints to changed graph topology.

## 6. Learning that accumulates

Implement a durable learning queue driven by completed work and feedback. Staff should not need a separate “create workflow” request. Capture failed attempts and rejected proposals as evidence, but do not treat them as successful procedures.

The maintenance pass runs in a separate bounded context within the edge-harness software, with access to scoped evidence and a candidate workspace. It has no business-application credentials, desktop control, or release/deployment credentials. Code evaluation uses an isolated test environment and synthetic fixtures. The central server schedules/tracks work without running the learner itself.

Automatic draft generation is an explicitly configured maintenance capability, not autonomous business execution. It cannot operate the application or make candidates available to business runs. An independent runtime admission step validates and activates eligible candidates automatically; a better evaluation score never removes an execution approval requirement.

The learning cycle is:

1. **Collect:** preserve observations, selected skills/versions, actions, corrections, failures, verification, and staff outcome acceptance.
2. **Distill:** derive reusable steps or rules; distinguish application facts, staff preferences, and organizational policy. One staff preference cannot become company policy automatically.
3. **Reconcile:** find existing relevant skills. Propose an update, a new package, or no change. Preserve contradictory evidence and avoid one new skill per conversation.
4. **Construct:** draft natural-language guidance and, where useful, workflow/function changes using approved capabilities. Missing capabilities become explicit development requests, not invented APIs or permissions.
5. **Evaluate:** test changed records, starting states, failure paths, and prior accepted behaviors. Validate candidate code in isolation without live credentials. Preserve which evidence produced each proposed change.
6. **Admit:** apply runtime-owned checks to the exact candidate version. Validate scope, capabilities, compatibility, content hashes, and test results. Candidate-authored tests supplement trusted checks; they cannot replace them. Show staff what changed and why, without requiring a separate code-review person or PR approval.
7. **Activate:** the runtime installs an admitted immutable version for future runs automatically. The learner cannot change admission rules or declare its own checks passed. Activation is not permission to perform business actions; all such actions remain Strict. Preserve a visible change history, suspension, and rollback.
8. **Reuse and measure:** later fresh sessions retrieve the released version and record outcomes against it.

Give each review bounded input, model-call, elapsed-time, and candidate limits. Deduplicate queue entries and persist retry state so restarts do not repeatedly generate the same proposal. Trigger useful reviews from accepted teaching/corrections and repeated failures; batch related evidence instead of reviewing every chat message.

Track usage, corrections, verified outcomes, and applicability. Propose consolidation or retirement of stale skills, preserving history and rollback. Low usage alone does not prove a procedure is wrong. “No justified change” is a valid review outcome.

## 7. Implementation sequence and exit criteria

| Phase | Work | Exit criterion |
| --- | --- | --- |
| 1. Strict execution and durable workflow tools | Remove Auto mode across interfaces and enforcement, migrate existing runs safely, add conversation/run/invocation contracts, and adapt the existing Finance graph to a resumable tool. Keep the current execution path available under Strict during migration. | Auto requests fail; every executable path requires approval. A tool invocation pauses internally, survives restart, resumes once, and rejects stale/duplicate decisions without duplicate writes. |
| 2. Agent-led console | Make the edge Deep Agent the chat coordinator; connect scope selection, workflow calls, status, approval cards, and takeover. | A staff message starts the known correction workflow; an unfamiliar request stays supervised; neither can bypass a rejection. |
| 3. Skill packages and judgment nodes | Add versioned discovery/loading and one narrowly scoped LLM-node example. | A run records its skill version and exact judgment context; the node receives no coordinator transcript or unapproved tools. |
| 4. Cumulative learner | Add the durable evidence queue, bounded maintenance pass, candidate construction, and staff-readable learning summary. | Normal teaching produces an evidence-derived candidate beyond the existing hardcoded field-label transformation. |
| 5. Automatic admission and activation | Replace mandatory learned-package PR review with runtime-owned checks, immutable versions, automatic installation, and rollback. | A passing candidate activates without a reviewer; rejected, tampered, or out-of-capability candidates cannot execute. Every business operation still pauses for staff approval. |
| 6. Longitudinal demonstration | Run the teaching/reuse/correction/regression sequence below; update README, architecture, setup, and evidence. | Results demonstrate accumulation across sessions with explicit limitations and simulation labels. |

Record learner-generated versions and evidence without requiring a PR for each update. Existing historical PRs remain historical review artifacts; do not silently deploy them under the new policy. Update the project instruction requiring developer review of every learned improvement when implementing this explicitly revised policy. Ordinary harness runtime changes remain separate from automatically learned package updates.

## 8. Acceptance demonstration

Use the same Windows VM and synthetic application. Retain browser fixtures for controlled fault injection. Start with two bounded task families within supported capabilities: read-only discrepancy reporting and verified correction-draft preparation. Reuse existing operations; do not expand financial authority to make the demonstration pass.

For each family:

1. Record an unassisted baseline or explicitly mark the capability as unavailable.
2. Complete a teaching run with staff corrections and independently verified results.
3. Produce, test, automatically admit, and activate the derived package change.
4. Restart the harness and use a new conversation and unseen record values. Confirm the released learning is retrieved and applied.
5. Introduce a meaningful variation that requires a second correction and candidate revision.
6. After automatic admission and activation, test the new variation and earlier cases. Demonstrate rollback and version pinning.

At least one family must gain a reusable procedure that was absent from the seeded skill catalog. Prewritten reusable operations are allowed; a canned generated procedure or copied teaching-record values do not count as learning. Keep teaching cases separate from evaluation cases, and include examples where the skill must decline to apply.

Record verified success, assessed incorrect actions, repeated mistakes, staff corrections, approval count, recovery count, model calls/tokens, elapsed execution time, and waiting time. Compare all runs under the same Strict policy and distinguish cold-start from learned versions. Learning may reduce failed attempts and unnecessary operations, but cannot reduce required approval coverage, silently broaden an operation, or unlock autonomous execution. Success means better procedures and less repeated teaching, not fewer approval gates.

Required regression coverage includes rejected Auto requests, migration of previously Auto runs, attempts to bypass internal approvals through skill/graph/helper nesting, wrong role/record routing, stale evidence, duplicate resume, staff rejection/cancellation, takeover, paused deadlines, uncertain Save, process restart, learner restart/deduplication, retrieval scope, unpublished package access, prompt injection in evidence, changed dependencies after admission, and rollback.

Use deterministic model/staff fixtures for repeatable enforcement tests and actual OpenRouter runs for learning/reuse evaluation. Label every run's model and staff provenance separately. A handful of successful demonstrations is evidence of the prototype mechanism, not enterprise reliability or guaranteed continual improvement.

### Model changes and evaluation cost

Do not build automatic replay of historical experiences or a model-switch qualification system for this milestone. Experience records are evidence, not automatically executable tests. Keep ordinary deterministic regression tests for code changes, focused tests for each learned capability, and the bounded live teaching/reuse demonstration. A model change is recorded; it does not automatically schedule a replay campaign over all past work.

Associate each result with its model/settings, prompt, skill, graph, application/policy revisions, and test-case version. Historical successful outcomes remain evidence of those combinations, not proof of the new combination. Recorded-output replay validates orchestration but cannot substitute for evaluating the new model.

When an evaluation is explicitly run, check that its cases and expected outcomes remain applicable. Preserve changed expectations and reasons rather than hiding failures as stale cases. Record what ran and what did not. If the evaluation budget is exhausted, preserve partial results and report incomplete coverage; do not call a partial run a full pass.

With sufficient compute, running all applicable evaluations remains a useful option. Selective execution is a cost optimization, but neither that optimizer nor a full historical replay system is needed to demonstrate cumulative learning. Keep Strict approval requirements unchanged regardless of evaluation coverage or score.

## 9. Scope and proposed decisions for review

This plan proposes:

- Agent-led conversation with deterministic workflows preferred for supported work.
- Strict approval of workflow calls and every executable operation inside them, with Auto mode removed.
- Separate, limited-context LLM nodes for judgment within workflows.
- File-based skill packages with backend governance records and immutable releases.
- Automatic skill creation, validation, and activation from normal work, without a mandatory human PR review; Strict business execution remains separate.
- A learning demonstration that extends beyond field labels and tests retention of prior behavior.

Defer autonomy management (earning, maintaining, reducing, and revoking permission to run without approval), confidence/risk-based automatic execution, real QuickBooks integration, general autonomous workflow generation for arbitrary apps, unmediated recording of everything staff do, model fine-tuning, cross-company learning, production identity/isolation hardening, automatic execution of arbitrary generated Python, and additional VM infrastructure. Candidate generation is bounded to installed capabilities; broader capabilities require explicit development and review.

The user approved implementation on 2026-09-12. Completion requires the exit criteria and evidence above; implementation progress alone is not a completed validation claim.

## Source references

Hermes was inspected at commit `d62716c7043e57ef7a29e81a02ddbc19334e29df`. Borrow its procedural-memory and maintenance mechanisms; do not infer enterprise readiness or measured improvement from feature availability.

- [Hermes skill loading](https://github.com/NousResearch/hermes-agent/blob/d62716c7043e57ef7a29e81a02ddbc19334e29df/tools/skills_tool.py): metadata discovery, file packages, and progressive loading.
- [Hermes learning triggers](https://github.com/NousResearch/hermes-agent/blob/d62716c7043e57ef7a29e81a02ddbc19334e29df/agent/turn_finalizer.py#L594): background review following completed turns.
- [Hermes review implementation](https://github.com/NousResearch/hermes-agent/blob/d62716c7043e57ef7a29e81a02ddbc19334e29df/agent/background_review.py): lesson extraction, existing-skill updates, and restricted maintenance tools. Our plan deliberately allows no-change outcomes.
- [Hermes curator](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator): lifecycle maintenance and recoverable history.
- [LangGraph subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs): persistence, nested tool interrupts, and state-inspection limitations.
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts): resume semantics and repeated execution before interrupts.
- [Deep Agents human-in-the-loop](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop): tool approvals with durable state.

Verify the installed library versions and their actual APIs during implementation; documentation describes capabilities, not proof that our integration already supports them.
