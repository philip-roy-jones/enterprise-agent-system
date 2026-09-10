"""Persistent synthetic accounting application; never posts accounting transactions."""

import time
from .store import canonical
from .types import Stale
import json


def initial_state():
    invoices = [
        dict(id=f"INV-{n}", company_id="ACME", vendor=vendor, po_id=f"PO-{n}", amount=amount, po_amount=po)
        for n, vendor, amount, po in [
            (1042, "Northstar Office Supply", 148000, 128000),
            (1043, "Cedar IT Services", 264000, 240000),
            (1044, "Atlas Packaging", 97500, 90000),
        ]
    ]
    return dict(
        revision=1,
        app_version="mock-1",
        company_id="ACME",
        view="dashboard",
        invoice_id=None,
        dialog=None,
        loading_until=0,
        unsaved=False,
        fields={"amount": "", "note": ""},
        variant="standard",
        reordered=False,
        interrupt_save=False,
        invoices=invoices,
        drafts=[],
        save_requests=0,
    )


class MockAccounting:
    def __init__(self, store):
        self.store = store
        if not store.get_value("mock"):
            store.put_value("mock", initial_state())

    def state(self):
        return self.store.get_value("mock")

    def scenario(self, config):
        with self.store.db() as db:
            lease = json.loads(db.execute("SELECT data FROM lease WHERE id=1").fetchone()[0])
            if lease["job_id"]:
                job = self.store._job(db, lease["job_id"])
                if (
                    job["status"] not in {"completed", "cancelled", "failed", "denied", "rejected"}
                    and lease["owner"] != "staff"
                ):
                    raise Stale("Take staff control before changing an active desktop")
            s = json.loads(db.execute("SELECT data FROM kv WHERE key='mock'").fetchone()[0])
            allowed = {
                "view",
                "invoice_id",
                "dialog",
                "variant",
                "reordered",
                "interrupt_save",
                "company_id",
                "unsaved",
                "delay_seconds",
            }
            if set(config) - allowed:
                raise ValueError("Unknown scenario option")
            if config.get("view", "dashboard") not in {"dashboard", "invoices", "invoice", "purchase_orders"}:
                raise ValueError("Invalid view")
            if config.get("dialog") not in {None, "info", "unfamiliar", "unsaved"}:
                raise ValueError("Invalid dialog")
            if config.get("variant", "standard") not in {"standard", "renamed", "layout"}:
                raise ValueError("Invalid UI variant")
            config = dict(config)
            delay = min(max(float(config.pop("delay_seconds", 0)), 0), 15)
            s.update(config, loading_until=time.time() + delay, revision=s["revision"] + 1)
            db.execute("UPDATE kv SET data=? WHERE key='mock'", (canonical(s),))
            return s

    def action(self, name, args, principal):
        with self.store.db() as db:
            s = json.loads(db.execute("SELECT data FROM kv WHERE key='mock'").fetchone()[0])
            lease = json.loads(db.execute("SELECT data FROM lease WHERE id=1").fetchone()[0])
            job = self.store._job(db, lease["job_id"]) if lease["job_id"] else None
            if principal == "worker":
                if not job or not lease["inflight"]:
                    raise Stale("No authorized operation in flight")
                self.store._check(job, lease, lease["owner"], lease["epoch"])
                required = "draft" if name in {"field", "save"} else "navigate"
                if required not in job["permissions"]:
                    raise PermissionError("Worker permission denied")
            elif (
                job
                and job["status"] not in {"completed", "cancelled", "failed", "denied", "rejected"}
                and lease["owner"] != "staff"
            ):
                raise Stale("Take staff control before interacting with the desktop")
            if s["loading_until"] > time.time():
                raise Stale("Application is loading")
            if s["dialog"] and name != "dialog":
                raise Stale("Dialog requires resolution")
            if name == "navigate":
                if s["unsaved"]:
                    s["dialog"] = "unsaved"
                else:
                    if args["view"] not in {"dashboard", "invoices", "purchase_orders"}:
                        raise ValueError("Unsupported navigation")
                    s.update(view=args["view"], invoice_id=None)
            elif name == "company":
                if args["company_id"] != "ACME":
                    raise PermissionError("Company out of scope")
                s["company_id"] = "ACME"
            elif name == "open":
                if job and principal == "worker" and args["invoice_id"] != job["invoice_id"]:
                    raise PermissionError("Invoice out of scope")
                if not any(i["id"] == args["invoice_id"] for i in s["invoices"]):
                    raise ValueError("Unknown invoice")
                s.update(
                    view="invoice",
                    invoice_id=args["invoice_id"],
                    fields={"amount": "", "note": ""},
                    unsaved=False,
                )
            elif name == "dialog":
                response = args["response"]
                allowed = {"info": {"acknowledge"}, "unfamiliar": {"review"}, "unsaved": {"keep", "discard"}}
                if response not in allowed.get(s["dialog"], set()):
                    raise PermissionError("Response is not applicable to this dialog")
                if response == "discard":
                    s.update(fields={"amount": "", "note": ""}, unsaved=False)
                s["dialog"] = None
            elif name in {"field", "save"}:
                if s["company_id"] != "ACME" or s["view"] != "invoice":
                    raise PermissionError("Wrong company or view")
                if job and principal == "worker" and s["invoice_id"] != job["invoice_id"]:
                    raise PermissionError("Wrong invoice")
                if name == "field":
                    if args["field"] not in {"amount", "note"}:
                        raise ValueError("Unknown field")
                    s["fields"][args["field"]] = str(args["value"])
                    s["unsaved"] = True
                else:
                    operation_id = job["id"] if job else args.get("operation_id")
                    if not operation_id:
                        raise ValueError("Operation ID required")
                    existing = next((d for d in s["drafts"] if d["operation_id"] == operation_id), None)
                    if not existing:
                        from decimal import Decimal, InvalidOperation

                        try:
                            amount = int(Decimal(s["fields"]["amount"]) * 100)
                        except (InvalidOperation, ValueError):
                            raise ValueError("A valid amount is required") from None
                        if amount < 0 or not s["fields"]["note"].strip():
                            raise ValueError("Nonnegative amount and explanation required")
                        if principal == "worker" and (
                            not job["expected"] or amount != job["expected"]["amount"]
                        ):
                            raise PermissionError("Draft differs from verified business result")
                        s["drafts"].append(
                            dict(
                                id=f"DRAFT-{len(s['drafts']) + 1:04}",
                                operation_id=operation_id,
                                company_id=s["company_id"],
                                invoice_id=s["invoice_id"],
                                amount=amount,
                                note=s["fields"]["note"],
                                status="draft",
                            )
                        )
                        s["save_requests"] += 1
                    s["unsaved"] = False
                    if s["interrupt_save"]:
                        s.update(dialog="unfamiliar", interrupt_save=False)
            else:
                raise ValueError("Unknown action")
            s["revision"] += 1
            db.execute("UPDATE kv SET data=? WHERE key='mock'", (canonical(s),))
            return s
