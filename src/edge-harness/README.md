# Enterprise Agent System edge harness

Runs the Deep Agent, skills, approvals, protected memory and application integrations on an edge machine. The server/frontend is a separate application.

A **skill** is the reusable procedure: instructions, supporting text and an optional constrained graph. `read_skill` retrieves its approved version, `run_skill` executes its graph, and `resume_skill` continues the same interrupted execution. Graph steps reuse registered operations; each step requires its own staff approval. The runtime does not execute generated Python.

- `skills/`: bundled generic skill packages. Learned organization-specific packages live under the protected executor runtime's `skills/` directory.
- `eas_harness/skill_runtime.py`: compiles a skill's graph and resumes its checkpoints.
- `eas_harness/integrations/`: trusted application operations for Finance and Marketing.
- `eas_harness/roles.py`: registered input schemas, adapters and operation contracts.
- `windows/`: Windows installer and independent desktop controller.
- `linux/`: isolated service installation and access probes for API-based Linux integrations.

Historical graph-first evaluation tools are under `tools/enterprise_dev/legacy/`, outside the deployed harness. New requests always enter the Deep Agent.

Install from the repository root:

```bash
python -m pip install -c requirements.lock ./src/shared ./src/edge-harness
```

Use the [developer setup](../../docs/developer-setup.md) for Windows or the [Linux worker guide](../../docs/linux-worker.md) for Ubuntu. Each installed component uses its own `EAS_ENV_FILE`, account and credentials. The optional `[browser]` extra supports automated browser fixtures.

The server's request deadline includes staff approval waits and takeover. Expiry prevents further effects. Restart retains approvals and uncertain-write state; it never authorizes replaying a write.
