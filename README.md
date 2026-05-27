# Unsinkable Ship

[![PyPI version](https://img.shields.io/pypi/v/unsinkable.svg)](https://pypi.org/project/unsinkable/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Live Demo](https://img.shields.io/badge/demo-vercel-black.svg)](https://web-demo-ebon-iota.vercel.app/)

A drop-in resilience layer for Python LLM applications. `unsinkable` routes any
[OpenAI-SDK](https://github.com/openai/openai-python)-compatible client through
[TrueFoundry's AI Gateway](https://www.truefoundry.com/docs/ai-gateway/intro-to-llm-gateway)
so that provider outages, brownouts, and MCP tool failures fall back transparently.

- **Live demo**: <https://web-demo-ebon-iota.vercel.app/>
- **Package**: <https://pypi.org/project/unsinkable/>
- **Source**: <https://github.com/0xNoramiya/unsinkable-ship>

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Features](#features)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Synchronous and asynchronous clients](#synchronous-and-asynchronous-clients)
  - [Live dashboard](#live-dashboard)
  - [Chaos engineering](#chaos-engineering)
  - [Resilient MCP client](#resilient-mcp-client)
  - [Scripted demo](#scripted-demo)
- [TrueFoundry Setup](#truefoundry-setup)
- [Architecture](#architecture)
- [Development](#development)
- [Project Layout](#project-layout)
- [Acknowledgments](#acknowledgments)
- [License](#license)

---

## Installation

```bash
pip install unsinkable                # core + OpenAI / Anthropic adapters
pip install "unsinkable[otel]"        # adds the OpenTelemetry exporter
pip install "unsinkable[codemod]"     # adds libcst for `unsinkable wire`
```

Requires **Python 3.10+** and a [TrueFoundry](https://www.truefoundry.com) tenant
with the AI Gateway enabled and at least one connected provider integration
(OpenAI, Anthropic, Google Gemini, etc.).

---

## Quick Start

```python
from unsinkable import OpenAI

client = OpenAI()  # base_url, api_key, and observability injected from env

response = client.chat.completions.create(
    model="resilient-chat/resilient-chat",
    messages=[{"role": "user", "content": "Hello"}],
)
print(response.choices[0].message.content)
```

That is the complete change required to wrap an existing OpenAI-SDK call site.
All other methods (`embeddings`, `images`, streaming, tool use, structured
outputs, etc.) work unmodified.

---

## Features

| Component | Purpose |
| --- | --- |
| `unsinkable.OpenAI` / `AsyncOpenAI` | Drop-in replacement for `openai.OpenAI` and `openai.AsyncOpenAI`. Injects the gateway base URL, authentication, and an instrumented `httpx` transport that captures resolved-model, latency, token usage, and fallback metadata. |
| `unsinkable.Anthropic` / `AsyncAnthropic` | Drop-in replacement for `anthropic.Anthropic`. Translates the Messages API to OpenAI Chat Completions in flight, so the gateway sees a uniform request shape. |
| `unsinkable.mcp.ResilientMcpClient` | Wraps one or more [MCP](https://modelcontextprotocol.io/) servers — local stdio subprocesses **or** remote Streamable-HTTP endpoints (e.g. TrueFoundry's Virtual MCP Server) — and routes tool calls with priority-order failover. Honors the same chaos rules as the LLM shim. |
| `unsinkable doctor` | Verifies gateway connectivity, lists connected providers, surfaces the production-guardrail flag, and checks that required Virtual Models exist. |
| `unsinkable dashboard` | Local FastAPI + SSE server that streams request events to a browser UI. Includes in-page chaos controls, latency sparkline, **p50/p95/p99 percentiles**, token counter, and provider-color-coded badges. |
| `unsinkable demo` | Scripted 14-step resilience tour (~45s) covering LLM fallback, brownouts, cascade outages, and MCP failover. |
| `unsinkable wire <target>` | AST codemod that rewrites `from openai import ...` and `from anthropic import ...` to `from unsinkable import ...` across a project. Supports `--dry-run` for diff preview. |
| `unsinkable chaos {break,brownout,clear,status}` | Manual chaos triggers persisted via a temp-file state store so any process consulting the shim sees the active rules. Scenarios: `openai`, `anthropic`, `cascade`, `rate-limit`, `truncate`, `mcp-{primary,secondary,all}`. |

---

## Configuration

Environment variables (a `.env.example` template is shipped in the repository):

| Variable | Required | Default | Description |
| --- | :-: | --- | --- |
| `TFY_API_KEY` | yes | — | TrueFoundry Personal Access Token. |
| `TFY_HOST` | yes | — | Tenant URL, e.g. `https://<tenant>.truefoundry.cloud`. |
| `TFY_GATEWAY_BASE_URL` | no | `$TFY_HOST/api/llm` | Override for the OpenAI-compatible gateway endpoint. |
| `UNSINKABLE_DEFAULT_MODEL` | no | `resilient-chat/resilient-chat` | Model name used when callers omit one. |
| `UNSINKABLE_DASHBOARD_URL` | no | `http://127.0.0.1:8765` | Where the shim posts request events. Set to an empty string to disable instrumentation. |
| `UNSINKABLE_DISABLE_CHAOS` | no | `0` | Production guardrail. When `1` / `true` / `on`, all chaos engine behavior (body rewrites, brownouts) becomes a no-op even if a stale state file is present. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | unset | If set, request events are also exported as OTLP/HTTP spans. Requires `pip install unsinkable[otel]`. |
| `OTEL_SERVICE_NAME` | no | `unsinkable` | Service name attribute on exported spans. |

Settings are loaded with [`pydantic-settings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
from `.env` or the process environment.

---

## Usage

### Synchronous and asynchronous clients

```python
from unsinkable import OpenAI, AsyncOpenAI

sync_client = OpenAI()
async_client = AsyncOpenAI()

# Both expose the full openai-python surface area.
response = sync_client.chat.completions.create(
    model="resilient-chat/resilient-chat",
    messages=[{"role": "user", "content": "ping"}],
)
```

The shim is a subclass of `openai.OpenAI` / `openai.AsyncOpenAI`; any
constructor argument supported by the upstream SDK is supported here. When
`http_client` is provided explicitly, instrumentation is skipped and the caller
takes full control of transport behavior.

### Live dashboard

```bash
unsinkable dashboard           # listens on http://127.0.0.1:8765 by default
```

Open the URL in a browser. The shim's instrumented transport posts every
request to `/events`; the dashboard streams them to the page via Server-Sent
Events and renders them in a live-updating table with provider badges, a
latency sparkline, and stats counters.

The dashboard also exposes `POST /api/chaos/{break,brownout,clear}` endpoints
and surfaces them as buttons in the UI, so demos can be driven entirely from
the browser.

### Chaos engineering

```bash
unsinkable chaos break openai          # gateway-side OpenAI fallback
unsinkable chaos break anthropic       # gateway-side Anthropic fallback
unsinkable chaos break cascade         # both providers down; gateway routes to Gemini
unsinkable chaos break mcp-primary     # primary MCP server skipped client-side
unsinkable chaos brownout 5            # adds 5 s of latency to every request
unsinkable chaos status                # show active scenario
unsinkable chaos clear                 # remove all active rules
```

Each scenario maps to a pre-created TrueFoundry Virtual Model whose
priority-0 target is deliberately broken; the shim rewrites the outgoing
`model` field so the gateway hits the broken target, fails for real, and
falls back through its declared priority chain.

### Resilient MCP client

```python
import asyncio
from unsinkable.mcp import ResilientMcpClient, McpBackend

backends = [
    McpBackend("primary",   "python", ["servers/primary.py"]),
    McpBackend("secondary", "python", ["servers/secondary.py"]),
]

async def main():
    async with ResilientMcpClient(backends) as mcp:
        result = await mcp.call_tool("web_search", {"query": "rust 1.80"})
    print(result)

asyncio.run(main())
```

`ResilientMcpClient` connects to each backend over `stdio` at context-manager
entry. Tool calls are tried in declaration order; backends matching an active
`mcp-*` chaos scenario are skipped, and exceptions from one backend trigger an
automatic attempt on the next.

### Scripted demo

```bash
# Terminal 1
unsinkable dashboard

# Terminal 2
unsinkable demo
```

The `demo` command runs a 14-step scenario covering the happy path, a single
provider outage with fallback to Claude, a brownout, a cascade outage with
fallback to Gemini, MCP-layer failover, and recovery. Pair it with the
dashboard for the full visual story.

---

## TrueFoundry Setup

The repository ships YAML manifests for the four Virtual Models referenced by
the chaos scenarios. Setup takes roughly ten minutes.

1. **Tenant + token.** Sign in at `https://<tenant>.truefoundry.cloud` and create
   a Personal Access Token under **Access → Personal Access Tokens**. Copy
   `.env.example` to `.env` and populate `TFY_API_KEY` and `TFY_HOST`.

2. **CLI installation and login.**

   ```bash
   pip install -U truefoundry
   tfy login --host "$TFY_HOST" --api-key "$TFY_API_KEY"
   ```

3. **Provider integrations.** In the console, navigate to **AI Gateway →
   Model Integrations → New** and add the following five integrations:

   | Integration name | Provider | Model | Notes |
   | --- | --- | --- | --- |
   | `openai` | OpenAI | `gpt-4o-mini` | valid API key |
   | `anthropic` | Anthropic | `claude-sonnet-4-6` | valid API key |
   | `google-gemini` | Google AI Studio | `gemini-2.5-flash-lite` | valid API key |
   | `openai-broken` | OpenAI | `gpt-4o` | intentionally invalid key (e.g. `sk-broken-on-purpose`) |
   | `anthropic-broken` | Anthropic | `claude-sonnet-4-6` | intentionally invalid key |

4. **Virtual Models.** Apply the four manifests:

   ```bash
   tfy apply \
     -f gateway-config/resilient_chat.yaml \
     -f gateway-config/chaos_openai_down.yaml \
     -f gateway-config/chaos_anthropic_down.yaml \
     -f gateway-config/chaos_cascade.yaml
   ```

5. **Verify.** Run `unsinkable doctor` for a table view, or
   `python examples/smoke_test.py` for a scripted end-to-end check that
   exercises a direct provider call, the happy-path Virtual Model, and a
   chaos-triggered fallback.

---

## Architecture

```
                ┌────────────────────────────────────────────────────────┐
                │                       Your code                        │
                │    from unsinkable import OpenAI, AsyncOpenAI          │
                └──────────────────────┬─────────────────────────────────┘
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            ▼                                                     ▼
  ┌──────────────────────┐                          ┌──────────────────────┐
  │  unsinkable.OpenAI   │                          │ ResilientMcpClient   │
  │  • base_url, auth    │                          │  • priority backends │
  │  • httpx transport   │                          │  • chaos-aware       │
  │    instrumentation   │                          │  • per-call failover │
  │  • body rewriting    │                          └──────────┬───────────┘
  │    via chaos rules   │                                     │
  └──────────┬───────────┘                                     │
             │                                                 ▼
             │                                       ┌───────────────────┐
             ▼                                       │   MCP servers     │
  ┌──────────────────────┐                           │   (stdio)         │
  │ TrueFoundry          │                           └───────────────────┘
  │ AI Gateway           │
  │  • Virtual Models    │
  │  • Priority routing  │
  │  • Fallback codes    │
  └──────────┬───────────┘
             │
             ▼
  ┌────────────────────────────────────────┐
  │ OpenAI · Anthropic · Google Gemini …   │
  └────────────────────────────────────────┘
```

Request events emitted by the transport are also POSTed to the optional local
dashboard for live observability.

---

## Development

```bash
git clone https://github.com/0xNoramiya/unsinkable-ship.git
cd unsinkable-ship
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```

The test suite (11 tests) covers configuration loading, the chaos-state
lifecycle, and live MCP failover against two locally spawned stdio servers.

---

## Project Layout

```
unsinkable-ship/
├── src/unsinkable/             # Python package
│   ├── client.py               # OpenAI / AsyncOpenAI shim + httpx transport
│   ├── chaos.py                # State persistence and scenario activation
│   ├── mcp.py                  # ResilientMcpClient
│   ├── dashboard.py            # FastAPI + SSE dashboard
│   ├── auto_demo.py            # Scripted demo runner
│   ├── cli.py                  # Click entry point: doctor / dashboard / demo / chaos
│   ├── config.py               # pydantic-settings configuration
│   └── events.py               # RequestEvent dataclass and HTTP sink
├── examples/                   # Sample agent and MCP servers
├── gateway-config/             # TrueFoundry Virtual Model manifests
├── tests/                      # pytest suite (config + chaos + MCP)
├── web-demo/                   # Static client-side dashboard mirror (Vercel)
└── video/trailer/              # HyperFrames composition for the project trailer
```

---

## Acknowledgments

Built for the **DevNetwork [AI + ML] Hackathon 2025**, TrueFoundry "Resilient
Agents" track. Powered by [TrueFoundry's AI Gateway](https://www.truefoundry.com/docs/ai-gateway/intro-to-llm-gateway),
the [OpenAI Python SDK](https://github.com/openai/openai-python), and the
[Model Context Protocol](https://modelcontextprotocol.io/).

---

## License

Released under the [MIT License](LICENSE).
