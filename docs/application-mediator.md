# Application Mediator

The mediator is a **separate application**, installed from `src/application-mediator`, with its own Python environment, local credential, office service identity, and durable input ledger. It has no model, skill learner, or dependency on the harness/server packages. The native Windows desktop controller belongs to this application. DemoBooks remains an independent test application with its application API disabled.

```text
Office                         Agent's Windows environment
  policy and action ledger ←→ Application Mediator ←→ Desktop controller ←→ DemoBooks
  central debug view                ↑
                                 Edge harness
```

The office still owns the existing request/operation authorization and central evidence. This delivery does not relocate conversations or implement a new messaging architecture.

## What the first profile does

`demobooks-v1` recognizes DemoBooks controls by accessibility identity **and** label/type, attaches human-readable descriptions, and renders a filtered accessibility view at their observed positions. Moving/resizing the window changes its revision and geometry. Unknown content is withheld. The synthetic vendor bank field is replaced with a restricted area. No raw screen pixels, inherited container names, bank values, or arbitrary desktop windows are forwarded to the harness or office.

This view is an **accessibility projection**, not a pixel-identical screenshot or a secure overlay placed on the physical desktop. The human mentor continues operating the actual application on the employee's computer. Passive shadowing, model observations, and chat captures receive the same projected surface. Captures are explicitly labeled `mediated_application`. The mentor can see locally provisioned information that the employee's mediated view withholds.

Controls carry descriptions for tools and the central inspector. Office policy can make draft controls read-only. Every input must identify a permitted control from a current view. Caller coordinates cannot redirect a click: the mediator computes its position. There is no arbitrary key, shell, URL, process or clipboard endpoint. Native input rechecks the original observation after the office round trip. Unknown/renamed/duplicate controls, a hidden application, missing policy, and office outages fail closed.

The office checks the mediator's employee/scope, employee lifecycle, current desktop lease, executing authorized operation, arguments, observation and policy revision. Shadowing can only observe, and cannot activate a window. Ordinary active window recovery retains its existing reserved operation. A local input reservation is persisted before execution; an uncertain result is not replayed after a restart. Central events report **authorization**, not proof of native success; the existing execution receipts and business verification remain authoritative.

## Install

Install the shared contracts and mediator separately from the edge:

```bash
pip install -c requirements.lock ./src/shared ./src/application-mediator
```

On the office machine, enroll a mediator for an existing employee (replace the placeholders):

```bash
python -m eas_server.admin --registry /protected/identities.json enroll-mediator \
  --id EMPLOYEE_ID --backend-url https://office.example.test \
  --output /protected/mediator-enrollment
```

For a development HTTP office, explicitly add `--development`. Enrollment produces protected `mediator.env` and `executor-mediator.env` files without printing credentials. The mediator identity has only `mediate` grants; it cannot claim work, run the planner, publish skills, or change policy.

On Windows, install the native controller using [legacy desktop setup](legacy-desktop.md). Its source/installer are now under `src/application-mediator/windows`. Copy the mediator enrollment file securely, then run the following as the designated desktop operator with provisioning privileges:

```powershell
.\src\application-mediator\windows\install-mediator.ps1 `
  -Source C:\TrustedSource\enterprise-agent-system `
  -Python C:\Python312\python.exe `
  -Configuration C:\ProtectedStaging\mediator.env
```

The installer creates `EAS-ApplicationMediator` under `%ProgramData%\EnterpriseAgentSystem\ApplicationMediator`. It copies the native token into its protected configuration. Merge `executor-mediator.env` into the **executor** configuration; remove `EAS_DESKTOP_AGENT_TOKEN` and `EAS_WINDOWS_TOKEN` there. Do not put any of these credentials in planner or learner configuration. Start the mediator before the executor. Its loopback port defaults to 8768; the native controller uses 8766. An explicitly configured mediator never falls back to the raw controller.

A scoped human supervisor assigns policy using their authenticated office session (including its CSRF header):

```http
PUT /api/employees/EMPLOYEE_ID/mediation-policy
Content-Type: application/json

{"profile":"demobooks-v1","enabled":true,"allow_drafts":true}
```

Set `allow_drafts` to false for read-only mediation. Set `enabled` to false to deny all mediated access. Policy changes invalidate old views. The developer agent page has a collapsed **Mediated application** inspector showing the last authorized observation with hover descriptions. Refreshing the inspector reads central evidence; it does not capture the desktop or send input. Access to agent inventory alone does not grant access to this business evidence.

## Boundaries and limitations

- This is a DemoBooks prototype, not universal legacy-app authorization. Each real application needs a trusted profile and validation. Canvas-only software will need a different adapter.
- The mediator and native controller are trusted. The Windows desktop operator/administrator can still reach the original application and controller credential. This does not contain a compromised desktop OS or trusted executor. Keep manually provisioned application permissions and environment isolation.
- The mediator does not accept learner-generated profiles. Automatic skill updates cannot alter its allowlist or office policy.
- Previously recorded evidence retains its original provenance. Installing mediation does not retroactively redact historical screenshots.
- No MCP Apps protocol host is implemented here. The independent service is a foundation for a future MCP Apps adapter; this developer inspector does not claim MCP Apps compatibility.
- Human shadowing still uses the employee's actual desktop. The inspector is read-only and is not a new remote-control channel.

`tests/test_mediation.py` exercises simulated desktop/office cases, including withholding, current-view binding, scoped authority, policy changes, and uncertain-input handling. Real Windows checks are recorded separately when performed.

## Recorded Windows validation

The mediator was installed independently on Morgan's Windows VM and the executor's raw controller credential was removed. An actual live-model, automated staff test request read INV-1042 through office-authorized mediated controls and reported **$1,480.00**. It used four model calls and made no business writes. The synthetic bank field was masked and its value absent from the published view. [Recorded evidence](evidence/application-mediator.json).

Installed-service probes confirmed that the mediator environment has no harness/server/LLM packages, requires an assignment, rejects arbitrary endpoints, and has a credential that the raw controller rejects. A Chromium check confirmed the central inspector starts collapsed, loads its scoped view, supplies control descriptions, and produces no page errors. These checks validate this prototype path, not arbitrary legacy software or resistance to a compromised Windows host.

Validation covered 271 regression cases across the suite and follow-up runs, including 18 mediation cases. Two stale test assumptions were corrected: the mentor fixture needed request authority, and the chat persistence test now opens an agent show page. Lint, formatting, frontend syntax, both Windows builds, and standalone mediator installation passed.
