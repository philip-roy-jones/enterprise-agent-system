"""Read-only synthetic campaign metrics. No real accounts, publishing or mailer."""

import json
import os
from pathlib import Path
import secrets

from fastapi import FastAPI, HTTPException, Request

EXAMPLES = [
    dict(
        campaign_id="CAM-2001",
        company_id="ACME",
        title="Autumn product guide",
        impressions=24000,
        clicks=1200,
        spend_cents=36000,
        revision=1,
    ),
    dict(
        campaign_id="CAM-2002",
        company_id="ACME",
        title="Customer webinar",
        impressions=15000,
        clicks=450,
        spend_cents=22500,
        revision=1,
    ),
    dict(
        campaign_id="CAM-2003",
        company_id="ACME",
        title="Unlaunched winter guide",
        impressions=0,
        clicks=0,
        spend_cents=0,
        revision=1,
    ),
]


def create_app(token, data_file):
    if not token or len(token) < 32:
        raise ValueError("Campaign Desk needs a private application credential")
    app = FastAPI(title="Campaign Desk — synthetic marketing application")
    data_file = Path(data_file)
    if not data_file.exists():
        data_file.parent.mkdir(parents=True, exist_ok=True)
        data_file.write_text(json.dumps(EXAMPLES, indent=2) + "\n")

    @app.get("/health")
    def health():
        return {"status": "ok", "synthetic": True, "read_only": True}

    @app.get("/campaigns/{campaign_id}")
    def campaign(campaign_id: str, request: Request):
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied, "Bearer " + token):
            raise HTTPException(401, "Application authentication required")
        records = json.loads(data_file.read_text())
        record = next((r for r in records if r["campaign_id"] == campaign_id), None)
        if record is None:
            raise HTTPException(404, "Campaign does not exist")
        return record

    return app


def main():
    import uvicorn

    uvicorn.run(
        create_app(os.environ["CAMPAIGN_DESK_TOKEN"], os.environ["CAMPAIGN_DESK_DATA"]),
        host="127.0.0.1",
        port=int(os.getenv("CAMPAIGN_DESK_PORT", "8770")),
    )


if __name__ == "__main__":
    main()
