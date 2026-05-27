from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from rich.console import Console
from rich.panel import Panel

from unsinkable import AsyncOpenAI, OpenAI
from unsinkable.chaos import ChaosState, activate, activate_brownout, activate_mcp
from unsinkable.config import get_settings
from unsinkable.mcp import McpBackend, ResilientMcpClient

console = Console()

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MCP_BACKENDS = [
    McpBackend("primary", sys.executable,
               [str(REPO_ROOT / "examples/mcp_servers/search_primary.py")]),
    McpBackend("secondary", sys.executable,
               [str(REPO_ROOT / "examples/mcp_servers/search_secondary.py")]),
]


@dataclass
class Step:
    title: str
    narration: str
    action: Literal["ask", "chaos", "clear", "brownout", "mcp_chaos", "mcp_call"]
    arg: str | None = None
    pause_after: float = 1.5


SCRIPT = [
    Step("Happy path", "First, the agent calls our resilient virtual model. "
         "Default routing → OpenAI gpt-4o-mini answers.",
         "ask", "Reply in exactly 3 words.", pause_after=2.0),

    Step("Happy path", "One more, to set the baseline.",
         "ask", "Name one Python web framework.", pause_after=2.0),

    Step("Chaos: break OpenAI", "Now imagine OpenAI brown-outs in production. "
         "We swap to a virtual model where the OpenAI target is deliberately broken.",
         "chaos", "openai", pause_after=1.5),

    Step("After break", "Same agent call. OpenAI fails for real at the gateway. "
         "TrueFoundry's fallback fires — Claude takes over. User never notices.",
         "ask", "Reply in exactly 3 words.", pause_after=2.0),

    Step("Brownout: +5s latency", "Now provider is up but slow. We add 5s of latency.",
         "brownout", "5", pause_after=1.0),

    Step("Under brownout", "Same call, you can feel the brownout. Still arrives.",
         "ask", "What year is it?", pause_after=2.0),

    Step("Cascade: both down", "Worst case — OpenAI AND Anthropic both down. "
         "Gateway tries each, fails both, lands on Gemini.",
         "chaos", "cascade", pause_after=1.5),

    Step("Triple fallback", "The agent still answers.",
         "ask", "Name three colors.", pause_after=2.5),

    Step("Recovery", "Clear the chaos. Back to normal routing.",
         "clear", None, pause_after=1.0),

    Step("Recovered", "We're back on the primary path.",
         "ask", "All good?", pause_after=1.5),

    Step("MCP layer too", "LLMs aren't the only thing that breaks. Tool servers do too. "
         "Let's call web_search through our resilient MCP client.",
         "mcp_call", "Rust 1.80 release notes", pause_after=2.0),

    Step("Break the primary MCP", "Now we kill the primary search server.",
         "mcp_chaos", "mcp-primary", pause_after=1.5),

    Step("MCP fallback", "Same call. Primary is skipped; secondary answers. "
         "Tools survive outages too.",
         "mcp_call", "Rust 1.80 release notes", pause_after=2.5),

    Step("Demo done", "Clearing everything.",
         "clear", None, pause_after=0.5),
]


def _post(url: str) -> None:
    try:
        httpx.post(url, timeout=2)
    except Exception:
        pass


def _ask(client: OpenAI, prompt: str) -> tuple[str, str]:
    settings = get_settings()
    t0 = time.perf_counter()
    r = client.chat.completions.create(
        model=settings.unsinkable_default_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=40,
    )
    dt = time.perf_counter() - t0
    return r.model, f"{r.choices[0].message.content or ''}  [dim]({dt:.1f}s)[/dim]"


async def _mcp_call(mcp: ResilientMcpClient, query: str) -> tuple[str, str]:
    t0 = time.perf_counter()
    result = await mcp.call_tool("web_search", {"query": query})
    dt = time.perf_counter() - t0
    first_line = result.splitlines()[0] if result else ""
    return first_line, f"  [dim]({dt*1000:.0f}ms)[/dim]"


async def amain() -> None:
    s = get_settings()
    dashboard_root = (s.unsinkable_dashboard_url or "").rstrip("/")
    client = OpenAI()
    async with ResilientMcpClient(MCP_BACKENDS) as mcp:
        await _run_steps(client, mcp, dashboard_root)


def main() -> None:
    asyncio.run(amain())


async def _run_steps(client: OpenAI, mcp: ResilientMcpClient, dashboard_root: str) -> None:
    s = get_settings()

    console.print(Panel.fit(
        "[bold]Unsinkable Ship — Live Resilience Demo[/bold]\n"
        f"Default model: [cyan]{s.unsinkable_default_model}[/cyan]\n"
        f"Dashboard: [cyan]{dashboard_root or '(disabled)'}[/cyan]\n"
        "Pro tip: open the dashboard in a second window to see chaos visualized.",
        title="🚢 ", border_style="cyan",
    ))

    ChaosState.clear()
    for i, step in enumerate(SCRIPT, 1):
        console.print()
        console.print(f"[bold magenta]Step {i}/{len(SCRIPT)} — {step.title}[/bold magenta]")
        console.print(f"[dim italic]{step.narration}[/dim italic]")
        time.sleep(1.0)

        if step.action == "ask":
            assert step.arg
            try:
                model, reply = _ask(client, step.arg)
                console.print(f"  [cyan]Q[/cyan] {step.arg}")
                console.print(f"  [green]A via {model}[/green]: {reply}")
            except Exception as e:  # noqa: BLE001
                console.print(f"  [red]FAIL[/red] {type(e).__name__}: {e}")
        elif step.action == "chaos":
            assert step.arg
            activate(step.arg)
            console.print(f"  [red bold]>>> chaos break {step.arg} activated[/red bold]")
            if dashboard_root:
                _post(f"{dashboard_root}/api/chaos/break/{step.arg}")
        elif step.action == "brownout":
            assert step.arg
            activate_brownout(float(step.arg))
            console.print(f"  [yellow bold]>>> brownout +{step.arg}s activated[/yellow bold]")
            if dashboard_root:
                _post(f"{dashboard_root}/api/chaos/brownout/{step.arg}")
        elif step.action == "clear":
            ChaosState.clear()
            console.print("  [green bold]>>> chaos cleared[/green bold]")
            if dashboard_root:
                _post(f"{dashboard_root}/api/chaos/clear")
        elif step.action == "mcp_call":
            assert step.arg
            try:
                first, took = await _mcp_call(mcp, step.arg)
                console.print(f"  [cyan]MCP[/cyan] web_search {step.arg!r}{took}")
                console.print(f"  [green]→[/green] {first}")
            except Exception as e:  # noqa: BLE001
                console.print(f"  [red]FAIL[/red] {type(e).__name__}: {e}")
        elif step.action == "mcp_chaos":
            assert step.arg
            activate_mcp(step.arg)
            console.print(f"  [red bold]>>> mcp chaos {step.arg} activated[/red bold]")
            if dashboard_root:
                _post(f"{dashboard_root}/api/chaos/break/{step.arg}")

        time.sleep(step.pause_after)

    ChaosState.clear()
    console.print()
    console.print(Panel.fit(
        "[bold green]Demo complete.[/bold green] Watch the dashboard for the full timeline.",
        border_style="green",
    ))


if __name__ == "__main__":
    main()
