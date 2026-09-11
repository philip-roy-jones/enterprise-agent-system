import pytest

from enterprise.accessibility_adapter import AccessibilityAdapter, decode_observation
from enterprise.types import Recovery, Stale, Observation


def visible_invoice(note="", amount="900.00", company="ACME", offset=0):
    def node(name, x=10, y=10, kind="Text", value=None, element=None):
        return dict(
            name=name,
            x=x + offset,
            y=y + offset,
            width=100,
            height=20,
            type=kind,
            value=value,
            element=element or name,
            enabled=True,
            automation_id="",
        )

    return dict(
        revision="current",
        title="DemoBooks",
        foreground=True,
        desktop_session=1,
        elements=[
            node("Vendor invoice INV-1044"),
            node(f"Company: {company}    |    Ready"),
            node("Invoice amount", x=100, y=150),
            node("$975.00", x=100, y=180),
            node("Purchase order PO-1044", x=350, y=150),
            node("$900.00", x=350, y=180),
            node("Adjusted total", kind="Edit", value=amount, element="amount"),
            node("Correction explanation", kind="Edit", value=note, element="note"),
            node("Save correction draft", kind="Button", element="save"),
        ],
    )


@pytest.mark.parametrize("offset", [0, 350])
def test_reads_visible_identity_and_aligned_amounts_without_full_record_catalog(offset):
    state, targets = decode_observation(visible_invoice(offset=offset))
    assert state["invoices"] == [
        dict(id="INV-1044", company_id="ACME", po_id="PO-1044", amount=97500, po_amount=90000)
    ]
    assert not state["record_catalog_complete"]
    assert next(t for t in targets if t["target"] == "amount")["label"] == "Adjusted total"


def adapter_for(raw, job_id="job-one"):
    class Bridge:
        calls = []

        def call(self, path, data=None):
            self.calls.append(path)
            assert path == "/observe", "A mutation was issued unexpectedly"
            return raw

    adapter = object.__new__(AccessibilityAdapter)
    adapter.bridge = Bridge()
    adapter.job = dict(id=job_id, invoice_id="INV-1044", company_id="ACME")
    adapter.fence = lambda: None
    adapter.input_mode = "accessibility"
    return adapter


def test_rejects_changed_observation_and_wrong_company_before_desktop_input():
    adapter = adapter_for(visible_invoice(company="OTHER"))
    with pytest.raises(PermissionError, match="company or invoice"):
        adapter._action("field", {"field": "amount", "value": "900.00"})
    adapter.approved_observation = Observation(revision="old", timestamp=1, screenshot="old.png", state={})
    with pytest.raises(Stale, match="fresh decision"):
        adapter._action("click", {"target": "save"})


def test_reconciles_only_visible_draft_with_matching_job_reference():
    note = "Approved PO correction [EAS:job-one]"
    raw = visible_invoice(note=note)
    raw["elements"].append(dict(raw["elements"][0], name=f"DRAFT-0012    $900.00    Draft    {note}"))
    adapter = adapter_for(raw)
    expected = dict(company_id="ACME", invoice_id="INV-1044", amount=90000, note=note)
    assert adapter.saved_result(expected)["id"] == "DRAFT-0012"
    assert adapter_for(raw, job_id="different-job").saved_result(expected) is None
    with pytest.raises(Recovery, match="differs"):
        adapter.saved_result(dict(expected, amount=91000))


def test_save_rejects_wrong_amount_before_issuing_click():
    note = "Approved PO correction [EAS:job-one]"
    adapter = adapter_for(visible_invoice(note=note, amount="90000"))
    with pytest.raises(PermissionError, match="before Save"):
        adapter.save_and_verify(dict(company_id="ACME", invoice_id="INV-1044", amount=90000, note=note))
    assert all(path == "/observe" for path in adapter.bridge.calls)


def test_uncertain_save_without_visible_result_is_never_repeated():
    adapter = adapter_for(visible_invoice())
    adapter.job["mutation"] = "attempted_uncertain"
    with pytest.raises(Recovery, match="earlier Save"):
        adapter.save_and_verify(dict(company_id="ACME", invoice_id="INV-1044", amount=90000, note="expected"))
    assert adapter.bridge.calls == ["/observe"]
