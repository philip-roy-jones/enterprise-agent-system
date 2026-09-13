# Security boundary validation — 2026-09-13

The [accepted plan](plans/security-boundaries-and-authorization.md) is implemented through phases A–E for the prototype. Phase F has profiles, distinct enrollment, independent leases and actual Windows/Ubuntu checks; automatic fleet placement and cross-worker context/package replication remain outstanding. The code does not silently share private knowledge to compensate for those missing features.

The current regression suite passed **240 tests in 1,203.95 seconds (20 minutes 3 seconds)**, with one upstream AnyIO/Starlette deprecation warning. Lint and formatting passed. Fresh server-only and harness-only environments installed and started independently. DemoBooks passed ten native accounting checks and a Windows x64 publish from its new directory.

## Evidence and checks

| Area | Evidence | Limit |
| --- | --- | --- |
| Individual identities and resource policy | Adversarial HTTP tests cover requester/approver separation, actor spoofing, wrong department/company, guessed request/approval/artifact IDs, history, aggregates and private skills | Synthetic identities and data; no customer directory |
| Email/password and browser sessions | Argon2id accounts, one-time expiring setup/reset, reset races, persistent throttles, same-origin checks, CSRF and logout; actual browser setup/sign-in and workspace switching | No mailer; organizational SSO removed from prototype scope |
| Worker protocol and grants | Separate planner/executor/admission permissions; current assignment; exact schemas; grant tampering, replay, expiry, policy revocation and wrong executor rejected | Privileged executor/application truth remains trusted |
| Context | Broker-backed actual LangGraph interrupt/restart; opaque checkpoint storage; cross-person history denial; policy changes end old continuations and isolate subsequent notes/history | Does not retract data already sent to a provider or copied by a compromised account |
| Learning | Accepted source audience checks, private metadata/content filtering, origin-worker maintenance, separate publication authority, lifecycle permission | No cross-worker distribution/declassification feature |
| Windows baseline | Actual `eas-planner` and `eas-learner` run in Session 0; denied app records/token/config/code/ACL/process access; no DemoBooks UI Automation elements; unauthenticated controller returns 403 | Not a red-team assessment of Windows or the hypervisor |
| Packaging | Server-only and harness-only clean virtual environments install and run independently | No claim that the developer's all-dependency environment is isolated |
| Migration | Existing archive preserved; three active legacy versions revalidated, then the newly learned fourth version preserved through the final runtime update | Legacy in-flight checkpoints must be drained; pending PR proposals are not deployed |

The earlier security baseline passed **235 tests in 1,212.64 seconds (20 minutes 12 seconds)** using `pytest -q --tb=short`. Lint and formatting passed; both application packages also passed installation and startup checks in separate clean environments. There was one upstream AnyIO/Starlette deprecation warning. The earlier 229-test security run also passed, before the final scope and context-revocation cases were added. CI's test timeout is 30 minutes because the broker adds real process/HTTP boundaries to the regression path.

The implementation was exercised during development, not merely checked once. Earlier runs found a foreign-request test using the wrong identity, an uncertain-save restart referencing an uninitialized adapter, and missing direct-operation trace entries. These were corrected without weakening resource policy, reconciliation or learning admission. A fresh-memory window also needed initialization before its first read, and derived comparison evidence needed to inherit its owning request's confidentiality so authorized learning results remained visible. Intermediate runs during those corrections are not counted as final passes.

## Earlier Windows live model runs

The [sanitized evidence](evidence/security-boundaries.json) records actual OpenRouter model calls on Windows with **simulated staff approvals** and synthetic records. The application API was disabled; the executor used the independent desktop controller. No real staff acceptance or production validation is claimed.

1. A greeting completed with one live model call and no business approval.
2. A taught invoice-total lookup read INV-1042 and answered **$1,480.00**. Four individually approved operations executed. The independent driver compared the answer to native observed record evidence, then accepted it. The isolated learner proposed a guidance package, runtime-owned checks admitted it, and it activated automatically.
3. A separate INV-1043 request read that admitted skill and answered **$2,640.00**, again with four individually approved operations. The test identity could retrieve its lesson; the ordinary staff identity could not retrieve that private lesson or its metadata.
4. A discrepancy report for INV-1042 completed six individually approved operations, including a separate scoped judgment call. It reported **+$200.00** and made no accounting changes. Its first learned candidate was rejected for inventing an unobserved field label. A second accepted report correctly returned **+$240.00** for INV-1043, but its candidate cited unavailable evidence and was also rejected. A successful business outcome therefore did not bypass admission. These two attempts did not produce a newly admitted report graph; the separate lookup lesson did activate and was reused.

