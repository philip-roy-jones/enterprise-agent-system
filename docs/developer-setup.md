# Developer machine and Windows worker

The server/frontend runs on the developer machine. The Windows VM or PC runs the edge harness, desktop controller and independent DemoBooks application. The harness has isolated planner, executor and learner processes. Addresses and secrets are local configuration; no particular VPN, hostname or cloud is required.

For architecture, access rules and limitations, see [security](security.md). The optional loopback browser fixture remains at the end of this guide.

## 1. Install and provision the server

```bash
git clone git@github.com:philip-roy-jones/enterprise-agent-system.git
cd enterprise-agent-system
python3 -m venv .venv
source .venv/bin/activate
pip install -c requirements.lock ./src/shared ./src/server
mkdir -p runtime/security
chmod 700 runtime/security
python -m eas_server.admin --registry runtime/security/identities.json init
python -m eas_server.admin --registry runtime/security/identities.json add-human \
  --id developer-staff --name 'Development staff' \
  --grants docs/examples/staff-grants.json \
  --development-token-file runtime/security/staff-token.txt
python -m eas_server.admin --registry runtime/security/identities.json enroll-worker \
  --id finance-desktop-01 --profile docs/examples/finance-environment.json \
  --backend-url https://your-backend-host --output runtime/security/edge
```

Use your own backend URL and stable, unique worker ID. The example gives one person Finance rights including skill lifecycle management; edit the grants deliberately for other people or reviewer access. Each additional person needs their own identity. Each desktop needs its own enrollment, even when two machines run the same profile. On Windows development hosts, use the corresponding virtual-environment executables and restrict the configuration folder with Windows ACLs instead of `chmod`.

Create an ignored backend `.env`:

```dotenv
EAS_DATA_DIR=runtime
EAS_BIND_HOST=127.0.0.1
EAS_BIND_PORT=8000
EAS_PUBLIC_URL=https://your-backend-host
EAS_AUTH_MODE=development
EAS_IDENTITY_FILE=runtime/security/identities.json
EAS_DESKTOP_ADAPTER=windows_accessibility
EAS_MODEL_MODE=live
```

Run `enterprise-server` and publish its loopback listener through an authenticated HTTPS endpoint/reverse proxy you control. The explicit development identity registry works remotely over HTTPS; built-in demo identities require loopback configuration. The server needs no application, desktop controller or model-provider credential.

For OIDC sign-in, register a client at your identity provider with redirect URL `https://your-backend-host/api/auth/callback`. Add people with `--issuer` and `--subject` instead of `--development-token-file`, and set:

```dotenv
EAS_AUTH_MODE=oidc
EAS_OIDC_ISSUER=https://your-identity-provider
EAS_OIDC_AUDIENCE=your-client-id
EAS_OIDC_JWKS_URL=https://your-identity-provider/jwks
EAS_OIDC_AUTHORIZATION_URL=https://your-identity-provider/authorize
EAS_OIDC_TOKEN_URL=https://your-identity-provider/token
EAS_OIDC_CLIENT_SECRET=your-confidential-client-secret
```

Use the exact provider-issued values, not these placeholder paths. The supported ID-token signature algorithm is RS256. The client secret is optional for a public PKCE client. An OIDC failure never enables development fallback. The browser flow is tested against a controlled provider fixture; no real organization IdP is included in the prototype deployment.

## 2. Install the Windows application and controller

