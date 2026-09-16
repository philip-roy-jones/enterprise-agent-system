"""Simulated server outages must not strand an idle planner or bypass denials."""

import httpx
import pytest

from eas_harness.config import Settings
from eas_harness.remote import RemoteStore
from eas_harness.worker import run_worker


class EndPolling(BaseException):
    pass


def poller(monkeypatch, tmp_path, handle):
    store = RemoteStore("http://testserver", "simulated-token")
    store.client.close()
    store.client = httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(handle))
    monkeypatch.setattr("eas_harness.worker.RemoteStore", lambda *args: store)
    sleeps = []
    monkeypatch.setattr("eas_harness.worker.time.sleep", sleeps.append)
    settings = Settings(data_dir=tmp_path, executor_url="http://executor-fixture")
    return store, settings, sleeps


@pytest.mark.parametrize("outage", ["connection", "timeout", 408, 429, 500, 502, 503, 504])
def test_poll_recovers_after_outage_with_capped_backoff(monkeypatch, tmp_path, outage):
    requests = []

    def handle(request):
        requests.append(request)
        attempt = len(requests)
        if attempt <= 7 or attempt == 9:
            if outage == "connection":
                raise httpx.ConnectError("Simulated disconnect", request=request)
            if outage == "timeout":
                raise httpx.ReadTimeout("Simulated timeout", request=request)
            return httpx.Response(outage, text="<html>Simulated gateway unavailable</html>")
        if attempt == 8:
            return httpx.Response(200, text="null", headers={"Content-Type": "application/json"})
        raise EndPolling

    store, settings, sleeps = poller(monkeypatch, tmp_path, handle)
    try:
        with pytest.raises(EndPolling):
            run_worker(settings)
        assert sleeps == [1, 2, 4, 8, 16, 30, 30, 0.5, 1]
        assert {r.url.path for r in requests} == {"/api/worker/claim"}
        # A retry retains the same worker identity, including when a claim
        # reached the server but its response was lost.
        assert len({r.content for r in requests}) == 1
    finally:
        store.client.close()


@pytest.mark.parametrize("status", [401, 403, 426])
def test_denial_or_protocol_mismatch_is_not_retried(monkeypatch, tmp_path, status):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, json={"detail": "Simulated rejection"})

    store, settings, sleeps = poller(monkeypatch, tmp_path, handle)
    try:
        with pytest.raises(PermissionError if status in {401, 403} else ValueError):
            run_worker(settings)
        assert len(requests) == 1 and not sleeps
    finally:
        store.client.close()


def test_single_poll_reports_an_outage_to_its_caller(monkeypatch, tmp_path):
    store, settings, sleeps = poller(
        monkeypatch, tmp_path, lambda request: httpx.Response(503, text="Unavailable")
    )
    try:
        with pytest.raises(httpx.HTTPStatusError):
            run_worker(settings, once=True)
        assert not sleeps
    finally:
        store.client.close()


def test_operation_transport_errors_are_never_replayed(monkeypatch, tmp_path):
    attempts = []

    def handle(request):
        attempts.append(request)
        return httpx.Response(503, text="Unavailable")

    store, _, sleeps = poller(monkeypatch, tmp_path, handle)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            store.finish_action("job", "invocation", {})
        assert len(attempts) == 1 and not sleeps
    finally:
        store.client.close()
