"""Versioned selectors: improvements change this library in an isolated checkout."""

GRAPH_VERSION = "v2"
AMOUNT_LABELS = ("Correction amount", "Adjusted total")
KNOWN_POPUPS = {"info": "acknowledge"}


def matches_invoice_procedure(request: str) -> bool:
    # Conservative matching: uncertainty enters supervised discovery. Never
    # coerce a request with extra conditions into a more permissive procedure.
    return request.strip().lower().rstrip(".") in {
        "invoice_correction",
        "correct this invoice",
        "prepare an invoice correction draft",
    }


def resolve_amount_label(available: list[str]) -> str | None:
    return next((label for label in AMOUNT_LABELS if label in available), None)
