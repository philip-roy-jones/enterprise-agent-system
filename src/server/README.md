# Enterprise Agent System server

Owns the staff frontend, HTTP API, approvals, dispatch and durable audit data. It installs no edge harness, LangGraph or Deep Agent code.

From the repository root:

```bash
python -m pip install -c requirements.lock ./src/shared ./src/server
enterprise-server
```

Configure `.env` in the launch directory, or set `EAS_ENV_FILE`. Register public workflow metadata in `eas_server/roles.py`; executable workflows belong to the edge harness.
