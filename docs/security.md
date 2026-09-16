# Authorization and worker security

> Current execution policy: [digital employees](plans/digital-employees.md) use shadowing / active / paused. Active work uses server authorization without per-operation staff approval. Historical Strict-policy descriptions below remain as background where noted.

This is prototype security engineering, not an enterprise-readiness claim. The [implementation plan](plans/security-boundaries-and-authorization.md) defines the threat model; the [validation record](security-validation.md) distinguishes automated checks, actual Windows probes, and untested deployments.

## Authority and access

The server authenticates each person and service, reloads its registered entitlements, and authorizes the specific resource and action. Browser fields, a worker-supplied name, and model explanations do not establish identity. Ordinary staff grants restrict records to their original requester; an explicitly scoped reviewer can read and approve another person's work. Request and approval rights are separate. One authorized person may do both.

| Identity | Permitted responsibility | Excluded authority |
| --- | --- | --- |
| Staff | Request, read, approve, control, accept, or manage skills according to explicit grants | Other people's resources without a grant; service RPCs; changing policy |
| Planner | Claim an eligible assignment; plan; read its authorized context; request registered operations through the executor | Staff decisions; application/controller credentials; arbitrary executor code; admission |
| Executor | Registered operations for its current assignment; consume exact grants; report receipts | Human decisions; other workers' assignments; widening policy |
| Admission | Claim its worker's maintenance; validate and publish packages within the accepted evidence scope | Staff decisions; broadening evidence audience; organization-wide deployment |
| Deployment operator | Provision/revoke identities; install trusted code and OS profiles | No automatic business-data access through a human API identity |

The identity file is a trusted deployment artifact. `python -m eas_server.admin` provisions staff identities, one-time password setup links and distinct worker service credentials. Staff sign in with email/password; Argon2id hashes and single-use expiring setup hashes stay in the server database. Account/client throttles persist across restarts. Browser cookies are HttpOnly, SameSite Strict, Secure over HTTPS, expire after one hour and require CSRF headers for mutations. Completing password setup/reset invalidates that person's sessions without changing their identity or history. Organizational SSO has been removed from the prototype. Explicit development bearer fixtures remain separate from the staff login UI; password mode rejects human bearer credentials.

## One approved operation

1. The executor submits a registered operation, its arguments and a fresh observation. The server compares its schema, permission and target with trusted contract metadata.
2. An authenticated, entitled person approves the exact proposal. A graph approval grants no authority to its children.
3. The server issues an Ed25519-signed, 30-second grant bound to the executor, requester, approver, request, invocation, arguments, observation, policy revision, lease epoch, contract and pinned skill versions.
4. The executor presents the grant before performing the effect. The server consumes its identifier once, transactionally with the action ledger. Changes, replay, expiry and revocation fail closed.
5. The executor reports a typed receipt. The server derives completion from the ledger; a planner cannot simply declare verified success.

Reports and screenshots from an authenticated executor are **executor-reported evidence**. Structural validation and signatures do not independently prove application truth. Staff outcome acceptance is recorded separately. A privileged compromised edge can lie about its own application; it cannot mint staff decisions or access another worker's server assignment.

Registered desktops have separate leases. Every interactive desktop still permits one active operation. Cancellation prevents future effects; an operation already in flight must report or reconcile before that desktop can take new work. Lost confirmation around a save retains the original invocation and uncertain-write state. Do not clear a stuck lease or replay a save to make a queue move.

## The Windows boundary

The edge harness remains one installed application with internal privilege separation:

- `EAS-Planner`: a dedicated non-admin, noninteractive Windows account in Session 0. Runs the Deep Agent and LangGraph coordinator. Holds its planner credential and model-provider key.
- `EAS-Executor`: the designated interactive desktop account, running without elevation. Holds controller/application access, the executor credential and the separate admission credential. Owns the execution ledger client, protected context/checkpoint broker, and runtime-owned package validation.
- `EAS-Learner`: another non-admin, noninteractive account. Receives bounded JSON evidence and returns untrusted candidate data through ACL-restricted directories. Holds a model-provider key, no server or controller credential.

Code, interpreter and configuration are SYSTEM-owned; service accounts cannot rewrite their ACLs to regain write access. Each account can write only its own runtime state. The planner cannot read the executor's configuration, controller token or DemoBooks records, inspect the application's process memory, or automate its interactive desktop. The controller also rejects unauthenticated loopback requests. These properties were probed under the actual installed accounts; they are not inferred from a model refusing an instruction.

