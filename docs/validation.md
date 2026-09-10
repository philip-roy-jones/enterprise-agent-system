# Validation record

The prototype uses a **simulated model**. These runs validate the execution, supervision, persistence, and recovery mechanisms; they do not evaluate live model judgment. The scripted demonstration also uses explicitly simulated staff approvals. Developer release approval remains a separate human step.

## Local regression suite

The full Linux suite passed **62 tests**, with **2 candidate-only tests skipped** on the baseline. It exercises real Chromium, separate backend/worker processes, temporary persistent databases, strict node and tool approvals, modes, corrections, handoff, rejected/denied/cancelled work, and restart after an ambiguous save. Focused native adapter tests include exclusive window recovery and respecting staff takeover. Native accounting-model tests validate 10 invariants, and the Windows x64 build includes its .NET runtime.

## Native Windows machine

DemoBooks was installed in the logged-in Windows desktop session and connected through an authenticated SSH tunnel. Its screenshots come from the actual screen. The worker uses the app's scoped bridge for accounting controls.

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

This is a synthetic application we control, not QuickBooks. Native business actions use known app controls; generic Windows accessibility or vision automation is not implemented. A locked session or secure desktop cannot be treated as an available interactive accounting session. Cross-department extension points exist, but Finance is the only shipped production-shaped example workflow. GitHub CI results and the improvement proposal are linked from the repository once their checks finish.
