# Enterprise Agent System: authorization and worker security boundaries

Status: **A–E implemented for the prototype; F has registration/lease support and Windows/Ubuntu validation; fleet distribution remains outstanding.** 2026-09-13. See the [measured validation record](../security-validation.md).

This is the accepted plan and scope record for the security work after the [agent-led learning milestone](agent-led-learning-plan.md). The implementation and actual deployment evidence are described in [security](../security.md) and [validation](../security-validation.md); this document does not establish enterprise readiness. Preserve the delivered learning behavior and [persistent staff conversation](persistent-session-context.md).

## Outcome

Staff describe outcomes to a supervised assistant. The Deep Agent plans the work, but cannot grant authority to itself. The server independently authorizes people, workers, resources, and exact operations. A protected execution service performs approved operations within its environment's limited application access.

Learning improves procedures without increasing permissions or reducing Strict approvals. A distinct worker identity supports attribution and revocation; it does not turn the model into an independently authorized employee.

Keep three software boundaries: server/frontend, edge harness, and independent synthetic business applications (DemoBooks Desktop and Campaign Desk). The server runs no Deep Agent, LangGraph, or learner. The edge harness can contain separately privileged services without becoming a new product or requiring a separate repository. `src/shared/` remains API/data contracts only.

Use the existing Windows VM and synthetic data for development. Individual employee identities and permission combinations do not each require a VM. Physical isolation claims require separate validation from application authorization tests.

> Scope update: organizational SSO/OIDC is removed at the owner's request. Individual email/password accounts replace the provider integration; worker enrollment, server authorization and strict approvals remain unchanged. Marketing on Ubuntu provides a second physical edge environment. Skills are the sole reusable procedure abstraction; optional LangGraph execution lives inside a skill.

## 1. Starting implementation and the gap (historical baseline)

| Area | Current implementation | Required change |
| --- | --- | --- |
| People | Shared staff/developer bearer tokens; several APIs allow broad resource access | Individual identities and authorization on every resource and action |
| Workers | Shared worker token, assignment filtering, local organization/role checks | Distinct registered workers with server-owned entitlements and assignment-scoped APIs |
| Approvals | Server records decisions and compares executable actions with approved proposals | Authenticate the actual approver; independently validate operation contracts, request authority, target scope, and current policy |
| Execution | Trusted harness calls a local desktop controller under the Windows user | Separate the planner from privileged execution using an OS-enforced boundary |
| Evidence | Worker submits observations, results, and execution state | Distinguish authenticated reports from independently established facts; restrict who can advance authoritative state |
| Learning | Runtime validation and automatic activation; edge-local immutable packages | Protect admission authority and scope distribution, evidence, memory, and package content |
| Deployment | One trusted organization and desktop; local development configuration | Explicit security profiles, revocable credentials, protected transport, and documented isolation limits |

Relevant implementation: [backend routes](../../src/server/eas_server/backend.py), [server action ledger](../../src/server/eas_server/store.py), [worker RPC contract](../../src/shared/eas_shared/protocol.py), [execution layer](../../src/edge-harness/eas_harness/execution.py), [desktop controller](../../src/application-mediator/windows/DesktopAgent/Program.cs), and [skill library](../../src/edge-harness/eas_harness/skill_library.py).

The existing server approval check is real: `begin_action` rejects work without a matching decision. However, the server cannot prevent a compromised Windows account from accessing its already logged-in application directly. Broad worker reporting methods also assume a trusted worker; passing the current tests does not establish containment of a malicious worker client.

## 2. Threat model and limits

