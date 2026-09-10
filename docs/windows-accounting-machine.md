# Native Windows accounting machine

DemoBooks Desktop is a native Windows Forms application built for this prototype. It resembles a traditional accounting package, with a menu bar, company shortcuts, vendor invoices, purchase orders, draft forms, notices, and persistent records. It is not QuickBooks, is not an Intuit product, and does not integrate with real accounting software.

The native application is the source of truth for accounting records. The Linux/backend machine hosts the staff console and worker; the Windows VM owns the visible accounting application. The worker reaches a loopback-only application bridge through an SSH tunnel. The bridge has a separate random token and exposes only synthetic accounting state, scoped controls, screenshots, and deliberate test scenarios.

## Build and install

With the .NET 10 SDK on Linux or Windows:

```bash
dotnet publish windows/DemoBooks/DemoBooks.csproj \
  -c Release -r win-x64 --self-contained true -o windows/publish
```

This produces a Windows x64 application including its runtime. No SDK or Python installation is needed on the Windows machine. Copy `windows/publish` and `windows/install.ps1` into the same folder on the VM, then run the installer from an elevated PowerShell session as the intended desktop user:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The installer places the program under `%LOCALAPPDATA%\EnterpriseAgentSystem\DemoBooks\app`, creates a desktop shortcut, and reserves a **loopback-only** HTTP URL for the current Windows identity. It creates a manual, triggerless `EAS-DemoBooks` task to launch into the existing interactive session. It does not install a recurring schedule. The desktop must be logged in and unlocked.

Accounting state lives in `...\DemoBooks\data\accounting-records.json`, separately from replaceable application binaries. The private bridge token is in `...\DemoBooks\data\bridge.token`. Preserve that directory during upgrades. The application uses a named mutex to prevent a second instance in the same desktop session.

## Connect the worker

Create an SSH tunnel from the backend/worker machine:

```bash
ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 versahn-win@100.66.6.90
```

Set these values in your ignored `.env`, using the token from the VM:

```dotenv
EAS_DESKTOP_ADAPTER=windows
EAS_WINDOWS_BRIDGE_URL=http://127.0.0.1:8765
EAS_WINDOWS_TOKEN=the-private-token-from-the-vm
```

Restart `enterprise dev`. Create a Finance invoice-correction job in the staff console. The **same graph** now uses the native Windows adapter, and its screenshots come from the actual Windows application window. The console's demonstration controls configure that native application's test conditions. The browser accounting page becomes a staff mirror of the same native records.

Use **Take control** before editing in the VM or through the staff mirror, and **Release control** to resume. Automated actions require DemoBooks to be the foreground application. If the session is locked, disconnected without a usable desktop, or the app is covered by another window, restore the desktop and bring DemoBooks forward before approving a fresh proposal. Screen geometry and native state are revalidated against each approved action.

## Adapter and evidence

`WindowsAdapter` implements the reusable operations used by the Finance graph. The native bridge resolves known WinForms controls and invokes their application actions; screenshots are captured from the real screen. This is an application-specific automation API for software we control, not a claim of generic UI Automation or vision-based control of unrelated Windows software.

The bridge refuses unknown accounting operations, wrong scoped invoices, invalid fields, wrong popup responses, stale revisions, and saves that do not match the purchase order. Save uses the job's operation ID as an application-supported idempotency key. Interrupted confirmations and app restarts preserve the persisted draft for reconciliation.

`windows/AccountingSmoke` exercises the shared native accounting model independently of the GUI:

```bash
dotnet run --project windows/AccountingSmoke/AccountingSmoke.csproj -c Release
```

Compilation and accounting-model tests can run on Linux. Native GUI and screenshot validation must run on the actual Windows VM; those results are reported separately from browser tests.
