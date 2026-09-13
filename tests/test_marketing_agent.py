import json

import httpx
from langgraph.checkpoint.memory import InMemorySaver

from eas_harness.config import Settings
from eas_harness.coordinator import Coordinator
from eas_harness.execution import ExecutionLayer
from eas_harness.integrations.marketing import CampaignAdapter, OPERATIONS
from eas_harness.maintenance import maintain
from eas_shared.types import JobInput


def test_marketing_chat_learns_and_reuses_a_skill_with_child_approvals(store, tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        model_mode="simulated",
        max_model_calls=16,
        worker_role_ids=("campaign_review",),
        campaign_token="synthetic-app-credential",
    )
    adapter = CampaignAdapter(settings, store)
    records = {
        "CAM-2001": dict(
            campaign_id="CAM-2001",
            company_id="ACME",
            title="Synthetic guide",
            impressions=24000,
            clicks=1200,
            spend_cents=36000,
            revision=1,
        ),
        "CAM-2002": dict(
            campaign_id="CAM-2002",
            company_id="ACME",
            title="Synthetic webinar",
            impressions=15000,
            clicks=450,
            spend_cents=22500,
            revision=1,
        ),
    }
    adapter.client.close()
    adapter.client = httpx.Client(
        base_url="http://synthetic-app.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=records[request.url.path.rsplit("/", 1)[-1]])
        ),
    )
    coordinator = Coordinator(
        settings, store, ExecutionLayer(store, adapter, OPERATIONS), InMemorySaver(), InMemorySaver()
    )

    def finish(record, task, inputs=None):
        values = JobInput(
            department_id="marketing",
            role_id="campaign_review",
            task=task,
            conversation_id="marketing-fixture",
            inputs=inputs or {},
        ).model_dump()
        job = store.create_job(values, ongoing=True)
        store.claim("synthetic-marketing-worker")
        decisions = []
        for _ in range(22):
            current = store.get_job(job["id"])
            if current["status"] == "completed":
                assert current["campaign_id"] == record
                return current, decisions
            coordinator.tick(current)
            for approval in store.approvals(job["id"]):
                if approval["status"] == "pending":
                    decisions.append(approval["name"])
                    store.decide(approval["id"], {"decision": "approve"}, actor="simulated-staff")
        raise AssertionError("Marketing request did not finish")

    job, decisions = finish("CAM-2001", "Report campaign metrics for CAM-2001")
    assert decisions == ["select_record", "validate", "establish", "report", "complete"]
    assert job["verified_report"]["click_through_percent"] == 5.0
    assert job["invoice_id"] is None
    store.accept(job["id"])
    scope = {"organization_id": "acme", "role_ids": ["campaign_review"]}

    class RPC:
        def get_job(self, identity):
            return store.get_job(identity)

        def learning_claim(self, worker):
            return store.learning_claim(worker, scope)

        def learning_finish(self, key, claim, result):
            return store.learning_finish(key, claim, result, scope)

        def skills_publish(self, metadata):
            return store.skills_publish(metadata, scope)

    maintain(settings, RPC(), "simulated-admission", coordinator.library)
    maintain(settings, RPC(), "simulated-admission", coordinator.library)
    result = next(q for q in store.learning_status()["queue"] if q["kind"] == "learn")["result"]
    assert result["status"] == "activated"
    spec = coordinator.library.get(result["skill_id"], result["version"], job)
    assert spec["capability_version"] == "marketing-1"
    assert spec["steps"] == ["validate", "establish", "report", "complete"]
    assert "CAM-2001" not in spec["instructions"]
    second, approvals = finish("CAM-2002", spec["task"], {"campaign_id": "CAM-2002"})
    assert approvals == ["read_skill", "run_skill", "validate", "establish", "report", "complete"]
    assert second["verified_report"]["cost_per_click_cents"] == 50.0
    assert list(second["skill_runs"].values())[0]["state"] == "completed"
    adapter.close()


def test_marketing_wire_contract_matches_executor():
    from importlib.resources import files

    assert json.loads(files("eas_shared").joinpath("marketing_operations.json").read_text()) == {
        name: operation.public() for name, operation in OPERATIONS.items()
    }
