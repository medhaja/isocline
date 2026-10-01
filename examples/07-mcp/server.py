"""A tiny MCP server for the 07-mcp example (streamable HTTP). Fictional data only.

    pip install "mcp>=1.9,<2"
    python examples/07-mcp/server.py            # listens on 0.0.0.0:8766, endpoint /mcp
"""
import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("acme-crm", host=os.environ.get("MCP_HOST", "0.0.0.0"), port=int(os.environ.get("MCP_PORT", "8766")))

ACCOUNTS = {
    "acme": {"name": "Acme Corp", "tier": "enterprise", "open_tickets": 3, "arr_usd": 120000},
    "globex": {"name": "Globex", "tier": "growth", "open_tickets": 1, "arr_usd": 48000},
}


@mcp.tool()
def lookup_account(company: str) -> dict:
    """Look up a (fictional) CRM account by company name."""
    key = company.strip().lower().split()[0] if company.strip() else ""
    return ACCOUNTS.get(key, {"name": company, "tier": "unknown", "open_tickets": 0, "arr_usd": 0})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
