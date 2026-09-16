# Ubuntu Marketing worker

> Current execution policy: [digital employees](plans/digital-employees.md) use shadowing / active / paused. Active work uses server authorization without per-operation staff approval. Historical Strict-policy descriptions below remain as background where noted.

The developer machine hosts the server/frontend. Ubuntu hosts the edge harness's isolated planner, executor and learner, plus **Campaign Desk**, an independent read-only synthetic application. No Finance application, Finance credential or private Finance skill is installed on this worker.

This setup exercises API-based application use. It does not claim Linux desktop-click automation or compatibility with every legacy application.

## Provision the environment

Use Ubuntu with Python 3.11+, `python3-venv`, systemd and administrator access. The tested host runs Ubuntu 24.04, Python 3.12 and systemd 255. Addresses below are placeholders, not a required VPN configuration.

On the server, enroll a new worker with `docs/examples/marketing-environment.json`:

```bash
python -m eas_server.admin --registry runtime/security/identities.json enroll-worker \
  --id marketing-desktop-01 --profile docs/examples/marketing-environment.json \
  --backend-url https://your-backend-host --output runtime/security/marketing-edge
```

Give the intended staff identity explicit Marketing grants. Copy the generated `planner.env` and `executor.env` to a private staging directory on Ubuntu, together with the source checkout and `requirements.lock`. Do not copy the server registry, human credentials or other workers' state.

Each configuration uses its own state directory:

| File | Required component values |
| --- | --- |
| `planner.env` | Generated planner enrollment; `EAS_EXECUTOR_URL=http://127.0.0.1:8767`; `EAS_DATA_DIR=/var/lib/enterprise-agent-system/planner` |
| `executor.env` | Generated executor/admission enrollment; `EAS_DATA_DIR=/var/lib/enterprise-agent-system/executor`; `EAS_CAMPAIGN_URL=http://127.0.0.1:8770`; a private `EAS_CAMPAIGN_TOKEN` |
| `learner.env` | Model settings only; `EAS_DATA_DIR=/var/lib/enterprise-agent-system/learner`; no worker, admission or application credential |
| `application.env` | `CAMPAIGN_DESK_DATA=/var/lib/enterprise-agent-system/application/campaigns.json`; `CAMPAIGN_DESK_TOKEN` matching the executor's application credential |

Generate a random application credential locally and write it only to the executor/application files. Add the following to planner, executor and learner configuration; supply the provider key privately on the edge:

```dotenv
EAS_MODEL_MODE=live
EAS_MODEL_PROVIDER=openrouter
EAS_MODEL_ID=openai/gpt-5.6-luna
EAS_DESKTOP_ADAPTER=campaign_api
EAS_LEARNING_ENABLED=true
```

Both executor and learner also need:

```dotenv
EAS_LEARNER_QUEUE=/var/lib/enterprise-agent-system/learning-ipc
```

Use mode `0600` for the staged files. On Ubuntu, run:

```bash
sudo apt-get install python3-venv
sudo python3 src/edge-harness/linux/install-worker.py \
  --source /absolute/path/to/checkout --config /absolute/path/to/private-config
sudo /opt/enterprise-agent-system/venv/bin/python \
  /opt/enterprise-agent-system/code/edge-harness/linux/test-installed-isolation.py
```

The installer creates four noninteractive users and system services: `eas-planner`, `eas-executor`, `eas-learner`, and `eas-application`. Code and configuration are root-owned; each service can write only its own state and authorized learning IPC. Planner/learner cannot read application data, protected credentials or the executor's process environment, or create listening sockets. The latter uses a seccomp `bind` restriction because the tested systemd build did not enforce `SocketBindDeny` alone. The probes include working credentials and writable own-state controls; a missing test target is not treated as proof of protection.

## Use and maintain it

Sign in as an authorized Marketing person, select the Marketing workspace and ask, “Please report campaign performance for CAM-2001.” Staff approve record selection and each operation. CAM-2001 has 24,000 impressions, 1,200 clicks and $360 spend; the calculated rate is 5% and cost per click is $0.30. CAM-2002 supplies different values for reuse tests; CAM-2003 has no activity and undefined rates, not division-by-zero errors. Campaign Desk does not publish anything or send email.

Accepted evidence can produce a scoped skill with instructions and an optional graph. Runtime admission checks test metrics with different values, zero denominators, changed observations and missing records. Reading or running an admitted skill still requires staff approvals. The server never distributes Finance material into the Marketing environment.

For upgrades, drain requests and maintenance, resolve uncertain effects, stop all four services and back up protected state. Re-run the installer with the same worker's configuration. Requalify installed skills against changed dependencies before restarting the worker. Do not reuse a runtime after changing its security boundary. Remove private staging credentials after installation and rotate credentials if copies remain outside their intended environment.
