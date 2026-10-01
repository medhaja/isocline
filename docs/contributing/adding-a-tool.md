# Adding a tool

1. Subclass `Tool` (`apps/api/isocline/tools/base.py`): `name`, `description`, `input_schema` (JSON Schema the model
   sees), `permissions` (informational: `network`, `code_execution`, `filesystem`, `knowledge`), and
   `async execute(args, ctx: ToolContext)`. Raise `ToolError` for user-facing failures. Use `ctx.get_secret(name)` for
   credentials (never read environment secrets directly).
2. Register it in `TOOLS` at the bottom of `tools/builtin.py`. Agents can now list it in `tools`.
3. Anything that makes network requests must go through `tools/ssrf.py` (`pinned_request` for requests you make).
4. If it has side effects, make the policy engine aware (`engine/policy.py::tool_action` / `has_side_effects`) so
   caching is disabled, checkpoints are taken and users can require approval.
5. Optional tool node: see [adding a node](adding-a-node.md) (`tool_<name>` type).
6. Tests without network (`respx`), docs in `docs/tools.md`.
