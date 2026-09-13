# Validation record

Regression tests use an explicitly **simulated model**. Separate native Windows demonstrations use **GPT 5.6 Luna through OpenRouter**. Scripted staff decisions are labeled simulated in both cases. Current learned packages activate after runtime-owned validation; historical developer-reviewed releases remain labeled separately. These are bounded demonstrations, not a general assessment of model reliability.

## Completed agent-led learning milestone, 2026-09-12

The final suite passed **214 tests**. Independent server and edge installations passed, and the native learning UI passed desktop/mobile checks. The [cumulative learning record](cumulative-learning-validation.md) covers live teaching and multiple revisions for reporting and correction, unseen records, previous layouts/requests, restart, rollback, stable version pins and guidance-only learning. Its [evidence artifact](evidence/cumulative-learning.json) retains all 22 runs, including six failed or partial development attempts. Business execution stayed under Strict approval throughout.

## Lookup through existing approved tools, 2026-09-12

After removing the hand-coded `read_invoice` operation, price-specific routing, and fixed answer template, one native Windows check used live GPT 5.6 Luna with explicitly simulated staff decisions. The agent selected INV-1042, used the existing `establish` operation, called `observe_app`, and answered **$1,480.00** from the current observation. The runtime required staff review of the answer. No workflow ran and no business mutation was attempted. The run used four model calls. See [recorded evidence](evidence/generic-observation-lookup.json).

This demonstrates answering through existing approved tools, not a learned lookup skill. The current learner composes its existing bounded Finance operations; it does not yet distill every conversational answer or generate new application capabilities. The 21 focused regression tests passed, including observation-based answers at different amounts, missing-record reporting, record binding, approval recovery, activity filtering and existing workflow learning. Two observation-answer cases passed again after the final general completion guidance changed. Those tests use a simulated model.

## Conversational invoice lookup and activity, 2026-09-12

These historical checks include an experimental hand-coded `read_invoice` shortcut. That shortcut and its price-specific coordinator routing were subsequently removed; the price results below are not evidence of learned lookup behavior.

Six native Windows checks used live GPT 5.6 Luna and explicitly simulated staff decisions. Every message entered chat without a structured invoice field. See [the recorded results](evidence/conversational-records.json).

| Request | Observed result | Model calls |
| --- | --- | --- |
| Price of INV-1042 | Approved record selection and one direct `read_invoice`; answered $1,480.00, without a comparison workflow | 2 |
| Price of INV-5783 | Reported that the record was absent from the current visible invoice list and ended the lookup | 2 |
| Comparison request without a record | Asked for the invoice ID, with no business approvals | 1 |
| Follow-up containing only INV-1043 | Continued the earlier comparison through the installed reporting skill and verified its result | 3 |
| Rejected selection of INV-1044 | Ended without binding the record or operating on it | 1 |
| Discrepancy report for INV-5799 | Ended with a visible-list lookup result when the workflow could not find the record | 3 |

No business mutations were attempted in these checks. Visible-list absence is not proof that a record does not exist in the entire application. The prior lookup error conflated an absent control with general UI recovery; the new result preserves the scoped observation and stops the lookup cleanly. A malformed recovery click supplying both a target and coordinates previously terminated the request. A regression now exercises returning that validation error to the agent, which corrects its next proposal and waits for approval without losing its workflow state.

Record selection and its consumed approval receipt commit atomically; a dropped response cannot lose a staff correction. Frontend checks cover the expandable call/result log, filtering, escaped text and keeping evidence expanded across refreshes. The log records public explanations and execution evidence, not private model reasoning. Earlier live follow-up attempts produced prose requesting approval without an actual tool proposal; the corrected coordinator instructions and final successful continuation are represented in the results above. These earlier failures remain in the local evaluation archive.

The older sections below describe historical builds, including the retired Auto mode; current business execution requires staff approval.

## Local regression suite

The pre-improvement baseline passed **90 tests, with 2 candidate-only tests skipped**, in 179.20 seconds. The reviewed improvement passed **95 tests** in 188.65 seconds. Lint, formatting, GitHub regression checks, and both Windows builds passed on the reviewed candidate.

The Linux suite exercises real Chromium, separate backend/worker processes, temporary persistent databases, strict node and tool approvals, automatic discovery, modes, corrections, handoff, rejected/denied/cancelled work, and restart after an ambiguous save. Candidate-only tests are skipped on the baseline and enabled in the improvement checkout. Additional tests cover delayed SQLite checkpoints, serialized desktop access, code-failure diagnostics, preventing edits before verified business values exist, accessibility parsing, stale geometry, and refusing another uncertain Save. Native accounting-model tests validate 10 invariants. Both Windows executables include their .NET runtime.

## Native Windows machine

DemoBooks was installed in the logged-in Windows desktop session and connected through an authenticated SSH tunnel. Its screenshots come from the actual screen. The original runs below use the app's scoped bridge and a simulated model.

