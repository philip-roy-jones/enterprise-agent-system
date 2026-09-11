# Validation record

Regression tests use an explicitly **simulated model**. Separate native Windows demonstrations use **GPT 5.6 Luna through OpenRouter**. Scripted staff decisions are labeled simulated in both cases; developer release approval remains a separate human step. These are bounded demonstrations, not a general assessment of model reliability.

## Local regression suite

Latest local result: **90 passed, 2 candidate-only tests skipped** in 179.20 seconds. Lint and formatting passed; the independent desktop controller build passed in the preceding native validation.

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

The [original requirement audit](original-prompt-audit.md) maps the implementation, evidence, deliberate limits, and remaining human release gate.
