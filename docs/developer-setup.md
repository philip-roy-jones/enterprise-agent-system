# Developer machine and Windows worker

The normal desktop prototype uses two machines:

| Machine | Runs here |
| --- | --- |
| Developer machine | FastAPI backend, staff frontend, jobs, approvals, central evidence, and development/review tools |
| Windows VM or PC | LangGraph worker, Deep Agent harness, local checkpoints, desktop controller, and DemoBooks Desktop |
| Model provider | OpenRouter inference when the Windows worker is configured for live assistance |

The Windows worker makes outbound authenticated requests to the backend. Desktop control stays on Windows over loopback. Staff can open the backend's frontend from another machine. There is no required VPN vendor, fixed hostname, or committed machine address.

## 1. Backend on the developer machine

Clone the repository and install Python 3.11+ dependencies:

```bash
git clone git@github.com:philip-roy-jones/enterprise-agent-system.git
cd enterprise-agent-system
python3 -m venv .venv
source .venv/bin/activate
pip install -c requirements.lock ./src/shared ./src/server
```

On a Windows developer machine, use `.venv\Scripts\python.exe` and `.venv\Scripts\enterprise-server.exe` instead of activating the Linux environment. Chromium installation is only needed for browser fixture tests.

Create an ignored `.env` on the backend:

```dotenv
EAS_DATA_DIR=runtime
EAS_BIND_HOST=127.0.0.1
EAS_BIND_PORT=8000
EAS_DESKTOP_ADAPTER=windows_accessibility
EAS_MODEL_MODE=live
EAS_STAFF_TOKEN=replace-with-private-staff-token
EAS_WORKER_TOKEN=replace-with-private-worker-token
EAS_WORKER_ORGANIZATION_ID=acme
EAS_WORKER_ROLE_IDS=invoice_correction
EAS_DEVELOPER_TOKEN=replace-with-private-developer-token
```

Generate separate random tokens, for example with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. The backend needs neither the OpenRouter key nor the desktop controller token. `EAS_MODEL_MODE` labels jobs; set it consistently on both machines.

Run **`enterprise-server`**. Publish its loopback listener through your own private HTTPS reverse proxy, or configure `EAS_BIND_HOST` for your trusted development network. Use the reachable backend URL in the Windows configuration below. Keep local addresses in `.env`, not source files. This prototype uses bearer tokens; protect remote connections with HTTPS or an encrypted tunnel.

## 2. Application and controller on Windows

