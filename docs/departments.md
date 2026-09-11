# Departments and workflow extensions

Enterprise Agent System is a shared platform. Finance is its first example department, not its product boundary. A department can supply one or several worker roles: People Operations onboarding review, IT service requests, Procurement purchase-order checks, and so on. Those additional production workflows are not implemented by this prototype.

`enterprise.workflows.roles.WorkerRole` registers the trusted code implementing a workflow:

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

The worker resolves the installed workflow and uses its graph, operation registry, and adapter through the shared execution layer. New department workflow modules can call `register_role()` and be explicitly loaded via `EAS_ROLE_MODULES=package.module`. These are reviewed application modules, never import paths supplied by a model or untrusted job.

The console discovers installed workflows from `/api/roles`, groups them by department, and renders their inputs. The Finance demonstration includes a custom invoice selector and interruption controls. Other installed workflows use ordinary form fields derived from their schemas.

Episode retrieval is bounded and scoped by organization, department, role, task, application version, graph version, company context, and matching recovery situation. It does not share Finance episodes with People Operations merely because both are part of one organization. Separate organizational guidance documents are available through an individually approved, scoped search tool. See [organizational knowledge](organizational-knowledge.md).

The prototype has one worker desktop and one trusted organization with simple token roles. Department metadata and retrieval boundaries are implemented, but a production department membership directory, per-user department ACLs, tenant isolation, and multiworker fleet scheduling are not. Adding a department workflow also requires its permission policy and application adapter to be reviewed and tested.

Finance offers two application adapters: the fast browser fixture and the native Windows DemoBooks application. Both use the same role graph and approval machinery. This separation is the example for future department integrations.

## Roles and machine boundaries

A role does not require its own VM. Several explicitly authorized roles can share one worker machine sequentially when their data and credentials belong in the same security boundary. The prototype still permits only one active desktop job; it does not implement a pool of concurrent desktop sessions.

Staff members do not each need a dedicated worker either. Staff identity determines which requests and approvals a person may make; a worker identity determines which applications, credentials, and data an execution environment may access. Several staff members may submit authorized jobs to the same worker queue. A dedicated environment becomes necessary when those access boundaries cannot safely be shared, rather than simply because another employee uses the system. Per-person authorization remains a production requirement, not a capability of the prototype's shared staff token.

Group real environments by access and consequence, not just department names. Sharing all applications under one operating-system user gives that user access outside the harness's intended tool list. An approval dialog and an application-window allowlist are not an OS sandbox. Different confidential or privileged workloads may need separate VMs or other independently enforced isolation, even when the VMs share a physical host.

The backend filters worker assignments, and the receiving worker independently rejects jobs outside its locally configured organization and role allowlist before initializing its graph or adapter. This detects inconsistent or misrouted jobs; it does not prove that a shared-token staff request was authorized by the correct employee. Real deployments also need per-person authorization and scoped target-application credentials. Staff approval authorizes an action within those permissions, not an expansion of them.

These design choices follow [NIST's resource-based authorization guidance](https://csrc.nist.gov/pubs/sp/800/207/final). Windows UI Automation itself is not an isolation boundary between ordinary applications sharing a user's privilege level; see [Microsoft's security overview](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-securityoverview).
