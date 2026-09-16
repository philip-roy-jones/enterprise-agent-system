# Application Mediator

A separately installed Enterprise Agent System application between the edge harness and legacy desktop software. Its first profile mediates DemoBooks observations and controls under office policy.

- `eas_mediator/`: authenticated loopback service, trusted DemoBooks profile, durable input ledger.
- `windows/DesktopAgent/`: native accessibility and input transport.
- `windows/install-mediator.ps1`: independent Windows installation/task.

See [setup and boundaries](../../docs/application-mediator.md). This is prototype infrastructure, not test business software and not an MCP Apps host.
