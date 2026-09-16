"""Developer inventory; inspection never grants execution or conversation access."""

import json
from fastapi import HTTPException
from eas_server.security import SCOPE

FLEET_SCOPE = {key: "*" for key in SCOPE}


def install_developer_agents(app, security):
    from eas_server.access import current

    def inventory():
        person = current.get()
        security.authorize(person, "inspect_agents", FLEET_SCOPE)
        security.workforce.sync()
        services = security.registry().principals
        with security.store.db() as db:
            employees = [json.loads(r[0]) for r in db.execute("SELECT data FROM employees ORDER BY id")]
        result = []
        for employee in employees:
            registered = [s for s in services if s.worker_id == employee["id"] and s.kind != "human"]
            executors = [s for s in registered if s.kind == "executor"]
            enabled = any(s.enabled for s in executors)
            result.append(
                {
                    "id": employee["id"],
                    "name": employee["name"],
                    "state": employee["state"],
                    "revision": employee["revision"],
                    "registered": bool(executors),
                    "enabled": enabled,
                    "profiles": employee["profiles"],
                    "services": [{"id": s.id, "kind": s.kind, "enabled": s.enabled} for s in registered],
                    "can_supervise": enabled and security.workforce.permits(person, employee, "supervise"),
                }
            )
        return result

    @app.get("/api/dev/agents")
    def index():
        return inventory()

    @app.get("/api/dev/agents/{employee_id}")
    def show(employee_id: str):
        employee = next((e for e in inventory() if e["id"] == employee_id), None)
        if employee is None:
            raise HTTPException(404, "Agent not found")
        return employee