Treat browser input, model output, documents, skills, proposed arguments, and worker requests as untrusted input. Knowing an identifier, belonging to the same organization, or being on a private network does not authorize access. This follows [OWASP's requirement to authorize each request at the resource boundary](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html) and [NIST's distinction between network location and resource authorization](https://csrc.nist.gov/pubs/sp/800/207/final).

Test three different compromise scenarios:

1. **Malicious caller or stolen staff credential:** central authorization limits the requests, approvals, and information available to that identity.
2. **Compromised planner or stolen planner credential:** the attacker can reach only assigned context and proposal APIs; cannot directly control the desktop, obtain application credentials, approve actions, or publish admitted skills.
3. **Compromised privileged executor or entire edge host:** assume exposure of that environment's accessible applications, local data, credentials, and retained context. The server must still deny access to other workers' resources and prevent the host from granting organization-wide authority. Reports from that host cannot prove that its local actions were legitimate.

The central authority, password account store, trusted operation implementations, deployment administrators, and the OS/hypervisor enforcing isolation remain trusted components. Compromise of a hypervisor can affect its guest VMs. Signed messages authenticate an origin; they do not make a compromised origin truthful.

For a legacy desktop, an attacker controlling the privileged interactive session can bypass our action broker. This plan limits the consequences of that compromise; it cannot make an application enforce approval semantics it does not support. Where an application API supports its own permissions or transaction approval, retain those protections too.

## 3. Identity and central policy

### People

- Use individual email/password accounts mapped to stable internal principal IDs. Store Argon2id hashes; provision passwords through single-use expiring setup links without a mailer. Authenticate sessions server-side; never accept actor identity or membership from request bodies. Organizational SSO is outside the revised prototype scope.
- Provide a clearly labeled development identity fixture with several distinct users for repeatable tests. Keep it explicit and restricted to development; no silent fallback from failed production authentication to demo credentials.
- Store organization membership and entitlements server-side. Separate rights to request work, approve an operation, read a resource, administer policy, and publish a package. An administrator does not automatically receive all business data.
- An authorized requester can also approve their own operation when policy permits. This plan does not require two humans. Supporting organizational separation-of-duties rules must not imply enabling them for every prototype task.
- Recheck entitlement changes when reading resources, deciding an approval, dispatching work, and resuming a paused operation. Disabling a person stops future access and invalidates their outstanding authority as applicable.

### Workers and services

- Register each worker with a unique identity and revocable credential. The server owns its organization, permitted environment profile, roles/capabilities, and enrollment status. A supplied worker name or self-reported department is a selector, not proof.
- Use separate credentials for the planner, executor, and admission service. No one credential grants proposal, execution, human approval, and release authority together.
- Bind assignments to a particular worker and its lease. A reconnect must authenticate that worker; an unrelated worker cannot resume work by copying an ID.
- Authenticate the server to the edge and protect transport with TLS. Real remote mode must reject known demo secrets, missing identity configuration, and unsupported insecure transport. Browser sessions need `Secure`/`HttpOnly` cookies, CSRF protection, expiry, and logout/revocation handling.
- Keep application credentials out of the frontend, central server, generic machine image, and planner environment. Provision them only to the appropriate execution environment using protected storage. Redaction is supplementary, not credential isolation.

### Policy evaluation

Authorize an explicit tuple: **principal, action, resource, organization, work scope, assigned worker, and current state**. Staff authorization to request a workflow does not require giving staff the worker's application credential. It must explicitly permit that delegated work.

The server derives allowed operations from policy and trusted installed contract metadata. Clients cannot grant permissions by supplying a role, `permissions` array, operation description, tool schema, or approval status. Unknown operations and undeclared fields fail closed. Trusted metadata can reside in shared contracts/server registrations; executable adapters and graph implementations stay on the edge.

Policy is centrally maintained. Deployment configuration establishes the environment's maximum access; per-request decisions can only narrow it. These are different enforcement layers, not independently edited copies of the same action approval. Record configuration revisions and detect drift. Self-reported configuration is not proof that a compromised machine is compliant.

## 4. Resource authorization and the worker protocol

Apply centralized authorization dependencies and resource checks consistently across routes and storage transitions. Inventory every endpoint before migrating it, including list/search, stream/reconnect, artifact download, metrics, knowledge, learning, administrative commands, and compatibility endpoints.

Required properties:

- A staff member sees only authorized requests, conversations, approvals, screenshots, knowledge, skills, and learning evidence. Supervisor views require an explicit entitlement. Filter aggregate counts and search results as well as individual downloads.
- Conversation ownership uses the authenticated person and authorized work scope. Preserve one ongoing conversation per person/scope. Changing scope cannot carry restricted messages into a newly authorized context.
- Worker APIs expose typed commands with specific transition rules. Replace general-purpose remote store updates with the smallest necessary operations. Every command checks the registered identity, assignment, target resource, lease, and allowed fields.
- A planner can submit proposals and request assigned context. An executor can consume execution authority and submit its own receipts. Neither can create human decisions, mutate permissions, rewrite actor identity, invent admitted versions, or modify another worker's request.
- Prevent bypass through alternate tool paths, direct HTTP requests, guessed IDs, stale versions, bulk endpoints, or legacy routes. Authorization errors must not disclose restricted content or its existence unnecessarily.
- Attribute evidence to its producer. Use states such as reported, structurally validated, independently reconciled, and staff accepted where relevant. An authenticated `success` message alone cannot mark a business result independently verified.

Keep existing action history, explicit simulated-run labels, operation identities, deadlines, rejection/cancellation semantics, and uncertain-write states. Do not replace the ledger merely to change the RPC surface.

## 5. Server-authorized execution

The edge planner, graphs, and learner remain on the edge. Only the execution service can reach the desktop controller or privileged application API path.

1. The planner proposes a registered operation for an assigned request.
2. The server validates requester entitlement, worker assignment, operation contract, target scope, and required evidence. Protected runtime evidence capture can prepare the approval only after the request is authorized.
3. The frontend presents trusted operation metadata plus exact proposed arguments and relevant evidence. Natural-language explanation from the model cannot replace the actual operation being approved.
4. An authorized staff decision is recorded with the actual actor, corrected arguments if any, and current policy revision. A parent workflow approval grants no authority to its children.
5. The server issues a short-lived, audience-bound execution grant to the assigned executor. It binds the request, invocation, approver/decision, worker, operation and contract version, normalized arguments, record/company scope, required skill/dependency versions, observation revision, lease epoch, policy revision, expiry, and one-time identifier.
6. The executor authenticates the grant and checks its current validity with the server before starting. It validates fresh local state, consumes the grant durably, performs only the registered operation, and publishes a receipt tied to the same invocation.

Use an established signing implementation and configured server verification keys. A grant is authority for its intended executor, not a transferable browser/planner bearer credential. Signing alone does not provide revocation; online consumption and current assignment/policy checks remain required.

Preserve a stable business idempotency key across retry and grant renewal. Lost acknowledgements, crashes, or expired grants cannot justify repeating an uncertain write. Corrections, stale observations, ownership changes, changed inputs, or incompatible dependencies require fresh validation and approval.

Check authority before each externally consequential step of a composite operation. If the server cannot be reached, stop before the next effect. Cancellation prevents subsequent effects; it cannot undo a save already sent to an application. Document the in-flight race and reconcile uncertain outcomes rather than promising instantaneous distributed revocation.

## 6. OS boundary within the edge application

Perform a bounded Windows feasibility spike before a broad process refactor:

- Identify the privileges needed for the interactive desktop controller and DemoBooks session.
- Run the planner and learner under an isolated account or a suitable OS sandbox that cannot reach the interactive desktop, executor/controller credentials, application files, protected process memory, privileged IPC, or controller network endpoint.
- Run the execution service under the designated application identity with protected code/configuration and authenticated, narrowly scoped IPC. Do not give it permission to administer unrelated applications or modify the central policy.
- Separate planner-writable history/work files from executor state and admitted packages. Protect binary/configuration directories against planner writes so restart cannot become an escalation path.
- Provide narrow brokered context/evidence APIs. Provider secrets should be supplied through a protected model client where practical; any credential the planner retains must have explicitly bounded authority and exposure documented.

An unprivileged service account, another process, or a different working directory is not sufficient evidence by itself. Test access attempts from the planner's actual security context. Account for Windows desktop/session access, process handles, shared directories, loopback services, and network paths.

**Decision point:** if reliable UI automation cannot coexist with the required planner isolation on the existing machine, record the failed boundary and choose a separate isolated execution environment for the affected component. Do not silently run everything as the interactive user and mark isolation complete. The authorization phases can still be delivered independently with an explicit trusted-host limitation.

## 7. Worker environments and scaling

Define centrally managed environment profiles based on data and credential compatibility. Finance is the first example; department names alone are not security classifications.

| Deployment concern | Proposed behavior |
| --- | --- |
| Base software | Reuse a common harness image/build containing no live organization credentials or private lessons |
| Environment access | Provision only assigned application accounts, data locations, network destinations, and model-provider routes |
| Packages | Install generic allowed capabilities and authorized organization-specific packages |
| Capacity | Add uniquely identified workers within the same authorized pool |
| Scheduling | Match authorized requests to eligible workers; maintain an exclusive lease per desktop |
| Reassignment | Drain work, revoke credentials, and remove prior local state before moving a worker across incompatible boundaries |
| Physical resources | Multiple isolated VMs may share a trusted host; dedicated physical hardware is not a default per-staff requirement |

A broadly privileged machine image must not be cloned as a substitute for role-specific provisioning. Installing an application does not itself grant access, but copied credentials, authenticated sessions, caches, backups, and private skills can.

The initial milestone used one Windows worker. The follow-up runs Finance on Windows and Marketing on Ubuntu concurrently, each with a distinct registered identity and exclusive lease. Automatic pool placement and cross-worker context/package replication remain later work.

## 8. Skills, learning, and memory confidentiality

Keep generic bundled examples in `src/edge-harness/skills/`. Organization-specific learned versions remain runtime packages; ordinary learning does not create PRs in the harness repository. A separate skills repository or running skills service is not required.

Maintain a protected package catalog/distribution path in the existing server application. Store approved immutable package bytes or references to access-controlled artifact storage, with scope, hashes, dependencies, provenance, admission status, and deployment records. The server distributes data; it does not execute graphs or learners.

- Authorize metadata, instructions, supporting files, tests, examples, and evidence before delivery to either a staff client or an edge. A hidden catalog entry does not secure a readable file.
- Derive candidate audience restrictions from its source evidence and procedure classification. A learner cannot broaden that audience. Combining evidence cannot relax any source's restriction.
- Automatically admit eligible packages within the existing permitted scope using runtime-owned checks. Retain constrained graph specifications, existing operation allowlists, instruction-only limitations, and no arbitrary generated Python or shell.
- Keep admission and publication credentials separate from ordinary planner/executor credentials. The trusted admission service can remain part of the edge-harness installation with a protected identity. A worker-reported test pass cannot substitute for runtime-owned validation or authorize fleet-wide publication.
- Do not automatically distribute a lesson across security boundaries. Sharing requires an explicitly configured publication/declassification decision by an entitled owner, including its audience and evidence treatment. This is separate from ordinary same-scope automatic activation and does not impose a human code review on every lesson.
- A valid package signature/hash proves origin/integrity, not semantic correctness. Maintain assessment, suspension, rollback, and provenance so a compromised source or later discovered error can quarantine dependent releases.
- Distinguish lifecycle rollback from security revocation. A compatible historical version may remain pinned for ordinary rollback; a revoked permission, compromised source, or explicitly blocked version stops further use even in an existing run.
- Scope session archives, summaries, learner input, caches, screenshots, and provider-bound prompts. Restrict history access after entitlement changes. Start a clean authorized context when restricted material would otherwise carry over; do not rely on asking the model to forget it.
- Define local/server retention and deletion behavior for downloaded context and packages, including worker retirement. Revocation prevents future delivery and use where enforceable; it cannot retract data already copied by a compromised host or sent to a provider. Record that exposure honestly.

Broader sharing of a useful generic lesson may be desirable, but removing record identifiers alone does not establish that the lesson is safe to share. Restricted business procedures are information even without application credentials.

## 9. Implementation phases and acceptance

Each phase produces a reviewable change, relevant tests, an updated setup document, and a validation record. Do not label the entire plan complete when only server-side authorization passes.

| Phase | Deliverable | Acceptance evidence |
| --- | --- | --- |
| A. Policy and identity | Resource/action inventory, central policy evaluator, email/password login, labeled development principals, unique worker enrollment/revocation | Staff and worker identities cannot impersonate one another; unauthorized object access fails through raw HTTP |
| B. Resource and protocol enforcement | Scoped staff views, all endpoint checks, assignment-bound typed worker commands, authoritative state transitions | Malicious worker fixture cannot reach another assignment, create decisions, edit authority, or declare an admitted release |
| C. Grants and migration | Exact-operation grants, current-policy checks, executor consumption and receipts, safe data migration | Altered, replayed, expired, revoked, or wrong-worker grants fail; restart and uncertainty tests retain duplicate-write prevention |
| D. Scoped knowledge and learning | Protected catalog/distribution, evidence classifications, separate admission authority, context revocation | Restricted skills and history never reach unauthorized clients; same-scope automatic learning/reuse still works; fabricated reports cannot directly publish |
| E. Windows privilege separation | Feasibility spike followed by the protected planner/executor deployment if demonstrated | Direct access attempts from the planner account fail against credentials, desktop, application data, protected files/processes, and controller IPC |
| F. Pool deployment | Reproducible scoped environment profiles and, when resources are available, multiple desktops | Worker replicas remain distinct; concurrent work uses separate desktop leases; reassignment does not retain prior credentials or knowledge |

Start the Phase E feasibility spike early, after defining the proposed interfaces in A/B, to avoid designing an execution protocol around an unworkable Windows boundary. Report its result independently; do not defer discovering the isolation constraint until all other work is finished.

**First implementation milestone:** A through D on the existing synthetic setup, plus a documented E feasibility result. This is a server authorization and scoped-learning milestone. Claim OS containment only after E passes, and pool isolation/scaling only after F is separately exercised.

## 10. Required validation scenarios

Use direct API clients and raw privileged-interface attempts as well as frontend tests. A cooperative model refusing to perform an action does not count as proof that the system prevents it.

| Scenario | Required result |
| --- | --- |
| Sales user requests Accounting work or reads its artifacts/history | Server denies access unless explicit policy authorizes that delegated work/resource |
| Authorized requester lacks approval rights | Request can reach an entitled approver; requester cannot impersonate one |
| Staff guesses another person's conversation, approval, artifact, or skill ID | No unauthorized content or decision access through read, stream, search, or aggregate routes |
| Worker claims another organization, pool, role, or assignment | Server derives identity/scope from registration and denies the request |
| Worker submits a fabricated success, approval status, or release result | It cannot manufacture human authority, authoritative verification, or package admission |
| Same operation arrives through graph, direct tool, or compatibility route | Equivalent authorization and Strict approval requirements apply |
| Proposal changes operation label, target, amount, skill, schema, or version after approval | Grant cannot authorize the changed operation |
| Staff/worker credential or permission is revoked during a pause | Further reads/dispatch fail; pending authority is invalidated; context reuse respects the new scope |
| Grant is copied to another worker, replayed, expired, or used with an old lease | Executor/server reject it without a business effect |
| Server disconnects or worker restarts around a save | No blind repeat; reconcile using the original invocation and business identity |
| Two operations compete for one desktop | One exclusive execution owner; no interleaved application effects |
| Private lesson is useful to another department | No automatic cross-boundary delivery, including its title, examples, evidence, and remembered context |
| Same-scope accepted teaching creates a reusable lesson | Runtime validation and automatic activation continue, with individual business approvals on reuse |
| Planner directly calls controller, reads its token, modifies binaries, or reaches the desktop | OS-enforced isolation rejects access in the actual deployment |
| Entire worker host is treated as compromised | Report exposure of its own accessible resources; prove its credentials cannot access other server scopes or mint shared authority |

Most policy/protocol tests use synthetic users and a malicious-worker client on the developer machine. Additional checks run against Windows Finance and Ubuntu Marketing using separate accounts and synthetic applications. These establish the tested access boundaries and concurrent execution; they do not establish pool scheduling, generic Linux GUI automation or a hypervisor security assessment.

Live-model tests are only needed to validate changed agent behavior, such as continued teaching and reuse. Security checks must also work without an LLM. Label simulated staff/model runs explicitly; record actual live runs, failures, and untested configurations separately.

## 11. Migration, rollout, and completion record

- Inventory existing credentials, active work, shared-principal history, skills, and artifacts before migration. Preserve evidence under restricted legacy ownership; do not assign all historical shared-token conversations to the first person who signs in.
- Add schema/protocol versions and reject incompatible combinations. Introduce new identities and read policies before exposing the new UI. Migrate public synthetic fixtures separately from private runtime records.
- Drain or explicitly cancel active legacy work before retiring its credentials/protocol. Preserve uncertain mutations and pending reconciliation. No new identity mapping may silently approve or replay old work.
- Retire shared-token and broad RPC paths after the new integration path passes. A compatibility fallback must not restore broad authority or allow downgraded grants.
- Record rollback and recovery procedures. Rolling back application code cannot automatically re-enable revoked credentials, resurrect grants, or make private historical data broadly readable.
- Update [architecture](../architecture.md), [department boundaries](../departments.md), [developer setup](../developer-setup.md), and README to distinguish implemented phases from planned isolation. Keep an access matrix and phase-by-phase validation record with measured revocation behavior and known gaps.

Full completion requires the relevant acceptance evidence for all phases, not only passing unit tests or a successful Finance demo. If limited resources permit only the first milestone, mark that milestone complete and retain E/F's outstanding status explicitly.

Autonomy optimization, arbitrary generated code execution, new business application integrations, Slack/Discord adapters, a dedicated skills repository, and formal enterprise certification are outside this plan. The existing one-conversation UI, Strict approvals, automatic validated learning, and three-application boundary remain the product baseline.

## 12. Delivery record

A–D now have central individual identity/resource checks, a narrow worker protocol, exact signed grants, protected context and immutable scoped package publication. E progressed from the feasibility spike to an installed three-process harness on the existing Windows VM, with direct access probes under both actual noninteractive accounts. Live-model teaching and reuse still work with separately recorded simulated staff decisions.

F provides explicit environment profiles, unique service enrollment, environment-rebinding rejection, distinct-desktop lease/assignment tests, and concurrent live execution on Windows Finance and Ubuntu Marketing. Both installations have access probes under their actual isolated accounts. Shared context/package replication and automatic fleet placement remain unimplemented; cross-worker package delivery fails closed. Retirement/retention is operator-managed, with no automatic erasure service. Email/password replaces the removed OIDC implementation. These limits are recorded rather than treating the entire original plan as complete.
