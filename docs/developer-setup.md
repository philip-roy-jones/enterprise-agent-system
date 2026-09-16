# Developer server and edge workers

The server/frontend runs on the developer machine. A Windows VM or PC runs the edge harness, desktop controller and DemoBooks. An Ubuntu worker can run the same harness against Campaign Desk; see [Linux setup](linux-worker.md). The harness has isolated planner, executor and learner processes. Addresses and secrets are local configuration; no particular VPN, hostname or cloud is required.

For architecture, access rules and limitations, see [security](security.md). The optional loopback browser fixture is documented in the README.

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
  --grants docs/examples/developer-grants.json
python -m eas_server.admin --registry runtime/security/identities.json enroll-worker \
  --id finance-desktop-01 --profile docs/examples/finance-environment.json \
  --backend-url https://your-backend-host --output runtime/security/edge
```

Use your own backend URL and stable, unique worker ID. The example gives the developer Finance rights including skill lifecycle management and global agent inventory access. Use `docs/examples/staff-grants.json` for ordinary Finance staff without inventory access; edit the grants deliberately for other people or reviewer access. Each additional person needs their own identity. Each desktop needs its own enrollment, even when two machines run the same profile. On Windows development hosts, use the corresponding virtual-environment executables and restrict the configuration folder with Windows ACLs instead of `chmod`.

Create an ignored backend `.env`:

```dotenv
EAS_DATA_DIR=runtime
EAS_BIND_HOST=127.0.0.1
EAS_BIND_PORT=8000
EAS_PUBLIC_URL=https://your-backend-host
EAS_AUTH_MODE=password
EAS_IDENTITY_FILE=runtime/security/identities.json
EAS_DESKTOP_ADAPTER=windows_accessibility
EAS_MODEL_MODE=live
```

Run `enterprise-server` and publish its loopback listener through an authenticated HTTPS endpoint/reverse proxy you control. The password identity registry works over HTTPS; built-in demo identities are limited to loopback fixtures. The server needs no application, desktop controller or model-provider credential.

Staff use email/password. Issue a one-hour account setup link from the server operator account:

```bash
python -m eas_server.admin --registry runtime/security/identities.json invite-human \
  --id developer-staff --email staff@example.test --data-dir runtime \
  --public-url https://your-backend-host --setup-file runtime/security/developer-setup-link.txt