The lookup tests validate guidance retrieval and reuse, not arbitrary application understanding. The numeric checker is a bounded synthetic oracle and the underlying observations are executor reports. Guidance-only admission explicitly lacks general behavioral evaluation. A subsequent live run under the explicitly authorized development supervisor read and invoked a migrated discrepancy graph for INV-1044. It executed six child operations with their own approvals, correctly reported **+$75.00**, and saved no draft. This used eight approvals and four actual model calls after the final edge restart. Graph recovery and save reconciliation are also covered by regression tests.

## Windows and Ubuntu follow-up

[Sanitized two-host evidence](evidence/two-host-workers.json) records actual OpenRouter calls to `openai/gpt-5.6-luna`, with **simulated staff approvals and acceptance**. Both workers use separate planner, executor and learner processes; the backend runs no agent.

- Concurrent requests were assigned to different registered workers. Windows read INV-1042 as **$1,480.00**, matching its native application observation. Ubuntu reported CAM-2002 with 15,000 impressions, 450 clicks, $225 spend, a 3% click-through rate and $0.50 cost per click.
- An earlier accepted CAM-2001 report produced the automatically admitted `report-campaign-performance` skill. A separate live learner used 3,001 tokens. Runtime-owned checks exercised different values, zero denominators, changed revisions and missing records. CAM-2002 reused that exact version with approvals for reading it, invoking it and each of its four graph operations.
- The successful concurrent requests used six Finance model calls and four Marketing calls. Their token counts and exact operations are in the evidence file. No business writes were proposed or executed.
- Finance and Marketing staff fixtures could neither request the other department nor retrieve its request. Actual service credentials on both hosts authenticated successfully and were denied foreign assignments and staff-session access.
- Ubuntu planner and learner probes each passed eleven checks under the installed service restrictions, including positive controls. They could not read protected credentials/application records, write execution code, inspect executor memory or create a listener; unauthenticated Campaign Desk access returned 401. These checks exercise API use, not Linux desktop automation.
- The final source upgrade requalified four Finance skills and one Marketing skill with no quarantines, preserving both conversation archives. Forty-six shared/harness source files matched the installed packages on each host; neither edge installed the server or the retired workflows package.
- An additional live CAM-2003 run restarted the Ubuntu planner and executor while its graph waited at validation. The same run resumed, required fresh approval and executed each child once. It correctly reported zero activity with undefined rates. A prior zero-activity request also returned correct metrics through individual approved operations; it did not exercise graph restart and was not counted as restart evidence.
- Browser checks exercised single-use password setup, removal of the setup fragment, normal sign-in, preserved conversation history, department filtering, authorized workspace switching and logout. They reported no JavaScript errors.

Failures remain part of the record. The first Finance attempt found DemoBooks closed. After it reopened, later attempts repeated old unavailability without checking the current application. A new prompt instruction alone did not prevent this. Explicit staff context saying the application had reopened led to the recorded fresh observation and correct answer. The earlier unsuccessful attempts were not accepted as successful teaching. This does not establish automatic recovery from every stale model belief.

The initial Ubuntu socket probe also failed: the tested systemd build did not enforce `SocketBindDeny` alone. Adding a seccomp restriction on `bind` made the actual planner/learner probes pass. Configuration text without a working access test was not counted as isolation evidence.

## Operational status and remaining evidence

Staff now use individual email/password accounts with the original principal IDs and history. Setup links are issued by the operator without a mailer. Workers retain separate machine credentials; they cannot sign in or approve as staff. The prior OIDC implementation and tests have been removed at the owner's request.

The backend, Windows tasks and Ubuntu services are installed. Legacy graph-first executable examples are retained only in development tooling; deployed skills use the Deep Agent entry point and shared protected execution. Optional synthetic software lives separately under `src/test-software/` and is not a server or harness dependency.

Account probes establish the tested account boundaries. They do not establish that a compromised privileged application account cannot use its own applications, or that the OS and hypervisor are secure. Two concurrent workers do not establish automatic fleet placement or shared persistent memory. Cross-worker skill/context replication remains unimplemented and delivery fails closed. Retention is operator-managed; revocation prevents future authorized access but is not remote erasure. See [setup](developer-setup.md), [Ubuntu installation](linux-worker.md) and [retirement/recovery](security.md#revocation-retention-and-recovery).
