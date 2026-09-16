"""Edge preflight tolerates only bounded skew; authoritative expiry stays server-side."""

import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from eas_harness.remote import RemoteStore


@pytest.mark.parametrize("offset,allowed", [(1, True), (10, False), (-60, False)])
def test_grant_clock_preflight(offset, allowed):
    key = Ed25519PrivateKey.generate()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    now = int(time.time())
    payload = dict(
        iss="enterprise-agent-system",
        aud="worker",
        sub="staff",
        iat=now + offset,
        exp=now + offset + 30,
        job_id="job",
        invocation="call",
    )
    token = jwt.encode(payload, key, algorithm="EdDSA")
    begins = []

    def handle(request):
        if request.url.path == "/api/execution/grant":
            return httpx.Response(200, json={"grant": token, "public_key": public, "audience": "worker"})
        begins.append(request)
        return httpx.Response(200, json={"ok": True})

    store = RemoteStore("http://localhost", "fixture")
    store.client.close()
    store.client = httpx.Client(base_url="http://localhost", transport=httpx.MockTransport(handle))
    try:
        if allowed:
            assert store.begin_action("job", "assistant", 1, "call", {}, "authorization")["ok"]
            assert len(begins) == 1
        else:
            with pytest.raises(jwt.InvalidTokenError):
                store.begin_action("job", "assistant", 1, "call", {}, "authorization")
            assert not begins
    finally:
        store.client.close()