| Scenario | Verified result |
| --- | --- |
| Strict correction | Completed with seven node approvals |
| Auto correction | Completed with no approval prompts or model calls |
| Changed field label | Entered supervised assistance, then independently verified the result and restored Auto |
| Interrupted save confirmation | Reconciled the persisted draft without a duplicate save |
| Another window covers DemoBooks | Recovered automatically before the next preview |
| DemoBooks minimized | Restored automatically and completed the job |
| Staff takeover while another window is active | Left focus alone until staff released control |

The native app also passed known-notice, unfamiliar-dialog, unsaved-dialog, wrong-record, reordered-row, delayed-view, and changed-layout checks. Known interruptions completed in Auto without assistance; unfamiliar and unsaved dialogs required individually approved assistant tools. See [native recovery variants](evidence/native-recovery-variants.json).

See [native demo results](evidence/native-demo-report.json) and [window recovery evidence](evidence/native-window-recovery.json). The desktop recovery tests deliberately introduced another process's window and minimized DemoBooks. Recovery required no manual minimize or focus action. The header-click fallback targets only DemoBooks' verified inert header; it does not dismiss application dialogs or operate arbitrary desktop controls.

## Limits

This is a synthetic application we control, not QuickBooks. The independent desktop controller supports Windows accessibility and input, but business interpretation and navigation still use a DemoBooks-specific adapter. Arbitrary custom-drawn applications without accessible controls need additional visual interpretation and verification. A locked session or secure desktop cannot be treated as an available interactive accounting session. Cross-department extension points exist, but Finance is the only shipped example worker. General workflow-code generation and full recording of unmediated human desktop demonstrations remain future work.

## Application API disabled

The independent desktop controller was tested with DemoBooks launched using `--no-api`; the VM listened only on the controller port, with no listener on the application API port.

- Auto completed through accessibility invocation and value patterns without model calls.
- Strict completed through actual mouse input and keyboard typing with seven individual node approvals.
- A renamed field triggered live GPT 5.6 Luna assistance with the latest screenshot. Individually approved actions completed the correction and the graph restored Auto.

See [API-disabled execution evidence](evidence/native-no-api.json). The adapter verified the visible saved draft and its unique job reference; it did not read the app's data files or call its accounting API.

## Live-provider findings

The initial OpenRouter connection check returned the requested tool call using 74 tokens. A live run exposed ambiguous cents-versus-dollars instructions: the proposed amount was wrong and the application rejected Save. The context now supplies explicit units and expected form strings. Another pre-comparison run exposed a missing mutation guard; tools now exclude editing and saving before verified business values exist, with an independent execution-time restriction. See [live provider evidence](evidence/native-live-openrouter.json).

Desktop testing also found that Windows can report a minimized application as foreground. Recovery now requires both foreground ownership and a restored window. Delayed checkpoint tests reproduced a deadlock with a single asynchronous checkpoint executor; checkpoint I/O now has its own concurrency allowance, synchronous durability, and independent serialized desktop execution.

A later Linux regression run crashed during the optional 45-second diagnostic stack dump. The process exited with SIGSEGV, and its core backtrace located the fault in `_Py_DumpTracebackThreads` on the diagnostic thread. Periodic native traceback dumping has been removed; integration requests now check backend/worker process health and report exit codes and logs immediately. This finding is specific to the local Python 3.12.3 run; it does not establish that all Python versions or desktop adapters have the same failure.

## Edge deployment checks

The Python worker and its Deep Agent harness were installed on Windows using Python 3.13.15. The developer machine runs the backend alone. In Windows mode, the backend initializes without desktop credentials or a desktop connection; browser fixture routes return 404.

An initial live read-only check stopped before a business action when window recovery encountered an off-screen title bar. The controller now maximizes an off-screen application before activation, and the worker task uses `pythonw.exe` so its launcher does not cover the application. A subsequent check navigated to the invoice using an approved real click. That discovery check was cancelled when the model proposed a purchase-order menu target outside the current tool allowlist. Exposed UI controls do not automatically grant permission to operate them; broader discovery navigation remains incomplete.

A subsequent correction completed from the Windows worker with the application API disabled, using real mouse/keyboard input and live OpenRouter assistance. It recovered from an unsaved-changes dialog and input-focus interruptions, verified the saved draft, and restored Auto. It required 10 model calls and 40,372 tokens; this demonstrates the full deployment but also shows that recovery remains expensive. See [Windows edge worker evidence](evidence/windows-edge-worker.json). All staff decisions in this check were explicitly simulated.

The metrics page was checked in Chromium for selected navigation state, matching page heading, percentage formatting, automatic refresh while visible, and returning to the worker console.

A live unmatched read-only request also completed on Windows: the worker reported the visible invoice and purchase-order totals and difference, then required staff approval of that report. It made one model call, used 3,186 tokens, and attempted no business mutation. See [live workflow discovery evidence](evidence/live-workflow-discovery.json). An earlier test-driver check was cancelled because its expected invoice amount was stale; the model's report matched the actual visible values.

## Original-requirement completion checks

