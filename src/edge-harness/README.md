# Enterprise Agent System edge harness

Runs LangGraph workflows, Deep Agent fallback, desktop adapters and permission checks on the edge machine. It contains no server persistence or staff frontend.

From the repository root on the edge machine:

```bash
python -m pip install -c requirements.lock ./src/shared ./src/edge-harness
enterprise-harness
```

Configure `.env` in the launch directory, or set `EAS_ENV_FILE`. Windows deployment scripts and the desktop controller are in `windows/`. Business workflow code is under `eas_harness/workflows/`. The optional `[browser]` extra installs Playwright for the synthetic browser fixture.

The total job budget (`EAS_JOB_TIMEOUT_SECONDS`, configured on the server) includes time waiting for staff approval or during staff takeover. The worker checks it on every polling cycle, including paused jobs, and before individual actions. Expiration fails the job and invalidates outstanding approvals. If the worker is offline, it checks the deadline when it reconnects.
