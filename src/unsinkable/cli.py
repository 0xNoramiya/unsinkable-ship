from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.table import Table

from unsinkable.config import get_settings

console = Console()


@click.group()
@click.version_option()
def main() -> None:
    """Unsinkable Ship — make any LLM app resilient via TrueFoundry's AI Gateway."""


@main.command()
def doctor() -> None:
    """Probe TrueFoundry gateway connectivity and config sanity."""
    import httpx

    try:
        s = get_settings()
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Failed to load settings:[/red] {e}")
        console.print("Run [bold]cp .env.example .env[/bold] and fill in TFY_API_KEY + TFY_HOST.")
        sys.exit(1)

    table = Table(title="Unsinkable Doctor", show_header=True)
    table.add_column("Check")
    table.add_column("Result")

    table.add_row("Tenant host", s.tfy_host)
    table.add_row("Gateway base", s.gateway_base_url)
    table.add_row("OpenAI base", s.openai_base_url)
    table.add_row("Default model", s.unsinkable_default_model)
    table.add_row("Dashboard URL", s.unsinkable_dashboard_url or "[dim]disabled[/dim]")

    expected = ["resilient-chat/resilient-chat", "chaos-openai-down/chaos-openai-down",
                "chaos-anthropic-down/chaos-anthropic-down"]
    try:
        r = httpx.get(
            f"{s.openai_base_url}/models",
            headers={"Authorization": f"Bearer {s.tfy_api_key}"},
            timeout=10,
        )
        if r.status_code == 200:
            model_ids = [m["id"] for m in r.json().get("data", [])]
            count = len(model_ids)
            table.add_row("Gateway reachable", f"[green]yes[/green] ({count} models available)")
            if count == 0:
                table.add_row(
                    "Models",
                    "[yellow]no providers connected — go to the TF console "
                    "and add an OpenAI/Anthropic integration[/yellow]",
                )
            else:
                providers = sorted({m.split("/", 1)[0] for m in model_ids if "/" in m})
                table.add_row("Providers", ", ".join(providers))
                for name in expected:
                    found = name in model_ids
                    table.add_row(
                        f"VM: {name}",
                        "[green]configured[/green]" if found else
                        "[yellow]missing — import gateway-config/*.yaml[/yellow]",
                    )
        else:
            table.add_row("Gateway reachable", f"[red]HTTP {r.status_code}[/red]")
    except Exception as e:  # noqa: BLE001
        table.add_row("Gateway reachable", f"[red]error: {e}[/red]")

    table.add_row("Chaos state", _chaos_status_str())
    console.print(table)


def _chaos_status_str() -> str:
    from unsinkable.chaos import ChaosState

    state = ChaosState.load()
    if state is None:
        return "[dim]clear[/dim]"
    return f"[red]{state.scenario}[/red]"


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8765, show_default=True)
def dashboard(host: str, port: int) -> None:
    """Launch the live resilience dashboard."""
    import uvicorn

    uvicorn.run("unsinkable.dashboard:app", host=host, port=port, log_level="warning")


@main.command()
def demo() -> None:
    """Run the scripted resilience demo. Pair with `unsinkable dashboard`."""
    from unsinkable.auto_demo import main as run_demo

    run_demo()


@main.group()
def chaos() -> None:
    """Inject failures into your LLM/MCP traffic."""


@chaos.command("break")
@click.argument("provider", type=click.Choice(
    ["openai", "anthropic", "cascade", "mcp-primary", "mcp-secondary", "mcp-all"]
))
def chaos_break(provider: str) -> None:
    """Break a provider for the next request. LLM scenarios trigger TF
    gateway-side fallback; mcp-* scenarios are honored by ResilientMcpClient."""
    from unsinkable.chaos import MCP_SCENARIOS, STATE_PATH, activate, activate_mcp

    if provider in MCP_SCENARIOS:
        state = activate_mcp(provider)
        console.print(
            f"[red bold]MCP CHAOS[/red bold] scenario active: [bold]{state.scenario}[/bold]"
        )
    else:
        state = activate(provider)
        console.print(
            f"[red bold]CHAOS[/red bold] scenario active: [bold]{state.scenario}[/bold]"
        )
        for orig, swap in state.rewrites.items():
            console.print(f"  [dim]{orig}[/dim] → [yellow]{swap}[/yellow]")
    console.print(f"[dim]state file: {STATE_PATH}[/dim]")


@chaos.command("clear")
def chaos_clear() -> None:
    """Disable all active chaos rules."""
    from unsinkable.chaos import ChaosState

    if ChaosState.clear():
        console.print("[green]chaos cleared[/green]")
    else:
        console.print("[dim]no chaos active[/dim]")


@chaos.command("status")
def chaos_status() -> None:
    """Show the active chaos scenario, if any."""
    from unsinkable.chaos import ChaosState

    state = ChaosState.load()
    if not state:
        console.print("[dim]no chaos active[/dim]")
        return
    console.print(f"[red]CHAOS[/red] scenario: [bold]{state.scenario}[/bold]")
    for orig, swap in state.rewrites.items():
        console.print(f"  {orig} → [yellow]{swap}[/yellow]")
    if state.brownout_seconds:
        console.print(f"  brownout: [yellow]+{state.brownout_seconds}s[/yellow] per request")


@chaos.command("brownout")
@click.argument("seconds", type=float)
def chaos_brownout(seconds: float) -> None:
    """Add SECONDS of latency to every request. Stacks with break."""
    from unsinkable.chaos import STATE_PATH, activate_brownout

    state = activate_brownout(seconds)
    console.print(
        f"[yellow bold]BROWNOUT[/yellow bold] +{state.brownout_seconds}s per request "
        f"(scenario: [bold]{state.scenario}[/bold])"
    )
    console.print(f"[dim]state file: {STATE_PATH}[/dim]")


if __name__ == "__main__":
    main()
