"""The sole authority for scripted operations and assistant tool execution."""

from enterprise.workflows.finance.operations import OPERATIONS
from enterprise.shared.identity import fingerprint
from enterprise.shared.types import Paused, Recovery, Stale, Stopped, MutationRejected
from threading import RLock
from enterprise.harness.budget import Deadline, OperationTimeout
from pydantic import ValidationError


class ExecutionLayer:
    def __init__(self, store, adapter, operations=None):
        self.store, self.adapter = store, adapter
        self.operations = operations or OPERATIONS
        self._desktop_lock = RLock()

    def run(self, job_id, invocation, name, arguments, execute, kind="node"):
        # Graph checkpoint I/O can use multiple threads, while all observations,
        # approval decisions, adapter state, and desktop effects stay serialized.
        with self._desktop_lock:
            return self._run(job_id, invocation, name, arguments, execute, kind)

    def _run(self, job_id, invocation, name, arguments, execute, kind="node"):
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
        if operation.input_model is None or operation.output_model is None:
            raise PermissionError(f"Operation {name} has no executable input/output contract")
        try:
            arguments = operation.input_model.model_validate(arguments).model_dump(exclude_unset=True)
        except ValidationError as error:
            if kind == "tool":
                raise PermissionError(f"Tool arguments are outside the {name} contract") from error
            raise
        for field in ("company_id", "invoice_id"):
            if field in arguments and arguments[field] != job.get(field):
                raise PermissionError(f"Operation {field} differs from the authorized job")
        self.adapter.job = job
        prepare = getattr(self.adapter, "prepare_observation", None)
        if prepare:
            prepare(job_id, owner, lease["epoch"])
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
                "request": job["task"],
                "assistant_report": job.get("assistant_report"),
            },
            application=job.get("application", "Ledger (synthetic)"),
            observation=observation.model_dump(),
            epoch=lease["epoch"],
            operation_spec=operation.public(),
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
            # Corrected arguments have the same executable schema as model proposals.
            try:
                operation.input_model.model_validate(arguments)
            except ValidationError as error:
                raise PermissionError(f"Corrected arguments are outside the {name} contract") from error
        action = dict(name=name, arguments=arguments, observation_revision=observation.revision)
        self.store.begin_action(job_id, owner, lease["epoch"], invocation, action, approval_id)
        self.adapter.approved_observation = observation if kind == "tool" else None
        deadline = Deadline(operation.timeout_seconds)

        def fence():
            self.store.check(job_id, owner, lease["epoch"])
            deadline.check()

        self.adapter.fence = fence
        self.adapter.deadline = deadline
        try:
            self.adapter.fence()
            if name == "save_draft":
                self.store.update_job(job_id, {"mutation": "attempted_uncertain"})
            result = execute(arguments)
            result = operation.output_model.model_validate(result).model_dump(exclude_unset=True)
            if name in {"save", "save_draft", "verify"}:
                expected = self.store.get_job(job_id)["expected"]
                if (
                    not expected
                    or any(
                        result.get(k) != expected[k] for k in ("company_id", "invoice_id", "amount", "note")
                    )
                    or result.get("operation_id") != job_id
                ):
                    raise Recovery(
                        "ambiguous",
                        "Saved result does not match the assigned record, values and operation ID",
                    )
            self.adapter.fence()
            if name in {"save", "save_draft", "verify"}:
                self.store.update_job(job_id, {"mutation": "confirmed_succeeded"})
            after = self.adapter.observe().model_dump()
            failures = self.store.get_job(job_id).get("operation_failures", {})
            if name in failures:
                failures.pop(name)
                self.store.update_job(job_id, {"operation_failures": failures})
            result = {"value": result, "after": after}
            self.store.finish_action(job_id, invocation, result, approval_id)
            return result
        except (Recovery, PermissionError, Stale, Stopped) as error:
            if isinstance(error, MutationRejected):
                if name not in {"save", "save_draft"} or error.operation_id != job_id:
                    error = Recovery("ambiguous", "Application rejection does not identify this Save")
                else:
                    self.store.update_job(job_id, {"mutation": "confirmed_failed"})
                    self.store.event(
                        job_id,
                        "mutation_failed",
                        {
                            "operation_id": job_id,
                            "invocation": invocation,
                            "reason": str(error),
                            "evidence": "explicit application rejection without commit",
                        },
                    )
            if isinstance(error, OperationTimeout):
                mutation = self.store.get_job(job_id)["mutation"]
                error = Recovery(
                    "ambiguous"
                    if mutation == "attempted_uncertain"
                    else "unfamiliar"
                    if operation.mutation
                    else "temporary",
                    f"{name} exceeded its {operation.timeout_seconds:g}-second action deadline; re-observe before continuing",
                )
            if isinstance(error, Recovery) and error.kind == "temporary":
                failures = self.store.get_job(job_id).get("operation_failures", {})
                failures[name] = failures.get(name, 0) + 1
                self.store.update_job(job_id, {"operation_failures": failures})
                self.store.event(
                    job_id,
                    "operation_retry",
                    {
                        "operation": name,
                        "failures": failures[name],
                        "retry_limit": operation.retry_limit,
                        "requires_fresh_invocation": True,
                    },
                )
                if failures[name] > operation.retry_limit:
                    error = Recovery("unfamiliar", f"{name} exhausted its retry allowance: {error}")
            self.store.finish_action(
                job_id,
                invocation,
                {"error": str(error), "kind": getattr(error, "kind", type(error).__name__)},
                approval_id,
                cache=False,
            )
            raise error
        except Exception as error:
            self.store.finish_action(job_id, invocation, {"error": str(error)}, approval_id, cache=False)
            # Only failures inside an authorized operation become procedure
            # failures. Authority/approval failures above this block cannot route
            # around their restriction through the assistant.
            self.store.event(
                job_id,
                "procedure_failure",
                {
                    "operation": name,
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "invocation": invocation,
                    "mutation": self.store.get_job(job_id)["mutation"],
                },
            )
            raise Recovery(
                "code_failure", f"Procedure {name} failed: {type(error).__name__}: {error}"
            ) from error
        finally:
            self.adapter.approved_observation = None
            self.adapter.deadline = None
            self.adapter.fence = lambda: (_ for _ in ()).throw(PermissionError("No active operation"))
