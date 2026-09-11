# Native Windows accounting machine

DemoBooks Desktop is a native Windows Forms application built for this prototype. It resembles a traditional accounting package, with a menu bar, company shortcuts, vendor invoices, purchase orders, draft forms, notices, and persistent records. It is not QuickBooks, is not an Intuit product, and does not integrate with real accounting software.

The native application is the source of truth for accounting records. The developer machine hosts the backend and staff console; the Windows VM runs the worker and visible accounting application. The worker reaches the application bridge over Windows loopback. See the [two-machine setup](developer-setup.md). The bridge has a separate random token and exposes only synthetic accounting state, scoped controls, screenshots, and deliberate test scenarios.

## Build and install

With the .NET 10 SDK on Linux or Windows:

```bash
dotnet publish src/demobooks/DemoBooks/DemoBooks.csproj \
  -c Release -r win-x64 --self-contained true -o src/demobooks/publish
```

This produces a Windows x64 application including its runtime. Running the application needs no SDK. The Python worker running beside it requires Python. Copy `src/demobooks/publish` and `src/demobooks/install.ps1` into the same folder on the VM, then run the installer from an elevated PowerShell session as the intended desktop user:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The installer places the program under `%LOCALAPPDATA%\EnterpriseAgentSystem\DemoBooks\app`, creates a desktop shortcut, and reserves a **loopback-only** HTTP URL for the current Windows identity. It creates a manual, triggerless `EAS-DemoBooks` task to launch into the existing interactive session. It does not install a recurring schedule. The desktop must be logged in and unlocked.

Accounting state lives in `...\DemoBooks\data\accounting-records.json`, separately from replaceable application binaries. The private bridge token is in `...\DemoBooks\data\bridge.token`. Preserve that directory during upgrades. The application uses a named mutex to prevent a second instance in the same desktop session.

## Connect the worker

For the optional application API path, configure the **Windows worker's** ignored `.env` using the token from the same machine:

```dotenv
EAS_DESKTOP_ADAPTER=windows
EAS_WINDOWS_BRIDGE_URL=http://127.0.0.1:8765
EAS_WINDOWS_TOKEN=the-private-token-from-the-vm
```

Restart the idle Windows worker. Create a Finance invoice-correction job in the staff console. The **same graph** now uses the native Windows adapter, and its screenshots come from the actual Windows application window. Introduce test conditions using the native application. The browser test workspace is disabled in Windows deployments.

Use **Take control** before editing in the VM, and **Release control** to resume. Before capturing an approval preview, the worker automatically restores a minimized or covered DemoBooks window while it owns the desktop lease. It first requests normal activation; if Windows declines, it raises its own window and clicks a verified inert header location. This bounded setup does not dismiss dialogs or change accounting records. Staff takeover prevents activation and existing approvals are revalidated after release. A locked session or secure desktop still requires restoring an interactive Windows session. Screen geometry and native state are revalidated against each approved action.

## Adapter and evidence

`WindowsAdapter` implements the reusable operations used by the Finance graph. The native bridge resolves known WinForms controls and invokes their application actions; screenshots are captured from the real screen. This is an application-specific automation API for software we control, not a claim of generic UI Automation or vision-based control of unrelated Windows software.

The bridge refuses unknown accounting operations, wrong scoped invoices, invalid fields, wrong popup responses, stale revisions, and saves that do not match the purchase order. Save uses the job's operation ID as an application-supported idempotency key. Interrupted confirmations and app restarts preserve the persisted draft for reconciliation.

`src/demobooks/AccountingSmoke` exercises the shared native accounting model independently of the GUI:

```bash
dotnet run --project src/demobooks/AccountingSmoke/AccountingSmoke.csproj -c Release
```

Compilation and accounting-model tests can run on Linux. Native GUI and screenshot validation must run on the actual Windows VM; those results are reported separately from browser tests.

## Verified on the Windows VM

The native app was installed and exercised in an interactive Windows session. Strict, Auto, changed-label assistance, and interrupted-save reconciliation all completed. A separate covering window and a minimized app were recovered automatically; the worker left focus alone during staff takeover and recovered after release. The original bridge tests used simulated model and staff decisions. Subsequent live OpenRouter tests and an [independent desktop adapter with the application API disabled](legacy-desktop.md) are recorded separately in [validation](validation.md).
