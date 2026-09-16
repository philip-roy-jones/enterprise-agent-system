# Digital-employee prototype validation

Validated 2026-09-15 (America/New_York). This is prototype evidence, not production certification or a readiness assessment of an employee.

## Automated checks

- The complete regression suite passed **231 tests** after the lifecycle and Discord changes.
- A subsequent focused run passed **18 tests**, including five additional checks: shared-room browser debugging, complete demonstration-to-admission publication, and three clock-skew cases. There are **236 distinct collected tests** in the resulting tree; the later five were not part of the 231-test full run.
- Ruff lint, formatting and `git diff --check` passed.
- Fresh isolated server and harness installations passed `tools/check_installation.py`. The server environment has no harness, LangGraph or Deep Agents; the edge environment has no server package.

These tests use simulated staff and models unless explicitly identified below. They exercise observation-only shadowing, bounded capture/model attempts, demonstration expiry, supervisor-only activation, scope checks, revocation of issued grants, duplicate prevention, shared-room attribution, private-context separation and fail-closed Discord audience checks. The demonstration admission test publishes a guidance-only skill through the actual worker API and checks that the employee remains in shadowing. The transport tests send no Discord messages.

## Installed workers and live checks

The server and both workers were updated after preserving the server database, identity registry and worker databases. Windows requalified four active packages and Ubuntu requalified one; neither migration quarantined a package. Historical versions and conversation history were retained. The prototype owner and development supervisor received explicit supervisor grants. Workers were returned to **shadowing** after temporary test activations.

| Check | Evidence | Result |
| --- | --- | --- |
| Windows passive observer | Request `383a5e7f4ff14c558ef9c551ed076e2c` | One screen sample and one live model note, zero authorized/executed business operations; cancelled without claiming a demonstrated outcome |
| Windows Finance read | Request `f71a89c18984497a9d3060059d1ce1f6` | Completed with five live model calls and five server-authorized operations; no human action decisions |
| Ubuntu Marketing read | Request `a89f9fe7314d48d1a2a263dde5ca20b4` | Completed with four live model calls and four server-authorized operations; no human action decisions |
| Installed console | Chromium against the installed backend | Employee selector and shadowing UI rendered without JavaScript errors |

The supervisor and mentor in these checks were **simulated test actors**. Applications and records were synthetic. The models were live. No actual human demonstration, employee competence evaluation, or live demonstration-derived skill release is claimed. The successful reads did not submit outcome acceptance or certify new procedures.

The first capture attempt found the Windows desktop controller stopped; starting its existing application tasks restored capture. Two autonomous read attempts then failed closed because Windows rejected newly issued grants as future-dated. Windows Time was enabled and synchronized, and edge signature preflight now tolerates two seconds of clock difference. The server retains strict expiry and one-time consumption using its own clock. The later read checks passed.

## Remaining integration limits

- The optional Discord bridge is implemented and tested with simulated transport. No real bot, guild/channel mapping or live delivery has been configured. See [Discord setup](discord.md).
- The Ubuntu machine uses a **Wayland** graphical session. Its API-based Marketing execution is live-validated. The passive observer currently supports a provisioned X11 session with explicit display access, so desktop shadowing on this Ubuntu Wayland session is not available. Starting a demonstration there reports capture unavailable; it does not silently focus windows, change sessions or invoke an approval portal. A supported capture integration or deliberately provisioned X11 session is required.
- Screen samples can miss actions. Guidance admission is not behavioral certification. Activation is an explicit supervisor decision.
- MCP Apps hosting/observation, group-wide skill replication and device management remain future work.
