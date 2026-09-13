"""Reusable trusted Finance operations, independent of graph orchestration."""

from eas_shared.types import Recovery
from eas_harness.errors import RecordUnavailable


class FinanceOperations:
    def operation(self, name, state):
        job = self.store.get_job(state["job_id"])
        adapter = self.layer.adapter
        adapter.job = job
        if name == "validate":
            if not {"read", "navigate"}.issubset(job["permissions"]):
                raise PermissionError("Invoice inspection requires read and navigate permissions")
            obs = adapter.observe()
            if obs.state.get("record_catalog_complete", True) and not any(
                i["id"] == job["invoice_id"] and i["company_id"] == job["company_id"]
                for i in obs.state["invoices"]
            ):
                raise RecordUnavailable(job["invoice_id"], obs)
            return {"validated": True}
        if name == "establish":
            adapter.ensure_company(job["company_id"])
            return adapter.ensure_invoice_open(job["invoice_id"])
        if name == "compare":
            s = adapter.ensure_editable()
            inv = next(i for i in s["invoices"] if i["id"] == job["invoice_id"])
            expected = {
                "company_id": job["company_id"],
                "invoice_id": job["invoice_id"],
                "amount": inv["po_amount"],
                "po_id": inv["po_id"],
                "difference": inv["amount"] - inv["po_amount"],
                "note": adapter.correction_note(
                    f"Align correction draft with approved purchase order {inv['po_id']}."
                ),
            }
            self.store.update_job(job["id"], {"expected": expected})
            return expected
        if name in {"prepare", "save"} and job["mutation"] not in {
            "attempted_uncertain",
            "confirmed_succeeded",
        }:
            current = adapter.ensure_editable()
            inv = next(i for i in current["invoices"] if i["id"] == job["invoice_id"])
            expected = job["expected"]
            if (
                not expected
                or expected["amount"] != inv["po_amount"]
                or expected["difference"] != inv["amount"] - inv["po_amount"]
                or expected["po_id"] != inv["po_id"]
            ):
                raise Recovery("unfamiliar", "Comparison evidence changed before draft operation")
        if name == "prepare":
            current = adapter.ensure_editable()
            if not job["expected"]:
                raise Recovery("unfamiliar", "Comparison is required before preparing a draft")
            if current["fields"] == {
                "amount": f"{job['expected']['amount'] / 100:.2f}",
                "note": job["expected"]["note"],
            }:
                return {"prepared": True}
            labels = [t["label"] for t in adapter.observe().targets]
            if not any(label in labels for label in getattr(self, "amount_labels", job["amount_labels"])):
                raise Recovery("unfamiliar", "The correction amount field label changed")
            adapter.set_field("amount", f"{job['expected']['amount'] / 100:.2f}")
            adapter.set_field("note", job["expected"]["note"])
            return {"prepared": True}
        if name == "save":
            if job["mutation"] in {"attempted_uncertain", "confirmed_succeeded"}:
                saved = adapter.saved_result(job["expected"])
                if saved:
                    return saved
                raise Recovery("ambiguous", "Uncertain prior Save requires reconciliation, not another write")
            self.store.update_job(job["id"], {"mutation": "attempted_uncertain"})
            result = adapter.save_and_verify(job["expected"])
            return result
        if name == "verify":
            result = adapter.saved_result(job["expected"])
            if not result:
                raise Recovery("ambiguous", "Saved correction is not visible; reconciliation required")
            return result
        if name == "recover":
            if "info" in state["reason"]:
                adapter.click_target("dialog-acknowledge")
            else:
                adapter.ready()
            return {"recovered": True}
        if name == "assist":
            return {"supervised_assistance_authorized": True}
        if name == "resume":
            obs = adapter.observe()
            if job["expected"]:
                saved = adapter.saved_result(job["expected"])
                if saved:
                    self.store.update_job(job["id"], {"mutation": "confirmed_succeeded"})
                    return {"next_node": "verify", "reconciled": saved}
                if job["mutation"] == "attempted_uncertain":
                    raise Recovery(
                        "unfamiliar", "Uncertain save has no verified result; staff must reconcile"
                    )
                if job["mutation"] == "confirmed_failed":
                    raise Recovery(
                        "unfamiliar",
                        "Application rejected Save; retry requires an individually approved save_draft tool call",
                    )
                fields = obs.state["fields"]
                if (
                    obs.state["company_id"] == job["company_id"]
                    and obs.state["invoice_id"] == job["invoice_id"]
                    and not obs.state["dialog"]
                    and fields["amount"] == f"{job['expected']['amount'] / 100:.2f}"
                    and fields["note"] == job["expected"]["note"]
                ):
                    return {"next_node": "save", "prepared_by_assistance": True}
            if obs.state["dialog"]:
                raise Recovery("unfamiliar", "Dialog still requires supervised resolution")
            return {"next_node": "establish"}
        if name == "judge":
            from eas_harness.judgment import judge

            if not job["expected"]:
                raise Recovery("unfamiliar", "Comparison evidence is required")
            return judge(self.settings, self.store, job, job["expected"])
        if name == "report":
            current = adapter.ensure_editable()
            inv = next(i for i in current["invoices"] if i["id"] == job["invoice_id"])
            expected = job["expected"]
            if (
                not expected
                or expected["difference"] != inv["amount"] - inv["po_amount"]
                or expected["amount"] != inv["po_amount"]
            ):
                raise Recovery("unfamiliar", "Comparison evidence has changed")
            report = {
                "invoice_id": job["invoice_id"],
                "po_id": inv["po_id"],
                "invoice_amount": inv["amount"],
                "purchase_order_amount": inv["po_amount"],
                "difference": expected["difference"],
            }
            self.store.update_job(job["id"], {"verified_report": report})
            return {"data": report}
        if name == "complete":
            if job["mutation"] != "confirmed_succeeded" and not job.get("verified_report"):
                raise Recovery("ambiguous", "Completion requires a verified saved result")
            if job["mutation"] == "confirmed_succeeded":
                if not adapter.saved_result(job["expected"]):
                    raise Recovery("ambiguous", "Previously saved result is no longer verified")
            else:
                previous = job["verified_report"]
                current = self.operation("report", state)["data"]
                if current != previous:
                    raise Recovery("unfamiliar", "Report changed before completion")
            return {"verified": True, "acceptance_required": True}
        if name == "review_discovery":
            # Staff reviews free-form outcomes explicitly.
            if not job.get("assistant_report"):
                raise Recovery("unfamiliar", "The assistant has not supplied an outcome to review")
            return {"staff_verified_outcome": job["assistant_report"], "acceptance_required": True}
        raise ValueError(name)
