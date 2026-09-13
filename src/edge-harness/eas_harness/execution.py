"""The sole authority for scripted operations and assistant tool execution."""

from eas_harness.integrations.finance.operations import OPERATIONS
from eas_shared.identity import fingerprint
from eas_harness.errors import Paused, MutationRejected, RecordUnavailable
from eas_shared.types import Observation, Recovery, Stale, Stopped
import time
from threading import RLock
from eas_harness.budget import Deadline, OperationTimeout
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
        from eas_harness.roles import get_role

        record_field = get_role(job["role_id"]).record_field
        selecting = name == "select_record"
        if selecting and (kind != "tool" or not job.get("conversation_request")):
            raise PermissionError("Record selection is only available to conversational requests")
        if job.get("record_id") is None and not selecting:
            raise Recovery(
                "unfamiliar",
                "No record is selected. Clarify the target in chat, then use select_record before application operations.",
            )
        try:
            arguments = operation.input_model.model_validate(arguments).model_dump(exclude_unset=True)
        except ValidationError as error:
            if kind == "tool":
                raise PermissionError(f"Tool arguments are outside the {name} contract") from error
            raise
        bound_inputs = {
            **job.get("inputs", {}),
            **{
                field: job.get(field)
                for field in ("organization_id", "department_id", "role_id", "company_id", "invoice_id")
            },
        }
        if selecting and job.get("record_id") is None:
            bound_inputs.pop(record_field, None)
        for field, value in bound_inputs.items():
            if field in arguments and arguments[field] != value:
                raise PermissionError(f"Operation {field} differs from the authorized job")
        self.adapter.job = job
        if selecting:
            # Selecting scope has no application effects and needs no desktop
            # access. The signed evidence is the current request itself.
            scope = {
                k: job.get(k)
                for k in (
                    "id",
                    "task",
                    "organization_id",
                    "department_id",
                    "role_id",
                    "company_id",
                    "record_id",
                )
            }
            observation = Observation(
                revision=fingerprint(scope),
                timestamp=time.time(),
                screenshot="",
                state={"request_scope": scope},
            )
        else:
            prepare = getattr(self.adapter, "prepare_observation", None)
            if prepare:
                prepare(job_id, owner, lease["epoch"])
            observation = self.adapter.observe()
        self.store.event(job_id, "observation", observation.model_dump())
        judgment = None
        if name == "judge":
            from eas_harness.judgment import disclosure

            if not job.get("expected"):
                raise Recovery("unfamiliar", "Comparison evidence is required before judgment")
            judgment = disclosure(job)
        signature = fingerprint(
            [name, arguments, observation.revision, lease["epoch"]] + ([judgment] if judgment else [])
        )
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
                "record_id": arguments[record_field]
                if selecting
                else job.get("record_id", job.get("invoice_id")),
                record_field: arguments[record_field] if selecting else job.get(record_field),
                "expected": job["expected"],
                "request": job["task"],
                "assistant_report": job.get("assistant_report"),
                **({"judgment": judgment} if judgment else {}),
            },
            application=job.get("application", "Ledger (synthetic)"),
            observation=observation.model_dump(),
            epoch=lease["epoch"],
            operation_spec=operation.public(),
            signature=signature,
        )
        require = True
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
                or approval["signature"] != signature
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
        for field, value in bound_inputs.items():
            if field in arguments and arguments[field] != value:
                raise PermissionError(f"Corrected {field} differs from the authorized job")
        action = dict(name=name, arguments=arguments, observation_revision=observation.revision)
        self.store.begin_action(job_id, owner, lease["epoch"], invocation, action, approval_id)
        # A primitive click/edit is bound to this exact screen. Composite
        # registered operations (also callable as tools) navigate through several
        # expected screens under their declared contract and per-input fences.
        self.adapter.approved_observation = (
            observation if name in {"click", "set_field", "save_draft"} else None
        )
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
            if selecting:
                # The server commits scope and its action receipt atomically.
                receipt = self.store.result(invocation)
                if receipt is None:
                    raise PermissionError("Record selection did not commit its authorized receipt")
                return receipt
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
            if name != "complete" and operation.desktop:
                current = self.store.get_job(job_id)
                if "complete" in current["completed"]:
                    self.store.update_job(
                        job_id, {"completed": [n for n in current["completed"] if n != "complete"]}
                    )
            if name in {"save", "save_draft", "verify"}:
                self.store.update_job(job_id, {"mutation": "confirmed_succeeded"})
            after = observation.model_dump() if selecting else self.adapter.observe().model_dump()
            failures = self.store.get_job(job_id).get("operation_failures", {})
            if name in failures:
                failures.pop(name)
                self.store.update_job(job_id, {"operation_failures": failures})
            result = {"value": result, "after": after}
            self.store.finish_action(job_id, invocation, result, approval_id)
            return result
        except (Recovery, PermissionError, Stale, Stopped) as error:
            if (
                isinstance(error, RecordUnavailable)
                and self.store.get_job(job_id)["mutation"] == "not_attempted"
            ):
                lookup = {"message": error.reason, "evidence": error.evidence, "invocation": invocation}
                self.store.update_job(job_id, {"record_lookup": lookup})
                self.store.event(job_id, "record_unavailable", lookup)
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
