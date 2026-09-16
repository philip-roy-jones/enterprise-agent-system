# Scoped organizational guidance

> Current execution policy: [digital employees](plans/digital-employees.md) use shadowing / active / paused. Active work uses server authorization without per-operation staff approval. Historical Strict-policy descriptions below remain as background where noted.

The backend stores immutable guidance documents separately from execution episodes. Each document has an organization and optional department, role, and company restrictions. A missing optional restriction deliberately shares it more broadly within that organization. A role restriction must name its matching department. Documents never cross organization boundaries.

Authorized staff can add a document with `POST /api/knowledge`. For example, from the backend checkout:

```python
import json
from pathlib import Path
import httpx
from eas_server.config import Settings

settings = Settings()
document = json.loads(Path("examples/finance-knowledge.json").read_text())
response = httpx.post(
    settings.backend_url + "/api/knowledge",
    headers={"Authorization": "Bearer " + Path("runtime/security/staff-token.txt").read_text().strip()},
    json=document,
)
response.raise_for_status()
print(response.json()["id"])
```

This is an explicit staff action; importing the example is optional. Document IDs, revisions, and scope are retained with results. This prototype provides creation and retrieval, not a full document editing, deletion, or retention interface. Add only synthetic guidance to the demonstration.

The Deep Agent can call `search_knowledge(query)`. Every call requires individual staff approval; Strict is the only execution mode. The backend checks that an executing approval covers that exact query before returning content. Search scope comes from the stored job, never from model-supplied organization or department identifiers. Permission checks and scope filtering run before ranking; search returns at most three documents of at most 12,000 characters each. Queries are bounded to 500 characters. An audit event records the query and returned source IDs/revisions, and the tool result preserves the retrieved content as episode evidence.

Document text is reference material. It cannot grant permissions, authorize another company's records, change approval mode, or supply arbitrary code to execute. The agent is instructed to cite document IDs/revisions when using guidance.

## Worker assignment

Enroll each desktop with an explicit organization/department/role/company profile and distinct planner/executor/admission credentials. The server derives dispatch authority from that registration and the requesting person's current grants. The receiving executor checks its environment binding and exact operation grant. Local role selectors do not grant additional server rights.

Creating guidance requires an explicit `knowledge` grant covering its full audience. Omitting an optional document restriction requires authorization for the corresponding broader scope; a department-scoped writer cannot silently publish organization-wide guidance. Retrieval uses current request authority and an executed exact-query approval. See [security](security.md) for individual identities, protected context, worker enrollment and remaining deployment limits.
