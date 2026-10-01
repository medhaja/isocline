# MCP tool

An agent calls `lookup_account` on a small MCP server (`server.py`, official MCP Python SDK, streamable HTTP) registered as `crm`.

**Requires:** `pip install "mcp>=1.9,<2"`, then `python examples/07-mcp/server.py` on the host. The server is on a private address, so allow it: `ISOCLINE_ALLOW_PRIVATE_NETWORK_HOSTS=["host.docker.internal"]`.

## Run it

```bash
export ISOCLINE_URL=http://localhost:8000
export ISOCLINE_TOKEN=isc_pat_...        # Settings → Access tokens
python examples/run_example.py examples/07-mcp
```

Or import `workflow.json` in the UI (project → **Import**) and run it with the contents of `input.json`.

## Expected result

`status: completed`; the node's tool runs include `mcp:crm/lookup_account`.

## Notes

With the test provider (`tool-user`) the tool receives a canned argument, so the account comes back `unknown`; with a real model it passes `Acme Corp`.