Follow [legacy desktop installation](legacy-desktop.md#install), with DemoBooks' application API disabled. Keep its designated Windows session logged in and unlocked. Build requires the .NET 10 SDK; the self-contained executables do not require an SDK to run.

Copy the same source version and the two generated edge configuration files to a protected staging directory on Windows. Do not copy the backend `.env`, identity registry, human tokens or server database. Keep the planner and executor files separate.

Add these model settings to **both** edge files:

```dotenv
EAS_MODEL_MODE=live
EAS_MODEL_PROVIDER=openrouter
EAS_MODEL_ID=openai/gpt-5.6-luna
OPENROUTER_API_KEY=your-private-provider-key
```

Only the **executor** configuration also receives:

```dotenv
EAS_DESKTOP_ADAPTER=windows_accessibility
EAS_DESKTOP_AGENT_URL=http://127.0.0.1:8766
EAS_DESKTOP_AGENT_TOKEN=the-local-controller-token
EAS_DESKTOP_INPUT_MODE=accessibility
```

The controller token is in `%LOCALAPPDATA%\EnterpriseAgentSystem\DesktopAgent\data\bridge.token` under the desktop account. The installer derives a separate learner configuration containing provider settings and no server/controller credentials. Retain the distinct generated worker tokens and the executor's admission token. For offline model fixtures, use `EAS_MODEL_MODE=simulated` consistently and omit provider keys. `mouse_keyboard` selects real clicks and typing instead of accessibility invocation.

## 3. Install the isolated harness

From an elevated PowerShell under the designated desktop account, with every legacy/new worker task drained and stopped:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\src\edge-harness\windows\install-isolated-worker.ps1 `
  -Source (Get-Location).Path `
  -PythonHome 'C:\path\to\Python313' `
  -PlannerConfig 'C:\protected-staging\planner.env' `
  -ExecutorConfig 'C:\protected-staging\executor.env'
```

Supply the directory of a complete trusted Python 3.11+ installation. The installer copies it into `%ProgramData%\EnterpriseAgentSystem\Worker`, installs only harness/contracts dependencies, creates non-admin `eas-planner` and `eas-learner` accounts, applies ACLs and SYSTEM ownership, and registers `EAS-Planner`, `EAS-Executor`, and `EAS-Learner`. The executor uses the designated user's interactive session without elevation. The other two accounts are denied interactive/RDP login. Random OS passwords are stored by Task Scheduler; they are not printed.

Before starting work, run the actual installed-account probes while DemoBooks/controller are running and worker tasks are stopped:

```powershell
powershell -ExecutionPolicy Bypass -File .\src\edge-harness\windows\test-installed-isolation.ps1
powershell -ExecutionPolicy Bypass -File .\src\edge-harness\windows\test-installed-isolation.ps1 `
  -TaskName EAS-Learner -Component learner
Start-ScheduledTask EAS-Learner
Start-ScheduledTask EAS-Executor
Start-ScheduledTask EAS-Planner
```

The probes rotate only the installer-owned account password and restore its original task action. Review the output: Session 0, denied application/configuration/code/process access, no target UI Automation elements, controller status 403. A missing positive control is a failed probe, not evidence of containment. Keep results protected under the relevant component's `runtime` directory. Remove staging configuration copies after provisioning.

Do not run a legacy `EAS-Worker`, `enterprise-harness`, or `enterprise dev` alongside this installation. Exactly one planner/executor pair owns a registered desktop. The backend can schedule distinct registered desktops independently, but shared skill/context replication and physical multi-VM isolation have not been validated.

## 4. Staff use and operations

Open the configured HTTPS frontend. In explicit development mode, sign in with the individual credential written to `staff-token.txt`; in OIDC mode, use the provider sign-in button. The console keeps one conversation per person and work scope. Staff approve each business operation, including graph children. Reading a skill does not authorize running it. Accepting an outcome is separate from approving its actions.

Skill reads require source-evidence access. Lifecycle changes additionally require `manage_skills`. Accepted work can produce an automatically validated lesson on that worker. A private lesson is not automatically shared with every employee or worker. Use Take control/Release control before interacting during active work.

Configuration and state are under `Worker\planner`, `Worker\executor`, and `Worker\learner`. The executor owns persistent context, checkpoints and admitted packages. The backend owns central requests, approvals and artifacts. Keep both sides' state stable across restarts. `EAS_ENV_FILE` selects each component's config; paths should be absolute in installed configurations. Logs contain business evidence and must remain under the same access restrictions as that evidence.

Revoke a person, service or entire worker immediately through the trusted server operator command:

```bash
python -m eas_server.admin --registry runtime/security/identities.json revoke --id finance-desktop-01
```

A registered environment's scope cannot be rebound to a new department while retaining its old runtime. Follow the [retirement/reprovisioning procedure](security.md#revocation-retention-and-recovery). No automatic retention/erasure schedule is enabled.

## Upgrade from the trusted legacy worker

Drain requests and maintenance, resolve uncertain application writes, stop the worker processes, and back up both machines' state. Provision new individual identities; disable the old broad shared-token configuration. Install the isolated harness while keeping legacy runtime data restricted under its original owner.

Before starting the new tasks, run the trusted migration under the desktop operator account:

```powershell
$env:EAS_ENV_FILE = "$env:ProgramData\EnterpriseAgentSystem\Worker\executor\.env"
& "$env:ProgramData\EnterpriseAgentSystem\Worker\venv\Scripts\python.exe" -m eas_harness.migrate `
  --from-root 'C:\path\to\legacy\runtime'
```

Migration preserves the conversation archive and revalidates already-active packages before admitting them with their original evidence. Inspect `executor\runtime\security-migration.json`; quarantined versions must not be treated as deployed. Existing legacy checkpoint formats are not converted into the protected broker format, so drain before migration. Pending historical PRs remain pending. Keep old backups under restricted ownership; do not assign all shared-principal history to the first new person.

For later upgrades, drain and stop all three tasks, stage trusted source/configuration, rerun the installer and revalidate dependency-bound packages before restart. Do not run migrations while the learner/executor can alter their registries. Keep identity policy and revocations when rolling back application code.

## Optional loopback browser fixture

Without Windows, install `pip install -r requirements-dev.txt`, copy `.env.example` to `.env`, keep `EAS_DESKTOP_ADAPTER=browser` and `EAS_MODEL_MODE=simulated`, then run `python -m playwright install chromium` and `enterprise dev`. Open `http://127.0.0.1:8000` and use the explicitly labeled local demo credential. `/mock` is a synthetic accounting test workspace, disabled in Windows mode.

This trusted developer fixture uses integrated edge execution. It tests graphs, approvals and recovery; it does not establish the Windows account boundary. Cross-process security regression tests separately exercise the planner/executor protocol with synthetic identities.