A separate knowledge store now enforces organization, department, role, and company scope before ranking documents. Tests cover out-of-scope exclusion, exact-query approval before retrieval, worker publication denial, spoofed scope arguments, and independent rejection of misrouted jobs before desktop/graph initialization. One Windows live-model check retrieved synthetic guidance with an approved search and cited its source in a separately approved report: two model calls, 6,463 tokens, no mutation. See [scoped knowledge evidence](evidence/scoped-knowledge.json).

An isolated browser test now exercises the complete release path with an explicitly simulated developer decision: unfamiliar label recovery, rejected unapproved deployment, reviewed fixture deployment, a different record/layout completing without fallback, version pinning, and rollback. That fixture decision does not approve or release the real improvement PR.

The [original requirement audit](original-prompt-audit.md) maps the implementation, evidence, and deliberate limits.

## Human-approved release on Windows

The project developer explicitly approved PR #1 commit `cac88dea82cdd5aa05f78113012fa1d75385ff67` in the project conversation. The release command verified the exact candidate, its test evidence, and passing GitHub checks, then activated v2 while idle. The PR was subsequently merged.

Invoice INV-1042 completed with the changed “Adjusted total” label in **12.56 seconds**, with **zero fallback calls, zero model calls, and a confirmed saved draft**. The teaching episode used INV-1044 and remains pinned to v1. The successful check used the Windows edge harness and accessibility actions with DemoBooks' application API disabled. Staff acceptance was explicitly simulated; developer release approval was human. The previous v1 registry remains available for rollback. See [reviewed release evidence](evidence/reviewed-release.json).

Two preceding mouse/keyboard checks paused on “Input focus changed before typing” and were cancelled without saving. The label itself was recognized. The first attempt to switch input modes was blocked by PowerShell's execution policy, so the second check still used keyboard input; the worker was then restarted successfully in accessibility mode. That historical check used accessibility input. The focus race was subsequently diagnosed and fixed; the current Windows worker uses mouse/keyboard input. The later evidence is recorded below.

## Operation contracts, conversation, and focus recovery

The updated local suite passed 124 tests, including malformed operation input/output rejection, deadline fencing, bounded retries with fresh approval, staff-guidance invalidation, durable agent questions, and evidence-derived improvement analysis. Question/answer integration tests use the real Deep Agent checkpoint machinery with explicitly simulated models.

The native controller now waits up to 500ms for the exact approved edit control after `SetFocus`; losing the assigned foreground window still aborts input. An interactive Windows diagnostic observed stale focused-element reports on five of six immediate samples, with all six matching the intended target after 50ms. The subsequent mouse/keyboard job on INV-1043 verified a saved draft in 16.17 seconds with no fallback or model calls. This is a deterministic native check, not a live-model evaluation. See [focus evidence](evidence/windows-focus-recovery.json).

## Completed acceptance checks

The final acceptance implementation passed **139 tests** in [CI](https://github.com/philip-roy-jones/enterprise-agent-system/actions/runs/34559108561), with successful native accounting smoke checks and both Windows builds. The backend shutdown bound was then verified separately with a deliberately open event stream: it exited after cleanup in 5.19 seconds. The [requirement audit](original-prompt-audit.md) maps all 17 sections.

The evidence-derived v3 proposal passed **127 isolated tests** and GitHub checks. It learned its label from an actual recorded browser correction and generated new-record/layout regressions. The proposal is a draft, with no developer approval or deployment. This is separate from the previously human-approved v2 release. [Proposal evidence](evidence/derived-improvement.json).

A live OpenRouter model on the Windows harness asked an approved question, waited for the simulated staff answer, and reported the requested purchase-order total without changing or saving data: 6 model calls, 24,567 tokens, 34.83 seconds. [Conversation evidence](evidence/live-staff-conversation.json).

After the combined rollout, a native mouse/keyboard job on INV-1042 completed in 21.93 seconds with zero fallback/model calls and a verified saved draft. The application API remained disabled. Chromium then submitted an explicitly simulated staff assessment, verified that the live metric incremented, and checked both sidebar selections with no JavaScript errors. [Rollout evidence](evidence/final-windows-validation.json).

Incorrect-action totals represent staff reports; unassessed operations are counted separately. They are not a general safety score. Historical debug runs with missing elapsed times are identified rather than backfilled with invented durations.


## Independent application packages — 2026-09-11

The server and edge harness now build as separate Python distributions, alongside a small contracts library. Fresh virtual environments installed each application with its own dependencies. The server served packaged frontend assets, listed roles and accepted a job with no harness, LangGraph, Deep Agent or Playwright installed. The harness contacted a synthetic HTTP claim endpoint and created its local checkpoints with no server, development tooling or Playwright installed. These checks run in CI through `tools/check_installation.py`.

The full regression suite passed **158 tests**. Three additional generated-workflow checks passed against an isolated copy of the new package layout, using simulated staff and model behavior. Review/deployment regression tests cover candidates from all three historical source layouts; the existing proposal #2 still verifies against its original hashes and remains pending review. The relocated Windows desktop controller built successfully, and the harness installer scripts parsed successfully in Windows PowerShell. This validates packaging and compatibility, not new model quality or a new accounting transaction.