Install [DemoBooks and the independent desktop controller](legacy-desktop.md#install), with DemoBooks' application API disabled. Keep the Windows session logged in and unlocked. The application and controller are self-contained .NET executables; building them requires the .NET 10 SDK, running them does not.

Clone or copy the same repository version to Windows. Install Python 3.11+; the native worker does not require a Chromium browser installation. Do not copy the backend's `.env` or runtime directory.

Create a separate ignored `.env` in the Windows checkout:

```dotenv
EAS_BACKEND_URL=https://your-backend-host
EAS_DATA_DIR=runtime
EAS_WORKER_TOKEN=the-same-private-worker-token-as-the-backend
EAS_WORKER_ORGANIZATION_ID=acme
EAS_WORKER_ROLE_IDS=invoice_correction
EAS_DESKTOP_ADAPTER=windows_accessibility
EAS_DESKTOP_AGENT_URL=http://127.0.0.1:8766
EAS_DESKTOP_AGENT_TOKEN=token-from-the-local-desktop-controller
EAS_DESKTOP_INPUT_MODE=accessibility
EAS_MODEL_MODE=live
EAS_MODEL_PROVIDER=openrouter
EAS_MODEL_ID=openai/gpt-5.6-luna
OPENROUTER_API_KEY=your-private-openrouter-key
```

Copy the controller token from `%LOCALAPPDATA%\EnterpriseAgentSystem\DesktopAgent\data\bridge.token`. Set `EAS_DESKTOP_INPUT_MODE=mouse_keyboard` to use actual clicks and typing. For an offline test, set `EAS_MODEL_MODE=simulated` on both machines and omit the OpenRouter key. No staff or developer credentials belong on the Windows worker.

From PowerShell in the Windows checkout:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\src\edge-harness\windows\install-worker.ps1 -Python 'C:\path\to\python.exe'
Start-ScheduledTask EAS-Worker
Get-Content .\runtime\worker.log -Tail 20
```

The installer creates a virtual environment and registers a manual `EAS-Worker` task in the desktop user's session. It installs no recurring schedule. Alternatively, install only the contracts and harness with `python -m pip install -c requirements.lock ./src/shared ./src/edge-harness`, then run `.\.venv\Scripts\enterprise-harness.exe` in that session.

Keep exactly one worker running for this prototype's single desktop lease. **Do not run `enterprise dev` on the backend in this setup:** it starts another worker there. After jobs finish, run `powershell -ExecutionPolicy Bypass -File .\src\edge-harness\windows\stop-worker.ps1` before upgrading its checkout. This stops the task and its Python process tree. Preserve `runtime/worker-checkpoints.sqlite` and `runtime/assistant-checkpoints.sqlite` on Windows across restarts; central job/evidence data stays on the backend.

## 3. Use the staff console

Open your reachable backend URL, sign in using the backend's staff token, and send a request in the conversation. The Deep Agent reads approved skills and invokes durable workflows; Strict is the only policy. Each tool and each child operation needs approval. Accepted, verified work enters bounded skill maintenance on the edge.

Use **Accumulated skills & learning** to inspect the proposed or activated version, instruction diff, operation changes, evidence and independent checks. Guidance-only packages explicitly identify their contract-only validation. Feedback reviews may suggest a missing capability or lifecycle change; these suggestions do not execute work or change the active registry. Suspend or activate an installed version to control future retrieval; active runs retain their pinned version.

For a bounded native DemoBooks evaluation, `enterprise longitudinal-demo NAME --simulate-staff --kind report --invoice INV-1043 --task "Report the discrepancy without saving"` uses the configured backend and developer token. It explicitly simulates approvals, verifies output against native observations before accepting teaching, and preserves both summaries and raw evidence under `runtime/agent-led-evaluation/longitudinal/`. Use `--kind correction` or `guidance` for those outcomes, `--guidance` for teaching, and `--no-learn` for held-out evaluation. Each run needs a new name. This driver is for the synthetic Windows application; it is not a real staff evaluation or a general correctness oracle.

Screenshots and observations come from the Windows worker and are uploaded to the backend. The browser test workspace is disabled in this deployment. To take over, select **Take control**, interact with the real Windows application, and select **Release control**. An old screenshot in the console is evidence of a past observation, not a live remote desktop stream.

## Optional single-machine test fixture

For regression work without Windows, install the full development environment with `pip install -r requirements-dev.txt` from the repository root. Then copy `.env.example` to `.env`, keep `EAS_DESKTOP_ADAPTER=browser` and `EAS_MODEL_MODE=simulated`, install Chromium using `python -m playwright install chromium`, and run `enterprise dev`. This starts a backend and browser worker locally and enables `/mock`, the synthetic browser test workspace. It exercises the same graph, approvals, and recovery infrastructure without validating Windows desktop behavior.

## Upgrading the earlier combined installation

Stop the idle Windows worker before replacing source or its environment. The relocated stop script recognizes all previous launcher paths. Remove or archive the old `.venv`, keeping `.env` and `runtime/` intact, then run the new installer with the system Python executable. It registers the new `src/edge-harness/windows/run-worker.py` launcher and installs only the harness and contracts. Restart with `Start-ScheduledTask EAS-Worker` after confirming the backend is available. The controller and DemoBooks executables do not need reinstalling for a Python package layout change.

On the backend, stop the server and create a fresh virtual environment using the server-only install command above, then start `enterprise-server`. This avoids retaining unused model and desktop dependencies from the earlier combined package. Independent packages have their own `pyproject.toml`; `requirements.lock` supplies version constraints without installing every dependency in that file.

Both applications load configuration from their working directory's `.env`. Set `EAS_ENV_FILE` to an explicit path when starting from another directory. Relative `EAS_DATA_DIR` values are still relative to the process working directory, so keep that directory stable when restarting.
