# 🚢 Unsinkable Ship

[![PyPI version](https://img.shields.io/pypi/v/unsinkable.svg)](https://pypi.org/project/unsinkable/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> Two lines of code. Your LLM agents become unsinkable.

A drop-in resilience layer for any Python LLM/agent app, powered by [TrueFoundry's AI Gateway](https://www.truefoundry.com/docs/ai-gateway/intro-to-llm-gateway). When OpenAI browns out, Claude rate-limits, or your MCP server crashes — your agent keeps going. Your users never notice.

Built for the DevNetwork [AI + ML] Hackathon 2025 — **TrueFoundry "Resilient Agents"** track.

## The pitch

Modern LLM apps are one provider outage away from a status-page incident. TrueFoundry's gateway already solves the *infrastructure* — fallback chains, retries, virtual MCP servers, observability. **Unsinkable Ship** is the missing two-line bridge: it wires your existing OpenAI-SDK app to that gateway with zero refactor, plus a chaos CLI, live dashboard, and a sample MCP-resilient agent so you can *prove* your resilience before production does.

## Try it without installing

**Live dashboard demo:** [web-demo-ebon-iota.vercel.app](https://web-demo-ebon-iota.vercel.app) — pre-recorded interactive mirror, no install needed.

## Install

```bash
pip install unsinkable
```

## Wire it in (2 lines)

```python
# Before
from openai import OpenAI
client = OpenAI()

# After
from unsinkable import OpenAI
client = OpenAI()  # routed through TrueFoundry, with GPT-4o → Claude → Gemini fallback
```

That's the whole change. Your `chat.completions.create(...)` calls work unchanged. If the primary model errors or browns out, the gateway transparently falls back. The shim emits live events to the dashboard so you can watch every hop.

## See it survive chaos

```bash
# Terminal 1 — start the dashboard at http://localhost:8765
unsinkable dashboard

# Terminal 2 — run the scripted 14-step resilience tour (~45s)
unsinkable demo

# Or break things manually:
unsinkable chaos break openai          # priority-0 OpenAI target fails → Claude answers
unsinkable chaos break anthropic       # Anthropic broken → Gemini takes over
unsinkable chaos break cascade         # both LLM providers down → Gemini still alive
unsinkable chaos brownout 8            # +8s latency injected per request
unsinkable chaos break mcp-primary     # tool server primary skipped → secondary answers
unsinkable chaos clear                 # back to normal
```

The dashboard shows every request, every retry, every fallback hop — in real time, with provider-color-coded badges, a latency sparkline, and in-page chaos buttons (so judges/demo viewers don't even need a terminal).

## What's in the box

| | |
|---|---|
| `unsinkable.OpenAI` / `AsyncOpenAI` | Drop-in SDK shim with instrumented httpx transport |
| `unsinkable doctor` | Probes gateway connectivity + lists missing Virtual Models |
| `unsinkable dashboard` | FastAPI + SSE live UI with chaos buttons, stats, sparkline |
| `unsinkable demo` | Scripted 14-step cinematic demo (LLM + MCP resilience) |
| `unsinkable chaos {break,brownout,clear,status}` | Manual chaos triggers |
| `examples/research_buddy.py` | Sample async agent with tool-calling + ResilientMcpClient |
| `examples/mcp_servers/{search_primary,search_secondary}.py` | Two FastMCP servers we deliberately break for the demo |
| `examples/smoke_test.py` | One-shot verification that your TF setup is wired correctly |
| `gateway-config/*.yaml` | TrueFoundry Virtual Model manifests for `tfy apply` |

## Architecture

```
┌─────────────────┐    ┌──────────────────────┐    ┌────────────────────┐
│ Your agent code │    │ unsinkable.OpenAI    │    │ TrueFoundry        │
│ from unsinkable │───▶│ shim (SDK subclass)  │───▶│ AI Gateway         │
│ import OpenAI   │    │ + instrumented httpx │    │ • Virtual Models   │
└─────────────────┘    │   transport          │    │ • Priority routing │
        │              └──────────────────────┘    │ • Real fallback    │
        │                       │                  └────────────────────┘
        │                       │                            │
        ▼                       ▼                            ▼
┌─────────────────┐    ┌────────────────────┐       ┌────────────────────┐
│ ResilientMcpCli │    │ Live Dashboard     │       │ OpenAI / Anthropic │
│ • primary       │    │ FastAPI + SSE      │       │ / Google Gemini    │
│ • secondary     │    │ + chaos buttons    │       │ providers          │
└─────────────────┘    └────────────────────┘       └────────────────────┘
```

## TrueFoundry setup (~10 min, mostly `tfy apply`)

1. **Tenant + token** — at `https://<tenant>.truefoundry.cloud` go to **Access → Personal Access Tokens** and create one. Copy `.env.example` to `.env` and fill in `TFY_API_KEY` + `TFY_HOST`.
2. **Install + log in to the CLI**:
   ```
   pip install -U truefoundry
   tfy login --host $TFY_HOST --api-key $TFY_API_KEY
   ```
3. **Provider integrations (UI, ~5 min)** — **AI Gateway → Model Integrations → New** and add **5** integrations:
   - `openai` (real key) with `gpt-4o-mini`
   - `anthropic` (real key) with `claude-sonnet-4-6`
   - `google-gemini` (real key) with `gemini-2.5-flash-lite`
   - `openai-broken` (bogus key e.g. `sk-broken-on-purpose`) with `gpt-4o`
   - `anthropic-broken` (bogus key) with `claude-sonnet-4-6`
4. **Virtual Models (CLI, ~10 s)**:
   ```
   tfy apply -f gateway-config/resilient_chat.yaml \
             -f gateway-config/chaos_openai_down.yaml \
             -f gateway-config/chaos_anthropic_down.yaml \
             -f gateway-config/chaos_cascade.yaml
   ```
5. **Verify**: `python examples/smoke_test.py` — should print "all checks passed", or run `unsinkable doctor` for the table view.

## A note on MCP resilience

TrueFoundry's gateway has a **Virtual MCP Server** feature that does for tools what Virtual Models do for LLMs. We chose to ship the same pattern *client-side* in this hackathon scope — `unsinkable.mcp.ResilientMcpClient` wraps two local FastMCP servers and fails over between them, consulting the same chaos engine the LLM shim uses. That keeps the demo self-contained (no public MCP servers to deploy) while telling the identical resilience story. Migrating to TF's Virtual MCP is a config change, not a rewrite.

## Run the tests

```bash
git clone https://github.com/0xNoramiya/unsinkable-ship
cd unsinkable-ship
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```

11 tests cover config, chaos engine state, and live MCP failover against the two local servers.

## License

MIT. See [LICENSE](LICENSE).
