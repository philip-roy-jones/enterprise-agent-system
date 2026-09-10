"""Versioned selectors: improvements change this library in an isolated checkout."""

GRAPH_VERSION = "v1"
AMOUNT_LABELS = ("Correction amount",)
KNOWN_POPUPS = {"info": "acknowledge"}


def resolve_amount_label(available: list[str]) -> str | None:
    return next((label for label in AMOUNT_LABELS if label in available), None)
