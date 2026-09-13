# Agent-led workflow discovery

Staff describe work in the conversation. The edge Deep Agent chooses among scoped skill metadata, requests approval to read a skill, and invokes its durable LangGraph as a separately approved tool. Each operation inside the graph still needs approval.

When no procedure fits, the agent can compose trusted Finance operations or ask staff for guidance. Unknown application conditions suspend a graph and return an assistance request; investigation and resumption remain approved. Code failures produce diagnostics. Denial and rejection never become a reason to try a different execution path.

After independently verified work is accepted, a bounded learner derives a declarative procedure from the successful approved trace. Runtime-owned checks can activate a new immutable skill or an update automatically. A later request retrieves that version. New Python operations require harness development; the learner cannot invent application capabilities.

The initial task families are read-only discrepancy reports and correction drafts. The reporting skill is absent from the seeded catalog and is a target for cumulative learning. See the [accepted plan](plans/agent-led-learning-plan.md), [architecture](architecture.md), and [README learning walkthrough](../README.md#teach-a-reusable-improvement).

Earlier workflow-discovery evidence records the historical graph-first implementation. Keep its model/staff provenance and limitations; it does not validate this revised coordinator.
