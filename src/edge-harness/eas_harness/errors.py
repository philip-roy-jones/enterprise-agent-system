from eas_shared.types import Recovery


class Paused(Exception):
    pass


class MutationRejected(Recovery):
    """An application explicitly rejected this operation without committing it.

    Absence of a saved record, transport errors, and timeouts are not this proof.
    Adapters without an authoritative rejection signal must retain uncertainty.
    """

    def __init__(self, operation_id: str, reason: str):
        self.operation_id = operation_id
        super().__init__("unfamiliar", reason)
