# Edge skill packages

Skills are part of the edge harness, not a separate service. The bundled `invoice_correction/` package contains a manifest and natural-language instructions; wheel installations include it under `share/enterprise-agent-system/skills/`.

The runtime binds this template to the worker scope and application version. Learned immutable packages are stored under the edge's `EAS_DATA_DIR/skills/`, with exported `manifest.json`, `SKILL.md`, a hash-checked registry, dependency bindings, admission evidence, history and active-version pointers. Runtime data is not committed to this repository.

Specifications compose registered operations into checkpointed LangGraph tools. They cannot contain executable Python or shell scripts. The model-only learner proposes data; runtime-owned checks decide whether to activate it. Every business operation still needs staff approval, including operations inside an automatically learned skill. See the [accepted plan](../../../docs/plans/agent-led-learning-plan.md).

A guidance-only package has `steps: []` and teaches use of existing tools. Optional bounded text files under `references/`, `templates/`, `assets/` and `tests/` are exported with the immutable package. `read_skill` lists their names and hashes; a separately approved `read_skill_resource` retrieves one file from that exact version. They are never imported or executed. Instruction and resource changes produce a new version even when graph steps are unchanged. Guidance admission is explicitly contract-only, with behavioral evaluation reported separately.
