# Scoped organizational guidance

The backend stores immutable guidance documents separately from execution episodes. Each document has an organization and optional department, role, and company restrictions. A missing optional restriction deliberately shares it more broadly within that organization. A role restriction must name its matching department. Documents never cross organization boundaries.

Authorized staff can add a document with `POST /api/knowledge`. For example, from the backend checkout:

```python
import json
from pathlib import Path
import httpx
from enterprise.config import Settings

settings = Settings()
document = json.loads(Path("examples/finance-knowledge.json").read_text())
response = httpx.post(
    settings.backend_url + "/api/knowledge",
    headers={"Authorization": "Bearer " + settings.staff_token},
    json=document,
)
response.raise_for_status()
print(response.json()["id"])
```

This is an explicit staff action; importing the example is optional. Document IDs, revisions, and scope are retained with results. This prototype provides creation and retrieval, not a full document editing, deletion, or retention interface. Add only synthetic guidance to the demonstration.

The Deep Agent can call `search_knowledge(query)`. Every call requires individual staff approval, even when the selected job mode is Auto. The backend checks that an executing approval covers that exact query before returning content. Search scope comes from the stored job, never from model-supplied organization or department identifiers. Permission checks and scope filtering run before ranking; search returns at most three documents of at most 12,000 characters each. Queries are bounded to 500 characters. An audit event records the query and returned source IDs/revisions, and the tool result preserves the retrieved content as episode evidence.

Document text is reference material. It cannot grant permissions, authorize another company's records, change approval mode, or supply arbitrary code to execute. The agent is instructed to cite document IDs/revisions when using guidance.

## Worker assignment

Configure `EAS_WORKER_ORGANIZATION_ID` and `EAS_WORKER_ROLE_IDS` independently on the backend and edge worker. The defaults authorize organization `acme` and role `invoice_correction`. Additional reviewed roles can be listed as comma-separated IDs. Dispatch only claims jobs inside the backend's configured worker scope; the receiving harness independently validates organization, installed role, department, input consistency, and permitted capabilities before constructing its adapter or graph. A bad route therefore does not automatically become desktop access.

These checks support the prototype's single worker credential and desktop lease. They do not establish employee identity or department membership: the shared staff token remains a workspace-wide prototype credential. Production authorization would need per-person permissions, separately authenticated workers, and application credentials that enforce the same resource boundaries.
