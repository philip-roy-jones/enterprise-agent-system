# Windows applications without an API

For the current planner/executor/learner account boundary, use the [isolated harness setup](developer-setup.md). The application/controller details below also support the trusted development adapters; launching a combined worker does not establish OS isolation.

The Windows desktop controller is a separate executable from DemoBooks. It observes Windows UI Automation controls, captures the visible application window, invokes accessibility patterns, and supplies real mouse and keyboard input. It does not reference DemoBooks' code, read its data files or process memory, or call its application API.

The execution preference is an authorized application API when available, then accessibility controls, then input grounded in current evidence. The included adapter knows DemoBooks' visible labels and navigation. It supports both accessibility operations and real clicks/typing using current control geometry. Live assistance receives the latest screenshot alongside structured observations. This is not yet a general vision-only driver for arbitrary custom-drawn applications.

## Install

Publish both Windows executables:

```bash
dotnet publish src/test-software/demobooks/DemoBooks/DemoBooks.csproj -c Release -r win-x64 --self-contained true -o src/test-software/demobooks/publish
dotnet publish src/application-mediator/windows/DesktopAgent/DesktopAgent.csproj -c Release -r win-x64 --self-contained true -o src/application-mediator/windows/desktop-publish
```

Copy both published directories and the installers to the Windows machine. In PowerShell, install DemoBooks with its application API disabled and install the independent controller:

```powershell
.\install.ps1 -Source .\publish -DisableApi
.\install-desktop-agent.ps1 -Source .\desktop-publish -TargetProcess DemoBooks
```

Both tasks launch manually in the logged-in user's interactive session. Neither installs a recurring schedule. Stop an existing DemoBooks process before replacing its executable. A normal unlocked desktop is required; secure desktops and applications running at higher integrity levels are unsupported.

Run LangGraph and the Deep Agent harness **on the same Windows machine** as the controller. Follow the [two-machine developer setup](developer-setup.md) to install the Python worker and connect it to the backend. Its desktop controller URL stays `http://127.0.0.1:8766`; no desktop port forwarding is needed.

The private controller token is in `%LOCALAPPDATA%\EnterpriseAgentSystem\DesktopAgent\data\bridge.token`. Configure it only on the Windows worker. Set `EAS_DESKTOP_INPUT_MODE=mouse_keyboard` for actual clicks and typing, or `accessibility` for control patterns. The controller belongs to the automation infrastructure; DemoBooks' application API on port 8765 remains disabled.

For filtered observations and office-authorized controls, install the separate [Application Mediator](application-mediator.md). The harness then connects to mediator port 8768 and the native token belongs only in mediator configuration. The raw connection described above is an unmediated test setup.

## Observation, approvals, and verification

Each action uses a fresh accessibility snapshot, including window identity, visible text, values, and geometry. The controller rejects changed revisions, unavailable controls, and clicks covered by another window. Assistant approvals are revalidated at the desktop boundary. The central execution layer still enforces permissions and exclusive control.

The adapter reads company, invoice, purchase order, amounts, and saved drafts from visible controls. It does not assume a complete record catalog is available on every screen: initial scope validation is followed by navigation and record verification before editing.

Because this path cannot pass an API idempotency key, correction explanations include a unique job reference. Save is permitted only when the visible fields match the verified purchase order and reference. The worker searches displayed saved drafts for that reference and verifies the amount and identity. If a previously attempted Save has no visible matching result, it pauses for reconciliation instead of saving again. The current app shows the last three drafts per invoice; absence outside that visible set is not proof that a save failed.

Use DemoBooks' **Training scenarios** menu to introduce changed labels, layouts, and dialogs. Application scenario endpoints and the browser's manual accounting mirror are unavailable in this mode; staff use the actual Windows desktop after taking control.

Other legacy applications require inspecting their actual controls and defining appropriate business verification. For inaccessible or ambiguous states the worker must stop for supervised investigation; generic blind clicking is not a completion strategy.
