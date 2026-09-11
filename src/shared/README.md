# Enterprise Agent System API contracts

A small versioned Python library used by the server and harness. It defines public job, decision, observation and role schemas, shared error/value conventions, and RPC method names. It has no process, credentials, environment loading, database, desktop controller or graph runtime.

Install it alongside either application, or build its wheel with `python -m pip wheel --no-deps ./src/shared` from the repository root. DemoBooks does not depend on it.
