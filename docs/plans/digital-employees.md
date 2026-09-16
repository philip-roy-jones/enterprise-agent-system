# Digital employees and demonstration learning

Accepted direction: 2026-09-15. Implemented prototype slice; see [validation and integration limits](../digital-employee-validation.md).

This supersedes the Strict-only policy in agent-led-learning-plan.md. Auto is the only execution policy for new work. Shadowing, active, and paused are employee lifecycle states, not confidence-based approval modes. Existing requests and credentials do not silently gain autonomous authority during migration.

Each enrolled worker has a durable digital-employee identity linked to its existing separate planner, executor, and admission credentials. Administrators prepare its OS and application accounts. Staff access remains server-authorized; a supervisor explicitly activates an employee and records the readiness basis. Model output cannot change employee state, grant permissions, or claim human acceptance.

An active employee receives short-lived server grants for exact scoped operations. Human action-approval prompts are removed. Preserve contract validation, observation binding, exclusive leases, policy revocation, deadlines, immutable skill versions, receipts, and uncertain-write reconciliation. Pause stops further effects; effects already in flight retain their receipt/reconciliation requirements.

A mentor starts a bounded demonstration, describes the goal, and personally operates the employee’s own prepared computer using its VM console or remote desktop and its provisioned applications/accounts. The mentor’s separate workstation is not observed. The executor may only passively sample the employee’s own desktop; it may not focus windows, click, type, run graphs, or recover the desktop. The isolated learner can describe observations and ask questions. Mentor answers and corrections are attributed separately from model notes. Finishing a demonstration records the mentor's outcome and schedules skill distillation. Demonstrations support instructions-only skills; they are not agent-executed graph evidence or proof of generalization. Screenshots are sampled observations, not a lossless click recorder. Capture is explicit, visible, bounded, and stops when the session ends.

Readiness is a supervisor decision with recorded evidence/rationale. No automatic confidence score unlocks authority. Existing workers migrate to shadowing; existing in-progress Strict requests are cancelled without rewriting historical approvals. Production identities, privacy restrictions, and separate application permissions remain in force.

Delivery includes server lifecycle and authorization, edge observation and isolated model review, demonstration learning, frontend controls, setup/migration documentation, and tests for forbidden shadow effects, privilege escalation, revocation, exact grants, capture expiry, provenance, and autonomous execution. Group-wide package replication and device management remain separate projects; matching scope is not proof of machine configuration.

## Team communication

Private Discord team channels are the preferred first external surface. An administrator binds each channel to one employee and scope, and links Discord user IDs to existing human identities. A room shares conversation memory; every request and correction retains its real author. Channel membership does not grant application authority. The bridge checks the current channel audience against server permissions before accepting work or posting public replies. The web console remains available for supervision, onboarding, history and debugging. Its private chat remains separate from shared room memory. See [Discord setup](../discord.md).

## Future MCP Apps direction (not implemented in this delivery)

Prefer MCP Apps for integrations that support an interactive interface so mentors can demonstrate through the same application surface used by their digital employee. This preserves the teaching pattern: describe the task, operate the employee's application, answer questions, then provide the observed outcome. Desktop-only applications continue to use the employee's actual desktop.

An MCP Apps host must record attributed human UI/tool requests, validated results and relevant view state in the demonstration episode. Do not treat arbitrary app-supplied context as a trusted audit trail or permission. `ui/update-model-context` can replace a previous update and may be deferred, so it is insufficient as a lossless record. In shadowing, human-initiated operations use the mentor's authorized demonstration session; the model remains observation-only. Active agent tool calls use the existing server authority and action ledger. Apps and tools do not grant themselves permissions. An MCP App without sufficient observation evidence should be labeled as such, not silently treated as fully observable.

Discord remains the conversation channel. The application UI would open in an authenticated MCP Apps host associated with the employee's environment; do not assume Discord can render MCP Apps. No MCP client, host, or tool integration has been implemented yet.

References: [MCP Apps overview](https://modelcontextprotocol.io/extensions/apps/overview), [model-context update semantics](https://apps.extensions.modelcontextprotocol.io/api/interfaces/app.McpUiUpdateModelContextRequest.html).
