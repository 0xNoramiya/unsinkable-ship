# Unsinkable Ship

> Two lines of code. Your LLM agents become unsinkable.

A drop-in resilience layer for any Python LLM/agent app, powered by [TrueFoundry's AI Gateway](https://www.truefoundry.com/docs/ai-gateway/intro-to-llm-gateway). When OpenAI browns out, Claude rate-limits, or your MCP server crashes — your agent keeps going. Your users never notice.

Built for the DevNetwork [AI + ML] Hackathon 2025 — TrueFoundry "Resilient Agents" challenge.

## The pitch

Modern LLM apps are one provider outage away from a status-page incident. TrueFoundry's gateway already solves the *infrastructure* — fallback chains, retries, virtual MCP servers, observability. **Unsinkable** is the missing two-line bridge: it wires your existing OpenAI-SDK app to that gateway with zero refactor, and ships a chaos CLI + live dashboard so you can *prove* your resilience before production does.

## Install (when published)

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

That's the whole change. Your `chat.completions.create(...)` calls work unchanged. If the primary model errors or browns out, the gateway transparently falls back. Your shim emits live events to the dashboard so you can watch it happen.

## See it survive chaos

```bash
# Terminal 1 — start the dashboard
unsinkable dashboard

# Terminal 2 — run your agent
python my_agent.py

# Terminal 3 — break things
unsinkable chaos --break openai           # 100% 500s from OpenAI
unsinkable chaos --brownout 8s openai     # OpenAI takes 8s every request
unsinkable chaos --rate-limit openai      # 429s
unsinkable chaos --mcp-fail web-search    # MCP tool crashes
```

The dashboard at <http://localhost:8765> shows every request, every retry, every fallback hop — in real time.

## Demo agent

```bash
python examples/research_buddy.py
```

A small MCP-powered research assistant. We use it as our chaos victim of choice.

## Architecture

```
┌─────────────────┐    ┌──────────────────────┐    ┌────────────────────┐
│ Your agent code │    │ unsinkable.OpenAI    │    │ TrueFoundry        │
│ from unsinkable │───▶│ shim (SDK subclass)  │───▶│ AI Gateway         │
│ import OpenAI   │    │ + instrumentation    │    │ • Virtual Model    │
└─────────────────┘    └──────────────────────┘    │ • Virtual MCP      │
        │                       │                  │ • Retries          │
        ▼                       │                  └────────────────────┘
┌─────────────────┐             │                            │
│ Chaos CLI       │             ▼                            ▼
│ (fault inject)  │      ┌────────────────┐         ┌────────────────────┐
└─────────────────┘      │ Dashboard      │         │ Real providers     │
                         │ (FastAPI + SSE)│         │ + MCP servers      │
                         └────────────────┘         └────────────────────┘
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
             -f gateway-config/chaos_anthropic_down.yaml
   ```
5. **Verify**: `python examples/smoke_test.py` — should print "all checks passed".

## Status

Hackathon-quality. Solo dev, ~48-hour sprint. See `MEMORY.md` for design decisions.
