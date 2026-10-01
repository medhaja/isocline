# Workflows

A workflow is a directed graph of nodes and edges plus settings. The builder saves drafts automatically (optimistic
concurrency: a stale save is rejected with `revision_conflict`); **Publish** creates an immutable numbered version.
Triggers and sub-workflows always run a published version; the builder runs the draft.

**Portable format** (export / import, `schema_version` 2.0):

```json
{"schema_version": "2.0", "name": "Company research", "description": "...",
 "graph": {"schema_version": "1.0", "nodes": [...], "edges": [...], "settings": {...}}}
```

- Nodes: `id`, `key` (the variable name used in `{{key.output}}`), `type`, `name`, `position`, `config`, optional
  `contract` and `harness`. Edges: `id`, `source`, `target`, optional `source_handle` (branch: `true`/`false`, a route
  name, `approved`/`rejected`, `body`/`done`, `error`, `timeout`) and `target_handle` (input port).
- Export strips secrets and workspace-specific references; import assigns fresh node ids (keys, and therefore
  variables, are preserved) and saves a draft that is never run automatically.
- The JSON Schema is in `packages/workflow-schema/` (`make schema` regenerates it from the server models).
- Graphs with `schema_version` 1.0 from earlier releases load unchanged; untyped edges are `Any`.

Validation (builder, `POST /workflows/{id}/validate`, `isocline validate file.json`) checks structure (entry node,
reachability, cycles only through loops, dangling references), contracts and types, and the environment (credentials,
models, knowledge bases, MCP grants). Preflight (`POST /workflows/{id}/plan`) estimates calls,
tokens, cost and time and blocks runs that exceed limits.

See [nodes](nodes.md), [variables](variables.md), [contracts](contracts.md).
