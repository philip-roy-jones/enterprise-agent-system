from eas_shared.types import Recovery


class Paused(Exception):
    pass


class RecordUnavailable(Recovery):
    """A scoped visible list lacks a record; not proof of global nonexistence."""

    def __init__(self, invoice_id, observation):
        self.evidence = {
            "invoice_id": invoice_id,
            "company_id": observation.state["company_id"],
            "observation_revision": observation.revision,
            "observed_at": observation.timestamp,
            "screenshot": observation.screenshot,
            "scope": "currently visible invoice list",
            "visible_records": [
                t["target"][5:] for t in observation.targets if t.get("target", "").startswith("open-INV-")
            ],
        }
        super().__init__(
            "record_unavailable",
            f"I couldn't find {invoice_id} in the current invoice list. Please check the invoice number.",
        )


def check_visible_invoice(observation, invoice_id, company_id):
    state = observation.state
    targets = {t.get("target") for t in observation.targets}
    if (
        state.get("company_id") == company_id
        and state.get("view") == "invoices"
        and not state.get("dialog")
        and any(t and t.startswith("open-INV-") for t in targets)
        and "open-" + invoice_id not in targets
    ):
        raise RecordUnavailable(invoice_id, observation)


class MutationRejected(Recovery):
    """An application explicitly rejected this operation without committing it.

    Absence of a saved record, transport errors, and timeouts are not this proof.
    Adapters without an authoritative rejection signal must retain uncertainty.
    """

    def __init__(self, operation_id: str, reason: str):
        self.operation_id = operation_id
        super().__init__("unfamiliar", reason)
