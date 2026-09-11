# Original prototype requirements

This audit covers the bounded demonstration in `original-prompt.txt`, including the requested Windows deployment and OpenRouter provider. It does not treat arbitrary new workflow generation, production adoption, or an unlimited number of worker VMs as requirements for the original demonstration.

**Status: the end-to-end teaching demonstration has passed; the full specification is not yet complete.** The table below records existing implementation and evidence, not unconditional completion of every sentence in each requirement.

## Requirements still partial

- **Final rollout and audit:** the latest operation contracts, conversational assistance, and evidence-derived improvement analysis have local test coverage. Their combined Windows rollout and a real generated candidate still need validation before the specification can be marked complete.
- **Section 11 — confirmed failure:** uncertain saves and confirmed success are covered, but the explicit confirmed-failed mutation state still needs an authoritative application rejection path and regression coverage.
- **Section 16 — incorrect-action accounting:** the metric currently counts audit events, without a complete assessment/reporting path. A zero count must not imply that all actions were assessed. Generated proposal checks now record actual regression failures from JUnit reports.

## Recently implemented and verified

- **Section 8:** executable Pydantic input/output contracts for registered nodes, tools, and public adapter operations; cooperative per-operation deadlines propagated to browser/HTTP waits and checked before subsequent effects; durable retry allowances with fresh Strict approvals. These deadlines do not claim preemptive cancellation of an already in-flight external call.
- **Sections 2 and 12:** staff messages enter assistant context; new guidance invalidates queued proposals; approved `ask_staff` questions pause without spending further model calls and resume with durable, deduplicated answers. Messages never count as action approval. Service, real Deep Agent checkpoint, and browser integration tests cover this behavior with simulated models.
- **Section 14:** development analysis now inspects the graph and resolver source, groups selected failure traces, and joins staff decisions to executed field actions, bound observations, and verified saves. It derives a missing label and next version from that evidence and generates new-record/layout regressions. Unsupported gap families produce no invented patch. Full proposal execution remains to be validated for this revision.
- **Windows mouse/keyboard:** an interactive diagnostic proved that UI Automation briefly reported the previous focused field after `SetFocus`. A bounded exact-target wait fixed the observed race. A native job on INV-1043 then saved successfully in 16.17 seconds with zero fallback and model calls; staff acceptance was simulated. See [focus recovery evidence](evidence/windows-focus-recovery.json).
- The full local suite passed **124 tests** before the final documentation/teaching-fixture refinements. Native controller publication also passed.

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
| 12. One staff experience | Job/conversation, proposals, corrections, modes, activity/evidence, and acceptance remain in the same console. Metrics navigation and live refresh verified in Chromium. Staff guidance and approved questions now participate in the same durable assistance conversation. |
| 13. Episodic evidence and scoped knowledge | Accepted episodes filtered by context. Separate immutable guidance documents filtered by organization, department, role, and company, with approved search and source references. `organizational-knowledge.md`, `test_knowledge.py`. |
| 14. Reviewed improvements | Manual evidence-derived isolated proposal generator for a recurring field-label gap; regression tests, patch/PR, commit-bound review, idle release, health checks, version pinning, and transactional rollback. Scheduling interface remains disabled. Graph topology is unchanged; old node definitions must remain until their jobs finish before any future topology migration. |
| 15. Implementation choices | Python, real LangGraph/Deep Agents, configurable OpenRouter model, explicit simulated mode, durable persistence; dependency versions recorded in `requirements.lock`. |
| 16. Validation and metrics | Baseline and isolated candidate suites, separate native/live evidence, and console metrics. A recorded zero incorrect-action count is not a proof of general safety. |
| 17. Teaching and correction demonstration | Strict/Auto, unfamiliar label, approved/corrected tools, verified return, accepted episode, and reusable improvement proposal. Isolated tests exercise a simulated developer review, deployment, a new invoice without fallback, version pinning, and rollback. |

## Reviewed release demonstration

The human project developer approved [PR #1](https://github.com/philip-roy-jones/enterprise-agent-system/pull/1), commit `cac88dea82cdd5aa05f78113012fa1d75385ff67`, after 95 isolated tests and GitHub checks passed. The prototype released version v2 while idle and retained v1 for rollback. A different invoice completed on Windows with the changed label, the application API disabled, zero fallback/model calls, and a verified saved draft. The accepted teaching episode remains pinned to v1. See [reviewed release evidence](evidence/reviewed-release.json).

The successful check used Windows accessibility actions. Two earlier mouse/keyboard checks recognized the label but paused on an unrelated focus guard before Save; both were cancelled without saving. These findings remain in the evidence. Staff acceptance of the successful test was simulated; developer release approval was human. This completes the demonstrated teaching cycle; it does not close the partial requirements listed above.

## Deliberate prototype limits

The worker has one configured organization and an explicit role allowlist. Staff authentication still uses a shared workspace token: there is no employee membership directory, per-person department ACL, production tenant isolation, or independently hardened automation sandbox. A role is not an operating-system security boundary. Multiple authorized roles may share a worker sequentially; additional real security boundaries need independently enforced credentials and isolation.

The improvement generator implements one bounded reusable change. General workflow-code generation, full recording of unmediated human demonstrations, arbitrary graph deployment, and generic vision-only control remain future work. Those should not be implied by the original teaching demonstration or by the README's statement of motivation.
