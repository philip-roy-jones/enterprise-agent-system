# Departments, integrations and skills

Enterprise Agent System supports several departments. The prototype implements Finance against DemoBooks on Windows and Marketing against Campaign Desk's read-only API on Ubuntu. Both applications contain synthetic records.

The Deep Agent is the entry point for every role. It can use individual approved operations or read and invoke a scoped skill. A skill contains instructions and may contain a constrained LangGraph specification; there is no separate deployed `workflows/` directory or graph-first dispatcher.

## Trusted application integrations

`eas_harness.roles.WorkerRole` registers a department's trusted application capabilities:

- Department and role identifiers and staff-facing labels.
- A typed input schema and the field identifying the target record.
- An application adapter, registered operation contracts and an operation handler.
- Permitted capabilities and visible graph stages.

Finance uses `invoice_id`; Marketing uses `campaign_id`. Staff supply the record in ordinary chat. The agent proposes `select_record`, and the runtime binds subsequent operations to the exact approved target. The chat UI selects an authorized work scope; it does not require an invoice form for every message.

Reusable operation implementations live in `eas_harness/integrations/`. Skill specifications refer to those operations; they cannot invent endpoints, import Python or supply executable closures. `SkillRuntime` executes graph children through the same approval, scope, lease, deadline and reconciliation checks used by direct operations. Approving a parent skill does not approve its children.

Custom trusted edge modules register through `eas_harness.roles.register_role()`. The server separately registers data-only `eas_shared.roles.RoleDefinition` metadata through `eas_server.roles.register_role()` and operation contracts through `eas_server.worker_api.register_contracts()`. The schemas and capabilities must agree. Server metadata must not import the harness. These are operator-installed integrations, not model-generated capabilities.

## Learning within a department

Bundled examples live in `src/edge-harness/skills/`. Learned versions live in the protected edge runtime. Accepted evidence can produce instructions and an optional graph using that department's installed operations. Runtime-owned admission tests check provenance, scope, dependencies and supported behavior before automatic activation. Staff still approve reads, invocations and business operations.

The Marketing example learns a campaign-performance skill from an accepted report and reuses it with another campaign's values. Its checks include zero activity, changed observations and missing records. It cannot publish advertising or send email because those capabilities are absent.

Skill metadata, content, supporting evidence and remembered context remain restricted to their authorized source audience. A useful Finance lesson is not automatically delivered to Marketing or to another employee. The server enforces those restrictions before returning material; a hidden UI item is not the access control. See [organizational knowledge](organizational-knowledge.md) and [security](security.md).

## Roles and machine boundaries

A role or staff member does not require its own VM. Several authorized roles may share one worker sequentially when their data and credentials belong in the same security boundary. Several staff can submit authorized requests to that worker's queue. Each desktop permits one active request; separate desktops have independent leases.

The deployed Windows Finance and Ubuntu Marketing workers have distinct service credentials and application environments. Concurrent live requests and account access probes have been exercised on both; see [validation](security-validation.md). Ubuntu uses an application API, not Linux desktop automation. Automatic fleet placement and cross-worker skill/context replication remain unimplemented.

Staff identity limits who may request, approve and read work. The registered worker and its environment limit which applications and credentials may be used. The server rechecks those scopes at assignment and operation time. A model-supplied department or record identifier cannot expand them.

Group real environments by which data and credentials may be shared. Installing all applications under one OS account gives that account access beyond the harness's tool list; an approval dialog is not an OS sandbox. Independently enforced boundaries may be necessary even when VMs share a physical host. See [NIST's resource-based authorization guidance](https://csrc.nist.gov/pubs/sp/800/207/final) and [Microsoft's UI Automation security overview](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-securityoverview).
