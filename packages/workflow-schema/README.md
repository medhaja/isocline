# @isocline/workflow-schema

The one persistent workflow representation (schema **v2.0**; v1.0 documents are read and upgraded). Canvas edits, imports, templates, the
AI generator all produce documents that validate against these files.

- `workflow-document.schema.json` — the export/import file (`*.workflow.json`)
- `workflow-graph.schema.json` — `{schema_version, nodes, edges, settings}`
- `node-configs.schema.json` — per-node-type `config` schemas
- `types.ts` — TypeScript types used by the web app

These JSON files are generated from `apps/api/isocline/schemas/workflow.py`; regenerate with
`python scripts/export_schema.py`. Structural rules that JSON Schema cannot express (no cycles,
handles valid for the node type, variables only referencing upstream nodes, bounded loops) are
enforced by `apps/api/isocline/engine/graph.py::validate_structure`.

Exports never contain credentials: `credential_id` and secret-looking fields are stripped.
