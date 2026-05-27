# Unsinkable Ship — Project Story

## Inspiration

Production LLM applications are routinely one provider outage away from a status-page incident. We have all read the same retro: OpenAI brown-outs, the agent surfaces a 5xx, customer support lights up. Anthropic rate-limits the next morning, same story. The infrastructure to avoid this already exists — [TrueFoundry's AI Gateway](https://www.truefoundry.com/docs/ai-gateway/intro-to-llm-gateway) ships priority-based routing, retries, virtual models, observability, even a Virtual MCP Server for tool resilience.

What was missing was the on-ramp. To benefit from the gateway you had to change `base_url`, swap auth, refactor request shapes, configure routing YAML, then build something to *prove* your new fallback chain actually fires under load. None of that is hard, but none of it is free either, and the sum is enough activation energy to keep most teams on raw `openai.OpenAI(api_key=...)` until the day production teaches them otherwise.

We wanted to collapse that activation energy to two lines of code, and pair it with a chaos engine and live observability so resilience could be demonstrated — not just promised — before shipping.

## What it does

`unsinkable` is a Python package that wires any OpenAI-SDK-compatible app to TrueFoundry's AI Gateway in two lines:

```python
from unsinkable import OpenAI
client = OpenAI()
```

The shim subclasses `openai.OpenAI` (and `openai.AsyncOpenAI`), injects the gateway base URL and authentication from environment variables, and installs an instrumented `httpx` transport. Every `chat.completions.create`, embedding, streamed response, or tool-call request now flows through TrueFoundry's gateway with priority fallback (OpenAI → Anthropic → Gemini, or whatever chain you configure).

The package also ships:

- **`unsinkable chaos {break,brownout,clear,status}`** — a CLI that toggles fault scenarios shared between the shim and any running agent via a temp-file state store.
- **`unsinkable dashboard`** — a FastAPI + Server-Sent-Events server that streams live request events to a browser UI with provider-color-coded badges, latency sparkline, token counter, and in-page chaos controls.
- **`unsinkable demo`** — a scripted fourteen-step resilience tour (happy path → break OpenAI → brownout → cascade → MCP failover → recovery) that runs end-to-end in about forty-five seconds.
- **`unsinkable.mcp.ResilientMcpClient`** — a client-side analogue of Virtual MCP Server that wraps multiple MCP backends and fails over between them per tool call, consulting the same chaos state.
- **A live Vercel demo** at <https://web-demo-ebon-iota.vercel.app/> so judges can play with the dashboard without installing anything.

The package is published on PyPI as [`unsinkable`](https://pypi.org/project/unsinkable/) — `pip install unsinkable` works in a clean venv today.

## How we built it

**The shim** lives in `src/unsinkable/client.py`. We subclass `openai.OpenAI` and `openai.AsyncOpenAI` and intercept transport rather than the SDK's resource methods, which preserves the full upstream surface area (`chat`, `embeddings`, `images`, streaming, tool use, structured outputs) without re-implementing anything:

```python
class _InstrumentedSyncTransport(httpx.HTTPTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        start = time.perf_counter()
        requested = _extract_requested_model(request)
        request, chaos = _apply_chaos(request)            # body rewrite if active
        brownout = current_brownout()
        if brownout > 0 and request.method == "POST":
            time.sleep(brownout)
        response = super().handle_request(request)
        response.read()
        self._sink.emit(RequestEvent(
            requested_model=requested,
            resolved_model=_extract_resolved_model(response),   # x-tfy-resolved-model
            status_code=response.status_code,
            latency_ms=(time.perf_counter() - start) * 1000,
            chaos=chaos,
            prompt_tokens=..., completion_tokens=...,
        ))
        return response
```

**The chaos engine** (`src/unsinkable/chaos.py`) persists state as a single JSON file at `/tmp/unsinkable-chaos.json` so the CLI and any agent processes consulting the shim see a consistent view without an IPC layer. Each named scenario maps an "original" Virtual Model name to a "chaos" variant:

```python
SCENARIOS = {
    "openai":    {"resilient-chat/resilient-chat": "chaos-openai-down/chaos-openai-down"},
    "anthropic": {"resilient-chat/resilient-chat": "chaos-anthropic-down/chaos-anthropic-down"},
    "cascade":   {"resilient-chat/resilient-chat": "chaos-cascade/chaos-cascade"},
}
```

The chaos variants are pre-applied TrueFoundry Virtual Models whose priority-0 target uses a deliberately invalid integration (`openai-broken` with `sk-broken-on-purpose` as the API key). When chaos is active, the shim rewrites the `model` field in the outgoing JSON body so the gateway hits the broken target, gets a real error, and falls back through the rest of its priority chain. This makes the demonstration *honest*: there is no mocking — the gateway's own retry and fallback logic does the work.

**Virtual Model manifests** were applied via `tfy apply -f gateway-config/*.yaml`. We figured out the working schema (`provider-account/virtual-model` with `integrations[].routing_config`) by dumping an existing provider account from the management API (`GET /api/svc/v1/provider-accounts`) and adapting:

```yaml
name: resilient-chat
type: provider-account/virtual-model
collaborators:
  - role_id: provider-account-manager
    subject: user:rhaikal91@gmail.com
integrations:
  - name: resilient-chat
    type: integration/model/virtual
    model_types: [chat]
    routing_config:
      type: priority-based-routing
      load_balance_targets:
        - target: openai/gpt-4o-mini
          priority: 0
          fallback_status_codes: ["401","403","404","408","429","500","502","503","504"]
          retry_config: { attempts: 2, delay: 100 }
        - target: anthropic/claude-sonnet-4-6
          priority: 1
        - target: google-gemini/gemini-2.5-flash-lite
          priority: 2
```

**The dashboard** (`src/unsinkable/dashboard.py`) is a small FastAPI app with an in-memory ring buffer (capacity 500) and SSE streaming. Chaos buttons in the UI POST to `/api/chaos/{break|brownout|clear}`, which write the state file and synthesize a `chaos-update` event so the banner updates instantly without waiting for the next LLM request.

**The MCP client** (`src/unsinkable/mcp.py`) uses `AsyncExitStack` to manage stdio sessions to multiple FastMCP backends. Each `call_tool` tries backends in priority order, skipping those matched by an active `mcp-*` chaos scenario; exceptions from one backend trigger an automatic attempt on the next.

**Distribution** uses Hatchling for builds and Twine for the PyPI upload. The 11-test pytest suite covers configuration parsing, the chaos state lifecycle, body-rewrite invariants, and live MCP failover against two locally spawned FastMCP servers.

**The trailer** was built with [HyperFrames](https://hyperframes.heygen.com): ten sub-compositions wired together in a 90-second root timeline, GSAP-driven animations, deterministic seekable rendering. Audio (4 narration lines, 6 SFX, a custom 90-second music track) was generated through the [ElevenLabs](https://elevenlabs.io/) text-to-speech, sound-generation, and music endpoints, then sequenced across separate audio tracks to avoid same-track collisions. Final render was done in Docker because the local WSL environment was missing `libnspr4` / `libnss3` for headless Chrome.

**The Vercel demo** (`web-demo/index.html`) is a single eighteen-kilobyte HTML file with a client-side state machine that simulates the gateway round-trip using pre-canned responses sourced from a real `unsinkable demo` run. Same dashboard look, identical buttons, no backend.

## Challenges we ran into

**TrueFoundry's Virtual MCP Server schema is sparsely documented.** The public docs describe the routing-config shape but not the wrapping manifest. The CLI validator and server schema validator both rejected our first attempts with cryptic `must have required property 'integrations'` errors. We unblocked by dumping an existing provider account from `GET /api/svc/v1/provider-accounts` and reverse-engineering the working YAML.

**Naming quirk.** A Virtual Model named `resilient-chat` exposes itself at `resilient-chat/resilient-chat`, not `<tenant>/<name>` as you might expect from gateway analogues. We tripped on this twice before realizing the model ID format is `<provider-account-name>/<integration-name>`.

**Authentic chaos is hard.** We considered three approaches: client-side fault injection (deceptive — the gateway never sees the failure), TF management API mutation of live VM configs (real but eats time and has rollback risk), and pre-broken Virtual Models (real and idempotent). We chose the third. The model-name-swap trick means the gateway hits an integration with a deliberately invalid key, returns a real 401, and the priority chain's fallback fires for real. The demo is honest end-to-end.

**An asyncio test wrapped a `RuntimeError` in an `ExceptionGroup`.** Our `test_chaos_all_raises` was asserting `pytest.raises(RuntimeError, match=...)` but the error was wrapped by `AsyncExitStack` cleanup, so the matcher missed. Fixed by catching the exception inside the `async with` block and returning it to the caller for assertion.

**Headless Chrome was missing system libs on WSL.** `puppeteer` failed with `libnspr4.so: cannot open shared object file`. Without sudo we couldn't `apt install` the missing libs, so we routed the entire HyperFrames render through Docker via the CLI's `--docker` flag.

**ElevenLabs billing failure.** The first attempt at audio generation returned `payment_issue` on every endpoint. Required pausing for the user to settle the invoice before retrying.

**The OpenAI SDK install was occasionally corrupt.** A fresh `pip install -e .[dev]` left us with `ModuleNotFoundError: openai.types.admin.organization.projects.groups.role_list_params`. Resolved by `pip install --force-reinstall --no-deps openai`. Suspect a partial wheel cache.

**Vercel CLI non-interactive mode requires `--scope`.** With a token attached to a multi-team account, `vercel deploy --prod --yes` refused to pick a default. Explicit `--scope rhaikal91-2932s-projects` unblocked the deploy.

## Accomplishments that we're proud of

- **`pip install unsinkable` is real.** The package shipped to PyPI in version 0.1.0 and we verified a clean install in an empty virtualenv: import works, CLI works, all four subcommands present.
- **The chaos demonstration is honest.** Clicking "Cascade" really does cause two provider failures at the gateway before Gemini answers. The model name the shim sends gets rewritten; the gateway tries `openai-broken/gpt-4o`, fails for real, tries `anthropic-broken/claude-sonnet-4-6`, fails for real, lands on `google-gemini/gemini-2.5-flash-lite`. The `x-tfy-resolved-model` header in the response proves which target ultimately answered. No mocking, no theater.
- **Eleven tests green**, including live MCP failover that spawns two `FastMCP` stdio servers and asserts the resilient client switches backends when the primary is marked broken.
- **The drop-in shim preserves the full `openai-python` surface area** because we intercept transport, not the resource methods. Embeddings, streaming, tool calls, structured outputs — all work without us re-implementing anything.
- **A cinematic ninety-second trailer** rendered deterministically from HTML + GSAP, with mad-scientist narration synced to lightning bolts cracking across the dashboard at each provider failure.
- **A live Vercel demo** that mirrors the dashboard with zero backend, so judges can interact with the resilience story in their browser without installing anything.
- **Eleven concurrent tasks tracked and shipped** in roughly forty-eight hours: SDK, chaos engine, dashboard, MCP, demo CLI, tests, PyPI release, GitHub repo, ninety-second trailer, web demo, professional README.

## What we learned

**TrueFoundry's gateway is genuinely powerful, but the developer story is the bottleneck.** The two-line wiring is what closes the loop between "we have an LLM app" and "we have a resilient LLM app."

**Mirror the resilience pattern at the client too.** Even with a smart gateway, some failure modes are client-side problems: network partition between the app and the gateway, tool servers that aren't behind the gateway, slow tool calls that the gateway never sees. Putting the same fallback discipline on the agent's tool layer (via `ResilientMcpClient`) tells the same story end-to-end.

**Real chaos beats simulated chaos.** Demoing actual gateway-level fallback is dramatically more compelling than mocked errors, and it isn't much more work once you accept the model-name-swap trick.

**HyperFrames's seek-driven deterministic renderer is a useful primitive.** Producing video from HTML/CSS/GSAP that renders frame-identically across machines opens up a workflow where you can iterate on a trailer like a webpage and re-render in two minutes.

**Single-file static HTML still earns its keep.** The Vercel demo is one eighteen-kilobyte file. It loads instantly, requires zero infrastructure, and gives judges the entire interactive story in a browser tab.

## What's next for Unsinkable Ship

- **Move MCP failover to TrueFoundry's Virtual MCP Server** instead of the client-side wrapper. The schema is figured out; the missing piece is hosting publicly reachable MCP servers for TF to call.
- **Anthropic SDK adapter.** Today only OpenAI-compatible clients are supported; we want `from unsinkable import Anthropic` to do the equivalent wiring.
- **A codemod (`unsinkable wire .`)** that scans an existing repository and rewrites `openai.OpenAI(...)` constructors to the unsinkable variant, for teams that want adoption without touching imports manually.
- **Richer chaos scenarios:** rate-limit storms, partial-response truncation, token-budget exhaustion, region-localized outages.
- **Per-route percentile observability.** The dashboard already collects latency per request; surfacing p50 / p95 / p99 distinguishes slow agents from slow providers.
- **Native OpenTelemetry exporter** so request events flow into existing observability stacks (Honeycomb, Datadog, Grafana Cloud) without depending on the bundled dashboard.
- **Production guardrails.** A config flag that hard-disables chaos rewriting in production environments, so a stray `unsinkable chaos break openai` on a developer laptop can never affect a deployed app.
- **Sponsor track 2.0.** Submitting `unsinkable` to PyPI as a public package was the most demanding constraint we could give ourselves, but the next step is making it useful enough that someone files an issue.
