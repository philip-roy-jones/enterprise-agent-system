# Departments and workflow extensions

Enterprise Agent System is a shared platform. Finance is its first example department, not its product boundary. A department can supply one or several worker roles: People Operations onboarding review, IT service requests, Procurement purchase-order checks, and so on. Those additional production workflows are not implemented by this prototype.

`enterprise.roles.WorkerRole` registers the trusted code implementing a workflow:

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

Episode retrieval is bounded and scoped by organization, department, role, task, application version, graph version, company context, and matching recovery situation. It does not share Finance episodes with People Operations merely because both are part of one organization. Shared organizational knowledge currently consists of these selected episode references; a general policy/document knowledge base is deferred.

The prototype has one worker desktop and one trusted organization with simple token roles. Department metadata and retrieval boundaries are implemented, but a production department membership directory, per-user department ACLs, tenant isolation, and multiworker fleet scheduling are not. Adding a department workflow also requires its permission policy and application adapter to be reviewed and tested.

Finance offers two application adapters: the fast browser fixture and the native Windows DemoBooks application. Both use the same role graph and approval machinery. This separation is the example for future department integrations.
