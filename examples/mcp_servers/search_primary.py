"""Primary web-search MCP server. Stub results; the demo's resilience story
is about handling THIS server going down, not about real search."""

import os
import sys

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("search-primary")

PROVIDER = "primary"
HEALTHY = os.environ.get("MCP_HEALTHY", "1") != "0"


@mcp.tool()
def web_search(query: str) -> str:
    """Search the web. Returns top results as text."""
    if not HEALTHY:
        raise RuntimeError(f"{PROVIDER} search server is down")
    return (
        f"[{PROVIDER}] Top results for {query!r}:\n"
        f"  1. Comprehensive overview of {query}\n"
        f"  2. Wikipedia article on {query}\n"
        f"  3. Recent news mentioning {query}\n"
    )


if __name__ == "__main__":
    if "--down" in sys.argv:
        HEALTHY = False
    mcp.run()
