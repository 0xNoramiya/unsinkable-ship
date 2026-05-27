# Changelog

## 0.2.0 (2026-05-28)

### Added

- **Anthropic SDK adapter.** `from unsinkable import Anthropic, AsyncAnthropic` —
  drop-in for `anthropic.Anthropic`. Translates Messages API → OpenAI Chat
  Completions, routes through TrueFoundry, translates the response back to the
  Anthropic `Message` shape (incl. `stop_reason` mapping).
- **Codemod.** `unsinkable wire <target> [--dry-run]` rewrites
  `from openai import OpenAI, AsyncOpenAI` and the equivalent Anthropic imports
  to `from unsinkable import ...`. Uses libcst so whitespace and comments are
  preserved.
- **OpenTelemetry exporter.** Set `OTEL_EXPORTER_OTLP_ENDPOINT` to fan request
  events out as spans alongside (or instead of) the dashboard. Optional install:
  `pip install unsinkable[otel]`.
- **Remote MCP backends.** `McpBackend.http(name, url, headers)` connects via
  Streamable-HTTP for use with TF's Virtual MCP Server endpoint or any remote
  MCP server. `McpBackend.stdio(...)` continues to work for local subprocesses.
- **Production guardrail.** `UNSINKABLE_DISABLE_CHAOS=1` hard-disables chaos
  rewrites and brownouts at the transport level, even if a stale state file is
  present. `unsinkable doctor` surfaces the flag.
- **Two new chaos scenarios.**
  - `unsinkable chaos break rate-limit` — routes through a Virtual Model whose
    priority-0 target retries on 429 / 5xx then falls back.
  - `unsinkable chaos break truncate` — body-override that clamps `max_tokens=1`
    so downstream parsing resilience can be exercised.
- **Latency percentiles.** Dashboard now shows p50 / p95 / p99 alongside the
  rolling average, computed from the last 50 requests.

### Changed

- `make_sink()` now accepts both `dashboard_url` and `otel_endpoint`; emits
  to a `CompositeSink` when both are configured.
- `pyproject.toml` adds optional extras: `[anthropic]`, `[codemod]`, `[otel]`.

### Compatibility

- `McpBackend(name, command, args, env, ...)` positional construction continues
  to work; the new `kind` field is the last positional argument.
- All v0.1.0 code paths are preserved.

## 0.1.0 (2026-05-27)

Initial release. OpenAI / AsyncOpenAI shim, chaos CLI, FastAPI + SSE dashboard,
scripted `unsinkable demo`, ResilientMcpClient with stdio backends.
