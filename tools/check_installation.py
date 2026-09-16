"""Run with python -I in a clean environment containing just one application."""

import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


def check_server(folder):
    for module in ["eas_harness", "enterprise_dev", "langgraph", "deepagents", "playwright"]:
        assert importlib.util.find_spec(module) is None, module
    from eas_server.config import Settings

    assert not hasattr(Settings(), "desktop_agent_token")
    assert not hasattr(Settings(), "model_id")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(
        os.environ,
        EAS_BIND_HOST="127.0.0.1",
        EAS_BIND_PORT=str(port),
        EAS_DATA_DIR=str(folder / "server"),
        EAS_MODEL_MODE="simulated",
        EAS_DESKTOP_ADAPTER="none",
        EAS_STAFF_TOKEN="isolation-test-staff",
    )
    process = subprocess.Popen(
        [sys.executable, "-I", "-m", "eas_server"],
        cwd=folder,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(base + "/api/health", timeout=1) as response:
                    assert json.load(response)["status"] == "ok"
                break
            except OSError:
                if process.poll() is not None:
                    raise AssertionError(process.stdout.read().decode())
                time.sleep(0.1)
        else:
            raise AssertionError("Standalone server did not become healthy")
        for path in [
            "/",
            "/static/app.js",
            "/static/activity.js",
            "/static/learning.js",
            "/static/employees.js",
            "/static/style.css",
        ]:
            with urllib.request.urlopen(base + path) as response:
                assert response.status == 200 and response.read(), path
        headers = {"Authorization": "Bearer isolation-test-staff", "Content-Type": "application/json"}
        request = urllib.request.Request(base + "/api/roles", headers=headers)
        with urllib.request.urlopen(request) as response:
            assert json.load(response)[0]["id"] == "invoice_correction"
        request = urllib.request.Request(
            base + "/api/employees/development-desktop/state",
            headers={**headers, "Authorization": "Bearer local-developer-demo"},
            data=json.dumps({"state": "active", "reason": "Simulated isolated-installation check"}).encode(),
        )
        with urllib.request.urlopen(request) as response:
            assert json.load(response)["state"] == "active"
        request = urllib.request.Request(
            base + "/api/jobs", headers=headers, data=json.dumps({"invoice_id": "INV-1042"}).encode()
        )
        with urllib.request.urlopen(request) as response:
            assert json.load(response)["record_id"] == "INV-1042"
    finally:
        process.terminate()
        process.communicate(timeout=10)


def check_harness(folder):
    for module in ["eas_server", "enterprise_dev", "playwright"]:
        assert importlib.util.find_spec(module) is None, module
    from eas_harness.config import Settings
    from eas_harness.worker import run_worker

    assert not hasattr(Settings(), "staff_token")
    assert not hasattr(Settings(), "developer_token")
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, self.headers.get("Authorization"), body))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"null")

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        run_worker(
            Settings(
                data_dir=folder / "edge",
                worker_token="isolation-test-worker",
                backend_url=f"http://127.0.0.1:{server.server_port}",
                desktop_adapter="windows_accessibility",
                model_mode="simulated",
            ),
            once=True,
        )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
    assert [r[0] for r in received] == [
        "/api/worker/claim",
        "/api/worker/learning_claim",
        "/api/worker/skills_publish",
    ]
    assert received[0][:2] == ("/api/worker/claim", "Bearer isolation-test-worker")
    assert (folder / "edge/worker-checkpoints.sqlite").is_file()
    assert (folder / "edge/assistant-checkpoints.sqlite").is_file()


def main():
    with tempfile.TemporaryDirectory(prefix="eas-installation-") as directory:
        folder = Path(directory)
        {"server": check_server, "edge-harness": check_harness}[sys.argv[1]](folder)
    print(f"{sys.argv[1]} standalone installation passed")


if __name__ == "__main__":
    main()
