"""The sole authority for scripted operations and assistant tool execution."""

from .operations import OPERATIONS
from .store import fingerprint
from .types import Paused, Recovery, Stale, Stopped


class ExecutionLayer:
    def __init__(self, store, adapter, operations=None):
        self.store, self.adapter = store, adapter
        self.operations = operations or OPERATIONS

    def run(self, job_id, invocation, name, arguments, execute, kind="node"):
        cached = self.store.result(invocation)
        if cached is not None:
            return cached
        job = self.store.boundary(job_id)
        lease = self.store.lease()
        owner = "assistant" if kind == "tool" else lease["owner"]
        if owner == "staff":
            raise Paused("Staff has desktop control")
        self.store.check(job_id, owner, lease["epoch"])
        operation = self.operations.get(name)
        if not operation or operation.permission not in job["permissions"]:
            raise PermissionError(f"Missing permission for {name}")
        self.adapter.job = job
        observation = self.adapter.observe()
        self.store.event(job_id, "observation", observation.model_dump())
        proposal = dict(
            kind=kind,
            name=name,
            arguments=arguments,
            description=operation.description,
            expected=operation.expected,
            inputs={
                "organization_id": job.get("organization_id", "acme"),
                "department_id": job.get("department_id", "finance"),
                "role_id": job.get("role_id", "invoice_correction"),
                "company_id": job.get("company_id"),
                "record_id": job.get("record_id", job.get("invoice_id")),
                "invoice_id": job.get("invoice_id"),
                "expected": job["expected"],
            },
            application=job.get("application", "Ledger (synthetic)"),
            observation=observation.model_dump(),
            epoch=lease["epoch"],
            operation_spec=operation.__dict__,
            signature=fingerprint([name, arguments, observation.revision, lease["epoch"]]),
        )
        approvals = self.store.approvals(job_id)
        outstanding = next(
            (
                a
                for a in reversed(approvals)
                if a["invocation"] == invocation
                and a["status"] in {"pending", "approved", "corrected", "executing"}
            ),
            None,
        )
        # A pending strict decision is never silently released by a mode change.
        require = kind == "tool" or job["effective_mode"] == "strict" or outstanding is not None
        approval_id = None
        if require:
            approval = self.store.proposal(job_id, invocation, proposal)
            if approval["status"] == "pending":
                raise Paused(approval["id"])
            if approval["status"] == "executing":
                # A crash interrupted this invocation. New authority, fresh state, same business idempotency key.
                self.store.stale_approval(approval["id"])
                raise Paused("Reconcile interrupted invocation")
            if (
                approval["epoch"] != lease["epoch"]
                or approval["observation"]["revision"] != observation.revision
                or approval["signature"]
                != fingerprint([name, arguments, observation.revision, lease["epoch"]])
            ):
                self.store.stale_approval(approval["id"])
                raise Paused("Observation changed; a fresh approval is required")
            approval_id = approval["id"]
            arguments = approval.get("corrected_arguments", arguments)
        action = dict(name=name, arguments=arguments, observation_revision=observation.revision)
        self.store.begin_action(job_id, owner, lease["epoch"], invocation, action, approval_id)
        self.adapter.fence = lambda: self.store.check(job_id, owner, lease["epoch"])
        try:
            self.adapter.fence()
            result = execute(arguments)
            after = self.adapter.observe().model_dump()
            result = {"value": result, "after": after}
            self.store.finish_action(job_id, invocation, result, approval_id)
            return result
        except (Recovery, PermissionError, Stale, Stopped) as error:
            self.store.finish_action(
                job_id,
                invocation,
                {"error": str(error), "kind": getattr(error, "kind", type(error).__name__)},
                approval_id,
                cache=False,
            )
            raise
        except Exception as error:
            self.store.finish_action(job_id, invocation, {"error": str(error)}, approval_id, cache=False)
            raise
        finally:
            self.adapter.fence = lambda: (_ for _ in ()).throw(PermissionError("No active operation"))
