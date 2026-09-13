import httpx
from eas_shared.types import Stale, Stopped

from eas_shared.protocol import WORKER_METHODS


class RemoteStore:
    def __init__(self, url, token):
        import os
        from urllib.parse import urlsplit

        if os.getenv("EAS_SECURITY_PROFILE") == "managed" and urlsplit(url).scheme != "https":
            raise ValueError("Managed workers require authenticated HTTPS transport")
        self.job_id = None
        self.client = httpx.Client(
            base_url=url, headers={"Authorization": f"Bearer {token}", "X-EAS-Protocol": "2"}, timeout=20
        )

    def __getattr__(self, method):
        if method not in WORKER_METHODS:
            raise AttributeError(method)

        def call(*args, **kwargs):
            body = {"args": args, "kwargs": kwargs}
            if method == "begin_action":
                import jwt

                response = self.client.post("/api/execution/grant", json=body)
                if not response.is_error:
                    grant = response.json()
                    # The authenticated TLS server supplies its verification key. No signing secret on edge.
                    claims = jwt.decode(
                        grant["grant"],
                        grant["public_key"],
                        algorithms=["EdDSA"],
                        audience=grant["audience"],
                        issuer="enterprise-agent-system",
                    )
                    if claims["job_id"] != args[0] or claims["invocation"] != args[3]:
                        raise PermissionError("Grant differs from the requested invocation")
                    body["grant"] = grant["grant"]
                else:
                    self.raise_error(response)
            r = self.client.post(f"/api/worker/{method}", json=body)
            if r.is_error:
                self.raise_error(r)
            result = r.json()
            if method == "claim" and result:
                self.job_id = result["id"]
            return result

        return call

    @staticmethod
    def raise_error(r):
        detail = r.json().get("detail", {})
        if isinstance(detail, dict):
            cls = {"Stale": Stale, "Stopped": Stopped, "PermissionError": PermissionError}.get(
                detail.get("type"), ValueError
            )
            raise cls(detail.get("message", str(detail)))
        raise (PermissionError if r.status_code in {401, 403, 404} else ValueError)(str(detail))

    def artifact(self, png):
        r = self.client.post(
            "/api/worker-artifacts",
            content=png,
            headers={"Content-Type": "image/png", "X-EAS-Job": self.job_id or ""},
        )
        r.raise_for_status()
        return r.json()["id"]

    def identity(self):
        response = self.client.get("/api/worker/identity")
        if response.is_error:
            self.raise_error(response)
        return response.json()
