from enterprise.workflows.finance.procedures import resolve_amount_label
import pytest


@pytest.mark.parametrize(
    "labels,expected",
    [
        (["Correction amount", "Correction explanation"], "Correction amount"),
        (["Correction explanation", "Adjusted total"], "Adjusted total"),
        (["Balance due", "Correction explanation"], None),
    ],
)
def test_amount_label_variants(labels, expected):
    assert resolve_amount_label(labels) == expected
