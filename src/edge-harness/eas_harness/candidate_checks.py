"""Runtime-owned behavioral cases for declarative Finance compositions.

Only synthetic records; no desktop, server, credentials, generated Python or model.
"""

from copy import deepcopy
from types import SimpleNamespace
from eas_harness.skill_library import validate_spec
from eas_harness.workflows.finance.runtime import FinanceOperations
from eas_shared.types import Recovery


class FixtureAdapter:
    def __init__(self, job, amount, po_amount, label):
        self.job = job
        self.saved = None
        self.saves = 0
        self.label = label
        self.state = {
            "invoices": [
                {
                    "id": job["invoice_id"],
                    "company_id": job["company_id"],
                    "amount": amount,
                    "po_amount": po_amount,
                    "po_id": "PO-9001",
                }
            ],
            "company_id": job["company_id"],
            "invoice_id": None,
            "dialog": None,
            "fields": {"amount": "", "note": ""},
        }

    def observe(self):
        return SimpleNamespace(
            state=deepcopy(self.state), targets=[{"label": self.label, "target": "amount"}]
        )

    def ensure_company(self, company):
        assert company == self.job["company_id"]
        self.state["company_id"] = company

    def ensure_invoice_open(self, invoice):
        assert invoice == self.job["invoice_id"]
        self.state["invoice_id"] = invoice
        return {"invoice_id": invoice}

    def ensure_editable(self):
        if (
            self.state["dialog"]
            or self.state["invoice_id"] != self.job["invoice_id"]
            or self.state["company_id"] != self.job["company_id"]
        ):
            raise Recovery("unfamiliar", "Fixture state not editable")
        return deepcopy(self.state)

    def correction_note(self, text):
        return text

    def set_field(self, field, value):
        self.ensure_editable()
        self.state["fields"][field] = value

    def save_and_verify(self, expected):
        self.ensure_editable()
        assert self.state["fields"] == {"amount": f"{expected['amount'] / 100:.2f}", "note": expected["note"]}
        self.saves += 1
        self.saved = {**expected, "operation_id": self.job["id"]}
        return self.saved

    def saved_result(self, expected):
        return self.saved


class FixtureStore:
    def __init__(self, job):
        self.job = job

    def get_job(self, _):
        return deepcopy(self.job)

    def update_job(self, _, updates):
        self.job.update(updates)

    def event(self, *args):
        pass


def check_candidate(candidate):
    spec = validate_spec(candidate).model_dump()
    checks = []
    if not spec["steps"]:
        return {
            "suite": "guidance-contract-1",
            "model_mode": "none",
            "behavioral_evaluation": "not performed; guidance use still requires live or simulated evaluation",
            "checks": [
                {"case": "typed scoped guidance without executable code", "passed": True},
                {"case": "bounded supporting text paths and content", "passed": True},
            ],
        }
    for amount, po_amount in [(15327, 12340), (47000, 51000), (9900, 9900)]:
        for label in spec["amount_labels"] or ["Correction amount"]:
            job = dict(
                id="synthetic-admission",
                invoice_id="INV-9001",
                company_id=spec["company_id"],
                permissions=["read", "navigate", "draft"],
                amount_labels=spec["amount_labels"],
                expected=None,
                mutation="not_attempted",
                model_calls=0,
                tokens=0,
            )
            adapter = FixtureAdapter(job, amount, po_amount, label)
            runtime = FinanceOperations()
            runtime.store = FixtureStore(job)
            runtime.layer = SimpleNamespace(adapter=adapter)
            runtime.settings = SimpleNamespace(model_mode="simulated", model_id="", max_model_calls=2)
            runtime.amount_labels = spec["amount_labels"]
            for name in spec["steps"]:
                result = runtime.operation(name, {"job_id": job["id"]})
                if name == "save":
                    runtime.store.update_job(job["id"], {"mutation": "confirmed_succeeded"})
            assert result["verified"]
            if "save" in spec["steps"]:
                assert adapter.saves == 1 and adapter.saved["amount"] == po_amount
            else:
                assert (
                    adapter.saves == 0
                    and runtime.store.job["verified_report"]["difference"] == amount - po_amount
                )
            checks.append({"amount": amount, "po_amount": po_amount, "label": label, "passed": True})
    # Trusted negative checks: stale comparison and wrong starting record cannot produce a report.
    runtime.store.job["verified_report"] = None
    adapter.state["invoices"][0]["amount"] += 1
    try:
        runtime.operation("report", {"job_id": job["id"]})
    except Recovery:
        checks.append({"case": "stale comparison refused", "passed": True})
    else:
        raise ValueError("Stale comparison was accepted")
    adapter.state["invoice_id"] = "INV-9002"
    try:
        runtime.operation("report", {"job_id": job["id"]})
    except Recovery:
        checks.append({"case": "wrong current record refused", "passed": True})
    else:
        raise ValueError("Wrong record was accepted")
    return {"suite": "finance-admission-1", "model_mode": "simulated", "checks": checks}
