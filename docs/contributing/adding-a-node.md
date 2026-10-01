# Adding a node type

Prefer composing existing nodes or adding a tool: new node types touch the schema, the executor and the UI.

1. **Schema** (`apps/api/isocline/schemas/workflow.py`): add the type to the right set (`INPUT_TYPES`, `LOGIC_TYPES`,
   `TOOL_TYPES`, ...), add a config model and register it in `CONFIG_MODELS`.
2. **Structure & types** (`engine/graph.py`): allowed source handles (`allowed_source_handles`), validation rules, and
   the node's output type (`effective_output_type`) if it isn't `Any`.
3. **Execution** (`engine/executor.py::_dispatch`): return `(output, handle, usage, extra)`. Durable nodes that wait
   must persist a wait state and return `Outcome("waiting")` — never sleep in a worker.
4. **Planner** (`engine/planner.py`) estimates for preflight, if it calls models or tools.
5. **UI**: `apps/web/src/lib/nodes.ts` (palette entry and defaults) and `components/builder/ConfigPanel.tsx`.
6. **Schema package**: `make schema` and commit `packages/workflow-schema/`.
7. Tests: an engine test in `apps/api/tests/integration/test_engine.py` style (in-process executor, `local_test`).