Checkpoint values stay opaque on the privileged side. The planner serializes/deserializes its own LangGraph data; the executor stores bounded JSON/base64 envelopes without unpickling them. Context, notes, archives and searches use the server-fetched original person and work scope. Every broker call rechecks current authority online. A registry-policy revision ends an existing continuation and creates a fresh internal memory namespace for subsequent requests; restoring an older policy does not resurrect its old notes or history. The staff-facing chronological conversation stays intact. The initial trusted migration binds preserved legacy context to the first authorized policy, without changing its original person/scope. A policy change invalidates browser sessions and future grants; it cannot erase information already in a process, exported to a provider, or copied by a compromised host.

Application privileges remain the outer limit. An attacker controlling the interactive desktop account can bypass the broker and operate applications already accessible to that account. Use separate environments for incompatible application/data boundaries. This design does not require one VM per employee. Do not populate every environment with every company's credential and call server approvals isolation.

## Learned knowledge

Generic examples remain in `src/edge-harness/skills/`. Private versions remain protected runtime data and immutable server catalog entries, not commits to the harness repository. The ordinary learner cannot publish. Runtime-owned admission validates the constrained package and its accepted, executed source evidence before publication.

Package titles, instructions, examples, resources, versions and evidence all require authorization. A reader must be able to read every source episode. A learner cannot remove evidence restrictions by changing parallel metadata. Only the registered generic seed may omit teaching evidence. Maintenance families include the originating person and registered desktop, so unrelated staff or workers do not silently contribute private history. Same-scope learning still activates automatically; business operations still require Strict approval.

Distribution is currently restricted to the originating registered worker. There is no cross-worker sharing/declassification endpoint. Replicas have distinct identities and independent leases, but sharing skills or moving a persistent context to another replica is not yet implemented. An environment-scope fingerprint prevents rebinding an existing protected runtime to another scope without deliberate reprovisioning.

## Revocation, retention and recovery

Use the local administration command to revoke a person, service principal or whole worker. Policy is checked at the next server request and before grant consumption; there is no cached allow window in the protocol. This is not a distributed cancellation guarantee for an effect that already began. Only narrow final receipts can finish an existing in-flight record after requester revocation.

Retention is explicit **operator-managed retention**, with no automatic TTL or selective erasure API in this prototype. Central SQLite data, artifacts and signing keys, protected edge context/checkpoints/packages, and operator backups persist until retired. They are sensitive data, not disposable caches. Runtime source copies and model-provider retention require their own controls.

To retire or change a boundary: drain work and maintenance; resolve uncertain writes; revoke all three service identities; stop tasks; remove application sessions and rotate controller/application/provider credentials; archive only under the former access restrictions or dispose of the old edge runtime, user profiles and backups under your retention policy; provision a clean environment and new worker ID. Do not reuse the former runtime in a new department. Removing a registry identity alone is not deletion of retained data.

For upgrade, back up central and edge state while drained. The operator-only `eas_harness.migrate` copies conversation archives and revalidates already-active legacy packages against current runtime dependencies and original accepted evidence. It does not deploy pending historical PRs or reassign legacy conversations to a new person. Uniquely owned historical artifacts receive their original request owner. Keep old shared history restricted until ownership can be established.

Rollback must preserve current identity policy, ownership, protocol version and revocations. Never restore the old broad worker RPC/shared-token configuration as a compatibility fix. Expired grants need a fresh authorized attempt; uncertain effects need reconciliation, not a grant replay.

## Limits and sources

The OS, hypervisor, deployment administrator, password account store, central authority, operation implementations and privileged executor/admission runtime are trusted. Planner/learner accounts are not network sandboxes and can send data they legitimately receive to their configured model provider. Provider egress restrictions, disk encryption, external audit storage, automated fleet placement, automated retention and broader host security assessment remain deployment work. Windows and Ubuntu account access and cross-department requests have been checked on the actual two-host installation; see the validation record.

The design follows [OWASP resource authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html), [NIST's resource-based trust model](https://csrc.nist.gov/pubs/sp/800/207/final), and [OWASP password storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html). Windows service/session behavior is described in [Microsoft's interactive services documentation](https://learn.microsoft.com/en-us/windows/desktop/Services/interactive-services).
