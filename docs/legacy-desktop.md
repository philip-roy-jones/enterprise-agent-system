# Windows applications without an API

For the current planner/executor/learner account boundary, use the [isolated harness setup](developer-setup.md). The application/controller details below also support the trusted development adapters; launching a combined worker does not establish OS isolation.

The Windows desktop controller is a separate executable from DemoBooks. It observes Windows UI Automation controls, captures the visible application window, invokes accessibility patterns, and supplies real mouse and keyboard input. It does not reference DemoBooks' code, read its data files or process memory, or call its application API.

The execution preference is an authorized application API when available, then accessibility controls, then input grounded in current evidence. The included adapter knows DemoBooks' visible labels and navigation. It supports both accessibility operations and real clicks/typing using current control geometry. Live assistance receives the latest screenshot alongside structured observations. This is not yet a general vision-only driver for arbitrary custom-drawn applications.

## Install

Publish both Windows executables:

```bash
dotnet publish src/test-software/demobooks/DemoBooks/DemoBooks.csproj -c Release -r win-x64 --self-contained true -o src/test-software/demobooks/publish
dotnet publish src/edge-harness/windows/DesktopAgent/DesktopAgent.csproj -c Release -r win-x64 --self-contained true -o src/edge-harness/windows/desktop-publish
```

Copy both published directories and the installers to the Windows machine. In PowerShell, install DemoBooks with its application API disabled and install the independent controller:

```powershell
.\install.ps1 -Source .\publish -DisableApi
.\install-desktop-agent.ps1 -Source .\desktop-publish -TargetProcess DemoBooks
```

Both tasks launch manually in the logged-in user's interactive session. Neither installs a recurring schedule. Stop an existing DemoBooks process before replacing its executable. A normal unlocked desktop is required; secure desktops and applications running at higher integrity levels are unsupported.

Run LangGraph and the Deep Agent harness **on the same Windows machine** as the controller. Follow the [two-machine developer setup](developer-setup.md) to install the Python worker and connect it to the backend. Its desktop controller URL stays `http://127.0.0.1:8766`; no desktop port forwarding is needed.

The private controller token is in `%LOCALAPPDATA%\EnterpriseAgentSystem\DesktopAgent\data\bridge.token`. Configure it only on the Windows worker. Set `EAS_DESKTOP_INPUT_MODE=mouse_keyboard` for actual clicks and typing, or `accessibility` for control patterns. The controller belongs to the automation infrastructure; DemoBooks' application API on port 8765 remains disabled.

## Upgrading a former mediator installation

The Application Mediator experiment has been removed. Existing installations must reconnect the executor to the native controller before resuming work:

1. Wait for active work to finish, stop the planner/executor/learner tasks, and back up configuration and runtime data.
2. Stop and unregister `EAS-ApplicationMediator`. Remove its service principal (`kind: mediator`) from the office identity registry before restarting the upgraded server; keep all other identities and historical evidence. Existing browser sessions may require sign-in again after this registry change.
3. Remove `EAS_MEDIATOR_*` settings from the executor configuration. Set `EAS_DESKTOP_AGENT_URL=http://127.0.0.1:8766` and securely copy the controller token into `EAS_DESKTOP_AGENT_TOKEN`. Keep this credential out of planner and learner configuration.
4. Install the updated shared contracts and harness. With `EAS_ENV_FILE` pointing to the executor configuration, run `python -m eas_harness.migrate --from-root PATH_TO_EXECUTOR_RUNTIME` while the worker is stopped to requalify existing skills against the restored adapter. Preserve chat, checkpoints, and skill history.
5. Archive the retired service's runtime evidence, remove its installation and enrollment credentials, and restart the worker components. The native controller and DemoBooks stay installed. Old filtered screenshots retain their original label in chat history.

## Observation, approvals, and verification

Each action uses a fresh accessibility snapshot, including window identity, visible text, values, and geometry. The controller rejects changed revisions, unavailable controls, and clicks covered by another window. Assistant approvals are revalidated at the desktop boundary. The central execution layer still enforces permissions and exclusive control.

The adapter reads company, invoice, purchase order, amounts, and saved drafts from visible controls. It does not assume a complete record catalog is available on every screen: initial scope validation is followed by navigation and record verification before editing.

Because this path cannot pass an API idempotency key, correction explanations include a unique job reference. Save is permitted only when the visible fields match the verified purchase order and reference. The worker searches displayed saved drafts for that reference and verifies the amount and identity. If a previously attempted Save has no visible matching result, it pauses for reconciliation instead of saving again. The current app shows the last three drafts per invoice; absence outside that visible set is not proof that a save failed.

Use DemoBooks' **Training scenarios** menu to introduce changed labels, layouts, and dialogs. Application scenario endpoints and the browser's manual accounting mirror are unavailable in this mode; staff use the actual Windows desktop after taking control.

Other legacy applications require inspecting their actual controls and defining appropriate business verification. For inaccessible or ambiguous states the worker must stop for supervised investigation; generic blind clicking is not a completion strategy.
