"""Secondary web-search MCP server. Fallback for when the primary is down."""

import os
import sys

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("search-secondary")

PROVIDER = "secondary"
HEALTHY = os.environ.get("MCP_HEALTHY", "1") != "0"


@mcp.tool()
def web_search(query: str) -> str:
    """Search the web. Returns top results as text."""
    if not HEALTHY:
        raise RuntimeError(f"{PROVIDER} search server is down")
    return (
        f"[{PROVIDER}] Backup results for {query!r}:\n"
        f"  1. Cached entry for {query}\n"
        f"  2. Reference docs covering {query}\n"
    )


if __name__ == "__main__":
    if "--down" in sys.argv:
        HEALTHY = False
    mcp.run()
