# Plan implementation audit

Audited 2026-09-12 against the current source, recent regression results, local live-run records, and the backend's published skill registry. This is a status assessment, not a new live evaluation or a claim of enterprise readiness.

## Persistent staff conversation

**Implemented for the agreed prototype scope.** The [persistent-session plan](plans/persistent-session-context.md) describes the current implementation and its limits.

- One ongoing conversation per authenticated principal and organization/department/role/company scope; natural-language requests do not require a record selector.
- Continuous chronological messages, reconnect, earlier-history loading, and execution details opened from the request's message. The cross-identity recent-activity list is removed.
- Edge-owned original history, persisted notes, model-requested context rotation, and a fallback character limit.
- Scoped `search_history` and paginated `read_history`, with current execution state reinjected independently of model notes.
- Context transitions preserve execution budgets, approvals, workflow checkpoints, and rejection/cancellation authority.

Code: [session archive](../src/edge-harness/eas_harness/session_context.py), [coordinator](../src/edge-harness/eas_harness/coordinator.py), [chat API](../src/server/eas_server/backend.py), and [frontend](../src/server/eas_server/frontend/app.js).

The latest focused session/console/activity run passed 18 tests using simulated models and staff. The rendered application was also checked at mobile, desktop, and wide desktop sizes without model calls or business decisions. Existing live OpenRouter records show the model calling `manage_context`, rotating, then using `search_history` and `read_history` to recover a synthetic phrase. Another recorded request recovered it after a worker restart. Those were synthetic messages, not real business work. Local evidence: `runtime/agent-led-evaluation/live-session-context.json` and `live-session-after-restart.json`.

Documented limits remain: text-match retrieval, fallible notes, a character rather than provider-token budget, no automatic archive retention policy, and prototype token identities. These are not missing acceptance features or promises of perfect recall.

## Agent-led execution and learning

**Complete for the accepted prototype scope.** The [learning plan](plans/agent-led-learning-plan.md) is checked against the live sequence in [cumulative learning validation](cumulative-learning-validation.md) and its [evidence artifact](evidence/cumulative-learning.json). The final suite passed **214 tests**, and both applications passed independent installation checks.

| Area | Current status |
| --- | --- |
| Separate server, edge harness, DemoBooks, and shared contracts | Implemented; clean installations confirm execution dependencies stay on the edge. |
| Agent coordinator and durable workflow tools | Implemented, including sequential child workflows within one request, approved recovery, checkpoints, cancellation and desktop ownership checks. Child completion returns control to the agent. |
| Strict business execution | Implemented; Auto requests are rejected. Learned activation does not authorize execution. |
| Versioned skills | Implemented for constrained graphs and guidance, with approved reads, scoped runtime version binding, integrity/dependency checks, pinning, suspension and rollback. |
| Isolated judgment node | Explicit invoice/PO totals, signed difference and units; exact context/prompt disclosed and bound to approval; usage recorded; invalid output bounded and abstention escalated. Live judgment runs are recorded. |
| Durable learner and runtime admission | Accepted reporting/draft and staff-reviewed observation evidence; bounded model-only maintenance, durable deduplication, immutable versions and independent automatic admission. |
| Broader feedback | Repeated failures, later incorrect assessments and missing-capability reports queue scoped reviews with related evidence. Failure reviews cannot activate a procedure. A live negative-feedback review produced a development suggestion. |
| Guidance learning and reconciliation | Guidance-only packages and instruction-only revisions; matching considers task text, actually read skills and procedure type. No-change is a valid outcome. |
| Lifecycle and supporting material | Scoped consolidation/retirement/suspension/development suggestions; bounded immutable text resources with individually approved progressive reads. Suggestions themselves have no execution or registry effect. |
| Staff-readable learning history | Instruction diffs, operation/resource changes, evidence, trusted checks, explicit guidance evaluation limits, lifecycle suggestions and activation/rollback history. Rendered on desktop and mobile. |
| Longitudinal demonstration | Completed for reporting and correction: live teaching and multiple revisions, fresh conversations, changed records, restarts, prior-layout/earlier-request regression, rollback, and unchanged historical version pins. Guidance-only learning also passed live reuse after restart. |

Code: [acceptance queue](../src/server/eas_server/store.py), [maintenance scheduling](../src/server/eas_server/learning.py), [evidence/admission](../src/edge-harness/eas_harness/maintenance.py), [skill contracts](../src/shared/eas_shared/skills.py), [workflow validation](../src/edge-harness/eas_harness/skill_library.py), and [judgment context](../src/edge-harness/eas_harness/judgment.py).

The earlier [direct lookup check](evidence/generic-observation-lookup.json) demonstrated existing approved tools. It was not a learned skill and is not counted as cumulative learning.

Automatic replay of every past experience on model changes, autonomy management, arbitrary generated Python, production identity/isolation, and generic legacy-app integration were explicitly deferred. They are not reasons to keep this milestone open. Guidance contract checks and synthetic regression results are not substitutes for live behavioral evidence.