```

Open the protected file and give its link to the intended person through your trusted development channel. No email is sent. The person chooses a password in the browser, then signs in normally. Use the same command with a new output file to reset a password; completing a reset invalidates existing sessions. Never put passwords in shell arguments or chat. The link's credential is in a URL fragment, which the frontend removes immediately and submits in a bounded JSON request. It cannot be reused after successful setup.

Passwords use Argon2id. Sign-in has persistent account/client throttling, bounded inputs, same-origin checks and HttpOnly sessions with CSRF protection. Remote password login requires HTTPS. The accounts database stores password hashes, not passwords. The registry still owns permissions, and worker service credentials cannot create human browser sessions. The implementation follows the relevant [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) and [setup/reset token guidance](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).

Organizational SSO/OIDC was removed from the prototype at the owner's request. `EAS_AUTH_MODE=development` retains bearer identities for explicitly labeled loopback/protocol fixtures; those credentials are not offered in the staff sign-in form.

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

Do not run a legacy `EAS-Worker`, `enterprise-harness`, or `enterprise dev` alongside this installation. Exactly one planner/executor pair owns a registered desktop. The backend can schedule distinct registered desktops independently, but Windows Finance and Ubuntu Marketing have been exercised concurrently. Shared skill/context replication and automatic fleet placement remain unimplemented.

## 4. Staff use and operations

Private [Discord channels](discord.md) are the primary staff communication surface. The HTTPS frontend is a developer console: sign in with the email/password established through the setup link, then open an agent’s debug page. Private conversations remain scoped to the person and employee; channel conversations retain their shared channel identity. Active employees execute under server authorization, while shadowing employees observe explicit demonstrations. Reading a skill does not authorize running it.

Skill reads require source-evidence access. Lifecycle changes additionally require `manage_skills`. Accepted work can produce an automatically validated lesson on that worker. A private lesson is not automatically shared with every employee or worker. Use Take control/Release control before interacting during active work.

Configuration and state are under `Worker\planner`, `Worker\executor`, and `Worker\learner`. The executor owns persistent context, checkpoints and admitted packages. The backend owns central requests, approvals and artifacts. Keep both sides' state stable across restarts. `EAS_ENV_FILE` selects each component's config; paths should be absolute in installed configurations. Logs contain business evidence and must remain under the same access restrictions as that evidence.

The planner retries failed dispatch polls after connection errors or temporary server/gateway failures, with backoff capped at 30 seconds. Authorization and protocol failures still stop it; business operations are not automatically replayed by this retry loop. On Windows, an unexpected planner exit records only its timestamp and exception type in `planner/runtime/planner-exit.json`, without retaining prompts or credentials. Check `EAS-Planner` in Task Scheduler when requests remain queued: an employee's **Active** state expresses permission to work, not process health.

Revoke a person, service or entire worker immediately through the trusted server operator command:

```bash
python -m eas_server.admin --registry runtime/security/identities.json revoke --id finance-desktop-01
```

A registered environment's scope cannot be rebound to a new department while retaining its old runtime. Follow the [retirement/reprovisioning procedure](security.md#revocation-retention-and-recovery). No automatic retention/erasure schedule is enabled.

## Developer agent pages

`/` lists all registered agents, including paused and disabled employees. `/agents/<employee-id>` is a stable link to an individual agent’s details, scoped conversations, debug events, learning and supervisor controls. `/metrics` shows evaluation results. Directory access requires an explicit human `inspect_agents` grant with all four scope fields set to `"*"`; [developer-grants.json](examples/developer-grants.json) includes it. The permission exposes registration metadata only: it does not authorize reading conversations, controlling desktops, promoting employees or managing skills. Those still use the existing scoped grants. Removed registrations remain visible as unregistered for debugging.

The loopback fixture’s `developer` identity has inventory access by default; its `staff` identity does not. Managed registries require an explicit grant. A registry change invalidates existing browser sessions, so sign in again after changing permissions.

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

Without Windows, install `pip install -r requirements-dev.txt`, copy `.env.example` to `.env`, keep `EAS_DESKTOP_ADAPTER=browser` and `EAS_MODEL_MODE=simulated`, then run `python -m playwright install chromium` and `enterprise dev`. The fixture is loopback-only and retains explicitly labeled bearer identities for automated tests. Staff still sign in with an email and password.

In a second terminal with the same virtual environment and fixture configuration, create a password setup link for its existing synthetic developer identity:

```bash
python - <<'PYTHON'
from pathlib import Path
from urllib.parse import urlencode
from eas_server.admin import private_write
from eas_server.config import Settings
from eas_server.security import Security
from eas_server.store import Store
settings = Settings()
assert settings.auth_mode == "development" and not settings.identity_file, "Fixture setup only"
security = Security(settings, Store(settings.data_dir))
email = "developer@example.test"
token = security.accounts.invite("developer", email)
private_write(
    settings.data_dir / "developer-setup-link.txt",
    settings.public_url.rstrip("/") + "/#" + urlencode({"setup": token, "email": email}) + "\n",
)
print("Open runtime/developer-setup-link.txt to set your fixture password; no email was sent.")
PYTHON
```

Open that protected file's link, set a password and sign in. Delete the consumed link file before issuing a replacement. This setup uses the existing developer identity and leaves the separate staff identity and its conversation history intact. `/mock` is the synthetic browser accounting workspace; it is disabled on the ordinary server/edge installation.

This trusted developer fixture uses integrated edge execution. It tests graphs, approvals and recovery; it does not establish the Windows account boundary. Cross-process security regression tests separately exercise the planner/executor protocol with synthetic identities.

## Employee lifecycle and migration

New and migrated worker registrations appear as digital employees in **shadowing**. The existing executor, planner and admission credentials identify services of that employee; they cannot log in as humans or change lifecycle state. Human supervisors use the existing email/password login. Add `supervise` only to the intended supervisor's grants for the employee's environment; ordinary request access does not confer promotion rights.

Open the employee’s page from the developer directory and start a demonstration by describing the task. The mentor operates **that employee's computer**, using the VM console or remote desktop. Keep that same OS session visible and unlocked. The observer never opens or focuses applications to get a better view. Start/finish are explicit capture controls; pausing the employee also stops capture. The observer may ask questions in chat. Under **Manage employee**, activation requires a supervisor's readiness rationale. Skills and observer notes cannot promote the employee.

Windows uses the protected controller's screenshot endpoint. Linux requires a provisioned X11 session and executor access to its `DISPLAY`/`XAUTHORITY`; a headless worker reports capture unavailable. The browser fixture is explicitly a test viewport. No OS login, application account, permission setting, or remote desktop service is created by this feature.

Upgrade the server, shared contracts and all edge packages together, including the isolated learner's installation. `Pillow` is now a harness dependency for bounded observer images. Stop/drain old worker processes before deployment. Historical unfinished requests are cancelled; their approvals and uncertain-write receipts are retained. Existing employees start in shadowing and require explicit supervisor activation. Changed trusted dependencies require existing learned packages to be requalified with the existing maintenance/migration procedure. Never reclassify previous human approvals as automatic policy decisions.

The legacy database table and some protocol fields retain the name `approvals` for historical compatibility. New records have `authorization.kind=employee_policy`, `decision=null`, and an employee revision; they are not fabricated human approvals. Every actual operation still consumes an exact, short-lived server grant. Pausing revokes subsequent effects but cannot undo an external side effect already committed; an in-flight write must still be reconciled.

Keep server and worker clocks synchronized (Windows Time or an equivalent NTP service). Grants are short-lived. The edge allows two seconds of clock difference during its preliminary signature check; authoritative expiry and one-time consumption remain enforced on the server without grace. A clock failure stops the operation rather than bypassing authorization.

For private team communication, see [Discord setup](discord.md). The optional bridge runs on the server, not inside each employee's VM. Future MCP Apps support is described in the [digital-employee plan](plans/digital-employees.md#future-mcp-apps-direction-not-implemented-in-this-delivery).

## Optional application mediation

The [Application Mediator](application-mediator.md) is a separately installed application with its own service identity, protected credentials, native controller and input ledger. Enroll it for an existing employee, assign office policy, and connect the executor to it. Its central developer inspector shows the last filtered observation. Native controller source and installer now live under `src/application-mediator/windows/`.
