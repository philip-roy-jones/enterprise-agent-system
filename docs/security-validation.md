# Security boundary validation — 2026-09-13

The [accepted plan](plans/security-boundaries-and-authorization.md) is implemented through phases A–E for the prototype. Phase F has profiles, distinct enrollment and independent lease tests; physical multi-VM validation, fleet placement and cross-worker context/package replication remain outstanding. The code does not silently share private knowledge to compensate for those missing features.

## Evidence and checks

| Area | Evidence | Limit |
| --- | --- | --- |
| Individual identities and resource policy | Adversarial HTTP tests cover requester/approver separation, actor spoofing, wrong department/company, guessed request/approval/artifact IDs, history, aggregates and private skills | Synthetic identities and data; no customer directory |
| OIDC and browser sessions | Controlled RSA provider tests cover issuer/audience/signature, PKCE, nonce, browser-bound one-time state, replay, CSRF and logout | No real enterprise IdP configured |
| Worker protocol and grants | Separate planner/executor/admission permissions; current assignment; exact schemas; grant tampering, replay, expiry, policy revocation and wrong executor rejected | Privileged executor/application truth remains trusted |
| Context | Broker-backed actual LangGraph interrupt/restart; opaque checkpoint storage; cross-person history denial; policy changes end old continuations and isolate subsequent notes/history | Does not retract data already sent to a provider or copied by a compromised account |
| Learning | Accepted source audience checks, private metadata/content filtering, origin-worker maintenance, separate publication authority, lifecycle permission | No cross-worker distribution/declassification feature |
| Windows | Actual `eas-planner` and `eas-learner` run in Session 0; denied app records/token/config/code/ACL/process access; no DemoBooks UI Automation elements; unauthenticated controller returns 403 | One VM; not a red-team assessment of Windows or the hypervisor |
| Packaging | Server-only and harness-only clean virtual environments install and run independently | No claim that the developer's all-dependency environment is isolated |
| Migration | Existing archive preserved; three active legacy versions revalidated, then the newly learned fourth version preserved through the final runtime update | Legacy in-flight checkpoints must be drained; pending PR proposals are not deployed |

The final regression suite passed **235 tests in 1,212.64 seconds (20 minutes 12 seconds)** using `pytest -q --tb=short`. Lint and formatting passed; both application packages also passed installation and startup checks in separate clean environments. There was one upstream AnyIO/Starlette deprecation warning. The earlier 229-test security run also passed, before the final scope and context-revocation cases were added. CI's test timeout is 30 minutes because the broker adds real process/HTTP boundaries to the regression path.

The implementation was exercised during development, not merely checked once. Earlier runs found a foreign-request test using the wrong identity, an uncertain-save restart referencing an uninitialized adapter, and missing direct-operation trace entries. These were corrected without weakening resource policy, reconciliation or learning admission. A fresh-memory window also needed initialization before its first read, and derived comparison evidence needed to inherit its owning request's confidentiality so authorized learning results remained visible. Intermediate runs during those corrections are not counted as final passes.

## Live model runs

The [sanitized evidence](evidence/security-boundaries.json) records actual OpenRouter model calls on Windows with **simulated staff approvals** and synthetic records. The application API was disabled; the executor used the independent desktop controller. No real staff acceptance or production validation is claimed.

1. A greeting completed with one live model call and no business approval.
2. A taught invoice-total lookup read INV-1042 and answered **$1,480.00**. Four individually approved operations executed. The independent driver compared the answer to native observed record evidence, then accepted it. The isolated learner proposed a guidance package, runtime-owned checks admitted it, and it activated automatically.
3. A separate INV-1043 request read that admitted skill and answered **$2,640.00**, again with four individually approved operations. The test identity could retrieve its lesson; the ordinary staff identity could not retrieve that private lesson or its metadata.
4. A discrepancy report for INV-1042 completed six individually approved operations, including a separate scoped judgment call. It reported **+$200.00** and made no accounting changes. Its first learned candidate was rejected for inventing an unobserved field label. A second accepted report correctly returned **+$240.00** for INV-1043, but its candidate cited unavailable evidence and was also rejected. A successful business outcome therefore did not bypass admission. These two attempts did not produce a newly admitted report graph; the separate lookup lesson did activate and was reused.

The lookup tests validate guidance retrieval and reuse, not arbitrary application understanding. The numeric checker is a bounded synthetic oracle and the underlying observations are executor reports. Guidance-only admission explicitly lacks general behavioral evaluation. A subsequent live run under the explicitly authorized development supervisor read and invoked a migrated discrepancy graph for INV-1044. It executed six child operations with their own approvals, correctly reported **+$75.00**, and saved no draft. This used eight approvals and four actual model calls after the final edge restart. Graph recovery and save reconciliation are also covered by regression tests.

## Operational status and remaining evidence

The backend and installed `EAS-Planner`, `EAS-Executor`, and `EAS-Learner` are running. The legacy combined worker is disabled. Central and edge credentials were separated; controller access remains on the Windows edge. The current human login is an explicitly labeled individual development identity. A real OIDC deployment is still a separate integration exercise.

The OS probes establish the tested account boundary on this installation. They do not establish that a compromised privileged desktop account cannot use its own applications, nor that several physical workers remain isolated. The server's distinct-worker tests exercise assignment/lease policy, not VM provisioning or pooled persistent memory. Retention is operator-managed; revocation prevents future authorized access but is not remote data erasure. See [setup](developer-setup.md) and [retirement/recovery](security.md#revocation-retention-and-recovery).
