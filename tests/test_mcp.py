import asyncio
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    path = tmp_path / "chaos.json"
    monkeypatch.setenv("UNSINKABLE_CHAOS_STATE", str(path))
    monkeypatch.setenv("TFY_API_KEY", "fake")
    monkeypatch.setenv("TFY_HOST", "https://demo.truefoundry.cloud")
    monkeypatch.setenv("UNSINKABLE_DASHBOARD_URL", "")
    import importlib
    import unsinkable.chaos as chaos
    import unsinkable.config as config
    importlib.reload(chaos)
    config.get_settings.cache_clear()
    yield
    importlib.reload(chaos)
    config.get_settings.cache_clear()


def _backends():
    from unsinkable.mcp import McpBackend
    return [
        McpBackend("primary", PY, [str(REPO_ROOT / "examples/mcp_servers/search_primary.py")]),
        McpBackend("secondary", PY, [str(REPO_ROOT / "examples/mcp_servers/search_secondary.py")]),
    ]


def test_happy_path_uses_primary(state_file):
    from unsinkable.mcp import ResilientMcpClient

    async def run():
        async with ResilientMcpClient(_backends()) as c:
            return await c.call_tool("web_search", {"query": "x"})

    out = asyncio.run(run())
    assert "[primary]" in out


def test_chaos_skips_primary(state_file):
    from unsinkable.chaos import activate_mcp
    from unsinkable.mcp import ResilientMcpClient

    async def run():
        async with ResilientMcpClient(_backends()) as c:
            activate_mcp("mcp-primary")
            return await c.call_tool("web_search", {"query": "x"})

    out = asyncio.run(run())
    assert "[secondary]" in out


def test_chaos_all_raises(state_file):
    from unsinkable.chaos import activate_mcp
    from unsinkable.mcp import ResilientMcpClient

    async def run() -> Exception | None:
        async with ResilientMcpClient(_backends()) as c:
            activate_mcp("mcp-all")
            try:
                await c.call_tool("web_search", {"query": "x"})
            except RuntimeError as e:
                return e
        return None

    err = asyncio.run(run())
    assert err is not None and "all MCP backends failed" in str(err)
