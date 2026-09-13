"""Marketing role data contracts. No application or harness runtime imports."""

from pydantic import BaseModel, ConfigDict, Field
from eas_shared.roles import RoleDefinition


class CampaignSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    campaign_id: str = Field(pattern=r"^CAM-\d{4}$")


class CampaignInputs(CampaignSelection):
    company_id: str = "ACME"


class CampaignOperation(CampaignInputs):
    reason: str = ""


class CampaignReview(CampaignOperation):
    assistant_report: str = Field(min_length=1, max_length=12000)


class CampaignRecord(CampaignInputs):
    title: str
    impressions: int = Field(ge=0)
    clicks: int = Field(ge=0)
    spend_cents: int = Field(ge=0)
    revision: int = Field(ge=1)


MARKETING_ROLE = RoleDefinition(
    id="campaign_review",
    department_id="marketing",
    department_name="Marketing",
    name="Campaign review",
    application="Campaign Desk (synthetic)",
    input_model=CampaignInputs,
    permissions=("read",),
    record_field="campaign_id",
    stages=("validate", "establish", "report", "complete"),
)
