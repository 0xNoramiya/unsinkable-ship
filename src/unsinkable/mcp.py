"""Client-side MCP resilience. Wraps a list of MCP server backends and tries
them in priority order on every tool call, skipping any marked broken by the
chaos engine. Mirrors how TrueFoundry's Virtual MCP Server works at the
gateway, but happens in-process — useful when you can't put the MCP servers
behind a reachable URL."""

from __future__ import annotations

import asyncio
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from unsinkable.chaos import ChaosState
from unsinkable.events import RequestEvent, make_sink
from unsinkable.config import get_settings


@dataclass
class McpBackend:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None


class ResilientMcpClient:
    """Connects to one or more MCP servers and routes tool calls with fallback.

    Backends are tried in declaration order. Chaos rules of the form
    `mcp-<backend-name>` cause that backend to be skipped (simulating outage).
    """

    def __init__(self, backends: list[McpBackend]) -> None:
        if not backends:
            raise ValueError("at least one MCP backend required")
        self.backends = backends
        self._stack: AsyncExitStack | None = None
        self._sessions: dict[str, ClientSession] = {}
        settings = get_settings()
        self._sink = make_sink(settings.unsinkable_dashboard_url)

    async def __aenter__(self) -> "ResilientMcpClient":
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        for b in self.backends:
            params = StdioServerParameters(command=b.command, args=b.args, env=b.env)
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._sessions[b.name] = session
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._stack is not None:
            await self._stack.__aexit__(*exc)
            self._stack = None

    def _is_broken(self, backend_name: str, chaos: ChaosState | None) -> bool:
        if chaos is None:
            return False
        scenario = chaos.scenario or ""
        return scenario == f"mcp-{backend_name}" or scenario == "mcp-all"

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        chaos = ChaosState.load()
        last_error: str | None = None
        skipped: list[str] = []
        for backend in self.backends:
            if self._is_broken(backend.name, chaos):
                skipped.append(backend.name)
                continue
            start = time.perf_counter()
            try:
                session = self._sessions[backend.name]
                result = await session.call_tool(name, arguments=arguments)
                latency_ms = (time.perf_counter() - start) * 1000
                text = _result_text(result)
                self._sink.emit(RequestEvent(
                    kind="mcp",
                    method="CALL",
                    url=f"mcp://{backend.name}/{name}",
                    requested_model=backend.name,
                    resolved_model=backend.name,
                    status_code=200,
                    latency_ms=latency_ms,
                    fallback_hops=skipped,
                    chaos=({"scenario": chaos.scenario or "", "skipped": ",".join(skipped),
                            "original": skipped[0] if skipped else "",
                            "chaos": backend.name} if skipped else None),
                ))
                return text
            except Exception as e:  # noqa: BLE001
                latency_ms = (time.perf_counter() - start) * 1000
                last_error = f"{type(e).__name__}: {e}"
                self._sink.emit(RequestEvent(
                    kind="mcp",
                    method="CALL",
                    url=f"mcp://{backend.name}/{name}",
                    requested_model=backend.name,
                    latency_ms=latency_ms,
                    error=last_error,
                ))
        raise RuntimeError(
            f"all MCP backends failed for tool {name!r} "
            f"(skipped {skipped} by chaos; last error: {last_error})"
        )


def _result_text(result: Any) -> str:
    parts = getattr(result, "content", None) or []
    out: list[str] = []
    for p in parts:
        text = getattr(p, "text", None)
        if text:
            out.append(text)
    return "\n".join(out) or str(result)


def run_sync(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if asyncio.get_event_loop().is_running() is False else asyncio.run(coro)
