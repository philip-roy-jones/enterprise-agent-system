import httpx
from .types import Stale, Stopped

WORKER_METHODS = {
    "get_job",
    "update_job",
    "event",
    "lease",
    "claim",
    "check",
    "transfer",
    "boundary",
    "proposal",
    "approvals",
    "stale_approval",
    "begin_action",
    "finish_action",
    "result",
    "relevant_episodes",
}


class RemoteStore:
    def __init__(self, url, token):
        self.client = httpx.Client(base_url=url, headers={"Authorization": f"Bearer {token}"}, timeout=20)

    def __getattr__(self, method):
        if method not in WORKER_METHODS:
            raise AttributeError(method)

        def call(*args, **kwargs):
            r = self.client.post(f"/api/worker/{method}", json={"args": args, "kwargs": kwargs})
            if r.is_error:
                detail = r.json().get("detail", {})
                if isinstance(detail, dict):
                    cls = {"Stale": Stale, "Stopped": Stopped, "PermissionError": PermissionError}.get(
                        detail.get("type"), ValueError
                    )
                    raise cls(detail.get("message", str(detail)))
                raise ValueError(str(detail))
            return r.json()

        return call

    def artifact(self, png):
        r = self.client.post("/api/worker-artifacts", content=png, headers={"Content-Type": "image/png"})
        r.raise_for_status()
        return r.json()["id"]
