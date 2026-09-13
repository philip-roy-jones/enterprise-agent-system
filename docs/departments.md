# Departments and workflow extensions

Enterprise Agent System is a shared platform. Finance is its first example department, not its product boundary. A department can supply one or several worker roles: People Operations onboarding review, IT service requests, Procurement purchase-order checks, and so on. Those additional production workflows are not implemented by this prototype.

`eas_harness.workflows.roles.WorkerRole` registers the trusted code implementing a workflow:

- Department and role identifiers and staff-facing labels.
- A Pydantic input schema and the input field identifying the target record.
- Its LangGraph factory, application adapter factory, and named operation contracts.
- Its permitted capabilities and visible workflow stages.

The backend accepts a generic envelope with `organization_id`, `department_id`, `role_id`, `inputs`, and `selected_mode`. The selected workflow validates its own inputs. It is not necessary for another department's job to have an invoice or a purchase order. Original invoice-demo request fields remain a compatibility convenience for the invoice role.

```json
{
  "organization_id": "acme",
  "department_id": "finance",
  "role_id": "invoice_correction",
  "inputs": {"company_id": "ACME", "invoice_id": "INV-1042"},
  "selected_mode": "strict"
}
```

The worker resolves the installed workflow and uses its graph, operation registry, and adapter through the shared execution layer. Install executable workflow modules on the edge and register `WorkerRole` through `eas_harness.workflows.roles.register_role()`. Load them with `EAS_WORKFLOW_MODULES=package.module` (the former `EAS_ROLE_MODULES` remains an edge-only alias). Separately install a server metadata module that registers an `eas_shared.roles.RoleDefinition` through `eas_server.roles.register_role()`, and load it with `EAS_SERVER_ROLE_MODULES=package.module`. For split execution, register public operation metadata with `eas_server.worker_api.register_contracts(role_id, metadata)` and provide the edge role's trusted `operation_handler(store, adapter, job, name, arguments)`. The executor never runs a planner-supplied Python closure. The public input schema and capabilities must agree; the server metadata module must not import harness code. These are reviewed application modules, never import paths supplied by a model or untrusted job.

The console discovers installed workflows from `/api/roles`, groups them by department, and renders their inputs. The Finance demonstration includes a custom invoice selector and interruption controls. Other installed workflows use ordinary form fields derived from their schemas.

Episode retrieval is bounded and scoped by organization, department, role, task, application version, graph version, company context, and matching recovery situation. It does not share Finance episodes with People Operations merely because both are part of one organization. Separate organizational guidance documents are available through an individually approved, scoped search tool. See [organizational knowledge](organizational-knowledge.md).

The deployed prototype has one Windows worker desktop and synthetic Finance records. Individual principal grants authorize organization, department, role, company, action and capability at the server. Other departments are authorization fixtures, not implemented business integrations. A real organizational IdP deployment, physical multi-VM validation and fleet scheduling remain unverified. Adding a department workflow also requires its permission policy and application adapter to be reviewed and tested.

Finance offers two application adapters: the fast browser fixture and the native Windows DemoBooks application. Both use the same role graph and approval machinery. This separation is the example for future department integrations.

## Roles and machine boundaries

A role does not require its own VM. Several explicitly authorized roles can share one worker machine sequentially when their data and credentials belong in the same security boundary. Each registered desktop permits one active request. Distinct-worker identities and concurrent leases are tested with protocol fixtures; automatic fleet placement and skill/context replication are not implemented.

Staff members do not each need a dedicated worker either. Staff identity determines which requests and approvals a person may make; a worker identity determines which applications, credentials, and data an execution environment may access. Several staff members may submit authorized jobs to the same worker queue. A dedicated environment becomes necessary when those access boundaries cannot safely be shared, rather than simply because another employee uses the system. Per-person authorization is enforced through the server registry; the deployed development identity is explicitly labeled.

Group real environments by access and consequence, not just department names. Sharing all applications under one operating-system user gives that user access outside the harness's intended tool list. An approval dialog and an application-window allowlist are not an OS sandbox. Different confidential or privileged workloads may need separate VMs or other independently enforced isolation, even when the VMs share a physical host.

The backend derives worker scope from its registered service identity and rechecks the requesting person before assigning work. The executor checks the current assignment, environment fingerprint and exact operation grant. Model-supplied department labels cannot authorize a route. Application credentials and environment configuration still impose the outer boundary; staff approval does not expand it. Private learned packages remain restricted to their source evidence audience and registered worker. See [security](security.md) for enrollment, revocation and clean reprovisioning.

These design choices follow [NIST's resource-based authorization guidance](https://csrc.nist.gov/pubs/sp/800/207/final). Windows UI Automation itself is not an isolation boundary between ordinary applications sharing a user's privilege level; see [Microsoft's security overview](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-securityoverview).
