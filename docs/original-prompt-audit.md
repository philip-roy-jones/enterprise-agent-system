# Original prototype requirements

This audit covers the bounded demonstration in `original-prompt.txt`, including the requested Windows deployment and OpenRouter provider. It does not treat arbitrary new workflow generation, production adoption, or an unlimited number of worker VMs as requirements for the original demonstration.

**Status: the end-to-end teaching demonstration has passed; the full specification is not yet complete.** The table below records existing implementation and evidence, not unconditional completion of every sentence in each requirement.

## Requirements still partial

- **Section 8 — operation contracts:** job inputs and assistant tool arguments have schemas, but native/browser operation results are mostly unstructured dictionaries. `Operation.timeout_seconds` and `retry_limit` are disclosed metadata; the shared execution layer does not enforce them. Adapter-specific timeouts and the overall job/recovery budgets exist, but do not complete the requested per-operation contracts.
- **Sections 2 and 12 — conversation:** staff messages are saved as audit events and shown in the console, but are not included in the assistant context. Approvals and corrected tool arguments work; free-text conversation does not yet guide assistance or provide an agent question/answer cycle.
- **Section 14 — improvement analysis:** isolation, tests, PR review, exact-commit CI checks, release and rollback work. Gap analysis is a predefined amount-label recipe: it checks for a label-related recovery reason and patches known source text. It does not yet infer the required change from the recorded correction or inspect the graph to choose among useful improvements. This is narrower than the requested development process, even without adding arbitrary workflow generation.
- **Windows mouse/keyboard extension:** two release checks paused at the keyboard-focus guard. Accessibility-mode execution passed. Resolving that input bug remains follow-up work; the original prompt explicitly permits accessibility and does not require clicks-only execution.

| Requirement | Implementation and evidence |
| --- | --- |
| 1. Bounded accounting example and interruptions | Browser fixture plus independent native DemoBooks; invoice/PO comparison, correction drafts, verification, deliberately introduced UI conditions. Browser tests and separate native evidence are listed in `validation.md`. |
| 2. Central backend and worker VM/PC | Backend/frontend on the developer machine; LangGraph, Deep Agent harness, and desktop control on Windows. One desktop lease. `developer-setup.md` and `evidence/windows-edge-worker.json`. |
| 3. Cyclic role graph | `enterprise/graph.py`: validate, establish, compare, prepare, save, verify, recover, assist, resume, and complete. Unknown requests also enter supervised discovery. |
| 4–6. Strict/Auto and supervised fallback | Shared execution enforcement, exact proposals, individual tool approvals including reads, and restoration after verified recovery. `tests/test_execution.py`, `test_assistant.py`, and `test_browser.py`. |
| 7. Durable progress versus current application state | Central jobs/evidence, separate durable edge checkpoints, fresh observations at boundaries, and uncertain mutation reconciliation. Restart tests and native evidence. |
| 8. Shared execution and adapters | Both execution paths use `ExecutionLayer`; typed job/tool inputs, adapter protocol, operation metadata, scoped API/accessibility/input adapters, and verification. The native decoder supports DemoBooks; generic third-party application interpretation is not claimed. |
| 9. UI recovery | Known popup handling, bounded readiness, identity-based navigation, supervised unfamiliar/unsaved conditions, and window activation. Native focus recovery can still be expensive; documented successful and failed checks are retained. |
| 10. Exclusive control | Transactional lease, epoch fencing, in-flight action checks, staff takeover, and stale approval invalidation. Misrouted jobs are independently rejected by the receiving worker before graph/adapter initialization. |
| 11. Mutation and crash recovery | Not-attempted/uncertain/confirmed states, idempotent browser/API saves, visible job references for the API-disabled app, and refusal to repeat an uncertain Save without reconciliation. |
| 12. One staff experience | Job/conversation, proposals, corrections, modes, activity/evidence, and acceptance remain in the same console. Metrics navigation and live refresh verified in Chromium. Staff notes are recorded; this is not a general conversational agent product. |
| 13. Episodic evidence and scoped knowledge | Accepted episodes filtered by context. Separate immutable guidance documents filtered by organization, department, role, and company, with approved search and source references. `organizational-knowledge.md`, `test_knowledge.py`. |
| 14. Reviewed improvements | Manual isolated proposal generator for a recurring field-label gap; regression tests, patch/PR, commit-bound review, idle release, health checks, version pinning, and transactional rollback. Scheduling interface remains disabled. Graph topology is unchanged; old node definitions must remain until their jobs finish before any future topology migration. |
| 15. Implementation choices | Python, real LangGraph/Deep Agents, configurable OpenRouter model, explicit simulated mode, durable persistence; dependency versions recorded in `requirements.lock`. |
| 16. Validation and metrics | Baseline and isolated candidate suites, separate native/live evidence, and console metrics. A recorded zero incorrect-action count is not a proof of general safety. |
| 17. Teaching and correction demonstration | Strict/Auto, unfamiliar label, approved/corrected tools, verified return, accepted episode, and reusable improvement proposal. Isolated tests exercise a simulated developer review, deployment, a new invoice without fallback, version pinning, and rollback. |

## Reviewed release demonstration

The human project developer approved [PR #1](https://github.com/philip-roy-jones/enterprise-agent-system/pull/1), commit `cac88dea82cdd5aa05f78113012fa1d75385ff67`, after 95 isolated tests and GitHub checks passed. The prototype released version v2 while idle and retained v1 for rollback. A different invoice completed on Windows with the changed label, the application API disabled, zero fallback/model calls, and a verified saved draft. The accepted teaching episode remains pinned to v1. See [reviewed release evidence](evidence/reviewed-release.json).

The successful check used Windows accessibility actions. Two earlier mouse/keyboard checks recognized the label but paused on an unrelated focus guard before Save; both were cancelled without saving. These findings remain in the evidence. Staff acceptance of the successful test was simulated; developer release approval was human. This completes the demonstrated teaching cycle; it does not close the partial requirements listed above.

## Deliberate prototype limits

The worker has one configured organization and an explicit role allowlist. Staff authentication still uses a shared workspace token: there is no employee membership directory, per-person department ACL, production tenant isolation, or independently hardened automation sandbox. A role is not an operating-system security boundary. Multiple authorized roles may share a worker sequentially; additional real security boundaries need independently enforced credentials and isolation.

The improvement generator implements one bounded reusable change. General workflow-code generation, full recording of unmediated human demonstrations, arbitrary graph deployment, and generic vision-only control remain future work. Those should not be implied by the original teaching demonstration or by the README's statement of motivation.
