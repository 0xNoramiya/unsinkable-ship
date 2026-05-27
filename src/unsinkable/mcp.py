"""Client-side MCP resilience. Wraps a list of MCP server backends (stdio OR
remote HTTP/SSE) and tries them in priority order on every tool call, skipping
any marked broken by the chaos engine.

Mirrors how TrueFoundry's Virtual MCP Server works at the gateway, but happens
in-process — useful for self-contained demos and as a fallback layer in front
of a Virtual MCP Server endpoint."""

from __future__ import annotations

import asyncio
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Literal

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from unsinkable.chaos import ChaosState
from unsinkable.config import get_settings
from unsinkable.events import RequestEvent, make_sink


@dataclass
class McpBackend:
    """One MCP server backend. Either stdio (local subprocess) or http (remote
    Streamable-HTTP MCP endpoint, e.g. TrueFoundry's Virtual MCP Server).

    Positional argument order preserved for backward compatibility:
    `McpBackend(name, command, args)` always means a stdio backend."""

    name: str
    # stdio fields (positional for backwards compat with v0.1.0):
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    # http fields:
    url: str = ""
    headers: dict[str, str] | None = None
    # Discriminator — comes last so positional construction of stdio backends
    # keeps working from existing code.
    kind: Literal["stdio", "http"] = "stdio"

    @classmethod
    def stdio(cls, name: str, command: str, args: list[str] | None = None,
              env: dict[str, str] | None = None) -> "McpBackend":
        return cls(name=name, kind="stdio", command=command, args=args or [], env=env)

    @classmethod
    def http(cls, name: str, url: str, headers: dict[str, str] | None = None) -> "McpBackend":
        return cls(name=name, kind="http", url=url, headers=headers)


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
        self._sink = make_sink(
            dashboard_url=settings.unsinkable_dashboard_url,
            otel_endpoint=settings.otel_exporter_otlp_endpoint,
            otel_service_name=settings.otel_service_name,
        )

    async def __aenter__(self) -> "ResilientMcpClient":
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        for b in self.backends:
            session = await self._connect(b)
            await session.initialize()
            self._sessions[b.name] = session
        return self

    async def _connect(self, b: McpBackend) -> ClientSession:
        assert self._stack is not None
        if b.kind == "stdio":
            params = StdioServerParameters(command=b.command, args=b.args, env=b.env)
            read, write = await self._stack.enter_async_context(stdio_client(params))
        elif b.kind == "http":
            # Streamable-HTTP transport for remote MCP servers (TF Virtual MCP etc.)
            from mcp.client.streamable_http import streamablehttp_client
            read, write, _ = await self._stack.enter_async_context(
                streamablehttp_client(b.url, headers=b.headers)
            )
        else:  # pragma: no cover — Literal makes this unreachable
            raise ValueError(f"unknown backend kind {b.kind!r}")
        return await self._stack.enter_async_context(ClientSession(read, write))

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
                    url=f"mcp+{backend.kind}://{backend.name}/{name}",
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
                    url=f"mcp+{backend.kind}://{backend.name}/{name}",
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
