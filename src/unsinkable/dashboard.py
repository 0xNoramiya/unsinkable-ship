from __future__ import annotations

import asyncio
import json
import time
from collections import deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

from unsinkable.chaos import (
    ChaosState,
    SCENARIOS,
    activate,
    activate_brownout,
)

app = FastAPI(title="Unsinkable Dashboard")

_EVENTS: deque[dict] = deque(maxlen=500)
_SUBSCRIBERS: list[asyncio.Queue] = []


@app.post("/events")
async def ingest(req: Request) -> dict:
    payload = await req.json()
    _EVENTS.append(payload)
    for q in list(_SUBSCRIBERS):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass
    return {"ok": True}


@app.get("/api/events")
async def list_events() -> list[dict]:
    return list(_EVENTS)


@app.get("/api/chaos")
async def chaos_status() -> dict:
    state = ChaosState.load()
    if not state:
        return {"active": False}
    return {
        "active": True,
        "scenario": state.scenario,
        "rewrites": state.rewrites,
        "brownout_seconds": state.brownout_seconds,
    }


@app.post("/api/chaos/break/{provider}")
async def chaos_break(provider: str) -> dict:
    from unsinkable.chaos import (
        BODY_OVERRIDE_SCENARIOS,
        MCP_SCENARIOS,
        activate_body_override,
        activate_mcp,
    )

    if provider in MCP_SCENARIOS:
        state = activate_mcp(provider)
    elif provider in BODY_OVERRIDE_SCENARIOS:
        state = activate_body_override(provider)
    elif provider in SCENARIOS:
        state = activate(provider)
    else:
        raise HTTPException(400, f"unknown scenario {provider!r}")
    await _push_chaos_event(state)
    return {"ok": True, "scenario": state.scenario}


@app.post("/api/chaos/brownout/{seconds}")
async def chaos_brownout(seconds: float) -> dict:
    state = activate_brownout(seconds)
    await _push_chaos_event(state)
    return {"ok": True, "scenario": state.scenario, "brownout_seconds": state.brownout_seconds}


@app.post("/api/chaos/clear")
async def chaos_clear() -> dict:
    cleared = ChaosState.clear()
    await _push_chaos_event(None)
    return {"ok": True, "cleared": cleared}


async def _push_chaos_event(state: ChaosState | None) -> None:
    payload = {
        "kind": "chaos-update",
        "ts": time.time(),
        "active": state is not None,
        "scenario": state.scenario if state else None,
        "brownout_seconds": state.brownout_seconds if state else 0,
    }
    for q in list(_SUBSCRIBERS):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


@app.get("/stream")
async def stream(req: Request) -> EventSourceResponse:
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _SUBSCRIBERS.append(queue)

    async def gen():
        try:
            for ev in list(_EVENTS):
                yield {"event": "request", "data": json.dumps(ev)}
            while True:
                if await req.is_disconnected():
                    return
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15)
                    name = "chaos" if ev.get("kind") == "chaos-update" else "request"
                    yield {"event": name, "data": json.dumps(ev)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        finally:
            if queue in _SUBSCRIBERS:
                _SUBSCRIBERS.remove(queue)

    return EventSourceResponse(gen())


_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<title>Unsinkable — Live Resilience</title>
<style>
  :root { color-scheme: dark; --bg:#0b0f14; --panel:#10171f; --line:#1c2530;
          --dim:#7d8c9c; --fg:#d7e0ea; }
  * { box-sizing: border-box; }
  body { font: 14px/1.4 ui-monospace, "JetBrains Mono", Menlo, monospace;
         background:var(--bg); color:var(--fg); margin:0; padding:24px; }
  h1 { margin:0 0 4px; font-size:22px; letter-spacing:-0.01em; }
  .sub { color:var(--dim); margin-bottom:18px; }

  .panel { background:var(--panel); border:1px solid var(--line); border-radius:8px;
           padding:14px 16px; margin-bottom:14px; }
  .panel h2 { margin:0 0 10px; font-size:11px; text-transform:uppercase;
              letter-spacing:0.08em; color:var(--dim); font-weight:600; }

  .stats { display:flex; gap:10px; flex-wrap:wrap; }
  .stat { background:var(--bg); border:1px solid var(--line); border-radius:6px;
          padding:8px 14px; min-width:90px; }
  .stat .num { font-size:22px; font-weight:600; }
  .stat .lbl { color:var(--dim); font-size:11px; text-transform:uppercase;
               letter-spacing:0.06em; margin-top:2px; }

  .controls { display:flex; gap:8px; flex-wrap:wrap; }
  button { background:#1a2733; color:var(--fg); border:1px solid #2a3b4f;
           padding:7px 14px; border-radius:5px; font:inherit; cursor:pointer;
           transition:background 0.15s; }
  button:hover { background:#243446; }
  button.danger { background:#3a1e1e; border-color:#5a2828; color:#ffb0b0; }
  button.danger:hover { background:#4a2828; }
  button.warn { background:#3a311e; border-color:#5a4828; color:#ffd070; }
  button.warn:hover { background:#4a4028; }
  button.ok { background:#1e3a2a; border-color:#285a38; color:#9fe0a3; }
  button.ok:hover { background:#284a32; }

  #chaos { display:none; padding:12px 16px; margin-bottom:14px;
           background:#3a1e1e; color:#ffd0d0; border-radius:6px;
           border:1px solid #5a2828; font-weight:500; }
  #chaos.on { display:block; }

  table { width:100%; border-collapse: collapse; }
  th, td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); }
  th { color:var(--dim); font-weight: 600; font-size:11px; text-transform:uppercase;
       letter-spacing:0.04em; }
  tr.ok td { }
  tr.err { background: rgba(220,60,60,0.10); }
  tr.fb { background: rgba(220,160,60,0.10); }

  .pill { display:inline-block; padding:2px 9px; border-radius:10px; font-size:11px;
          font-weight:500; }
  .pill.ok { background:#1e3a2a; color:#7fe0a3; }
  .pill.err { background:#3a1e1e; color:#f08080; }
  .pill.fb { background:#3a311e; color:#f0c060; }
  .pill.chaos { background:#3a1e3a; color:#f0a0f0; margin-left:4px; }

  .badge { display:inline-block; padding:1px 8px; border-radius:3px; font-size:11px;
           font-weight:500; }
  .badge.openai { background:#0f3322; color:#7fe0a3; }
  .badge.anthropic { background:#3a2a14; color:#f0a868; }
  .badge.gemini, .badge.google-gemini, .badge.google { background:#14253a; color:#80a8f0; }
  .badge.broken, .badge.openai-broken, .badge.anthropic-broken { background:#3a1e1e; color:#f08080; }
  .badge.primary, .badge.secondary { background:#2a1e3a; color:#c8a8f0; }
  .badge.dim { color:var(--dim); }
  .kind-mcp { color:#c8a8f0; font-weight:500; }

  .small { color:var(--dim); font-size:11px; }
  .mono { font-family: inherit; }
</style></head>
<body>
<h1>🚢 Unsinkable — Live Resilience</h1>
<div class="sub">Powered by TrueFoundry's AI Gateway. Watch chaos bounce off in real time.</div>

<div id="chaos"></div>

<div class="panel">
  <h2>Stats</h2>
  <div class="stats">
    <div class="stat"><div class="num" id="s-total">0</div><div class="lbl">Requests</div></div>
    <div class="stat"><div class="num" id="s-ok" style="color:#7fe0a3">0</div><div class="lbl">OK</div></div>
    <div class="stat"><div class="num" id="s-fb" style="color:#f0c060">0</div><div class="lbl">Fallback</div></div>
    <div class="stat"><div class="num" id="s-err" style="color:#f08080">0</div><div class="lbl">Error</div></div>
    <div class="stat"><div class="num" id="s-avg">–</div><div class="lbl">Avg</div></div>
    <div class="stat"><div class="num" id="s-p50">–</div><div class="lbl">p50</div></div>
    <div class="stat"><div class="num" id="s-p95">–</div><div class="lbl">p95</div></div>
    <div class="stat"><div class="num" id="s-p99">–</div><div class="lbl">p99</div></div>
    <div class="stat"><div class="num" id="s-tokens">0</div><div class="lbl">Tokens</div></div>
    <div class="stat" style="flex:1; min-width:200px">
      <canvas id="spark" width="240" height="48" style="display:block; width:100%; height:48px"></canvas>
      <div class="lbl">Latency (last 30)</div>
    </div>
  </div>
</div>

<div class="panel">
  <h2>Chaos controls</h2>
  <div class="controls">
    <button class="danger" onclick="chaos('break/openai')">Break OpenAI</button>
    <button class="danger" onclick="chaos('break/anthropic')">Break Anthropic</button>
    <button class="danger" onclick="chaos('break/cascade')">Cascade (both)</button>
    <button class="danger" onclick="chaos('break/rate-limit')">Rate-limit OpenAI</button>
    <button class="warn" onclick="chaos('break/truncate')">Truncate (max_tokens=1)</button>
    <button class="danger" onclick="chaos('break/mcp-primary')">Break MCP primary</button>
    <button class="warn" onclick="chaos('brownout/3')">Brownout +3s</button>
    <button class="warn" onclick="chaos('brownout/8')">Brownout +8s</button>
    <button class="ok" onclick="chaos('clear')">Clear chaos</button>
  </div>
</div>

<div class="panel" style="padding:0">
  <table id="t"><thead><tr>
    <th style="padding-left:16px">time</th>
    <th>requested</th><th>resolved</th>
    <th>status</th><th>latency</th><th>note</th>
  </tr></thead><tbody></tbody></table>
</div>

<script>
const tbody = document.querySelector("#t tbody");
const chaosBanner = document.querySelector("#chaos");
const stats = {total:0, ok:0, fb:0, err:0, tokens:0, latencies:[]};
const sparkCanvas = document.getElementById('spark');

function providerOf(model) {
  if (!model) return 'unknown';
  if (model === 'primary' || model === 'secondary') return model;
  if (model.includes('claude')) return 'anthropic';
  if (model.includes('gpt') || model.includes('o1')) return 'openai';
  if (model.includes('gemini')) return 'gemini';
  if (model.includes('broken')) return 'broken';
  return model.split('/')[0] || model;
}

function badge(model) {
  if (!model) return '<span class="badge dim">-</span>';
  const p = providerOf(model);
  const cls = ['openai','anthropic','gemini','broken','primary','secondary'].includes(p) ? p : 'dim';
  return `<span class="badge ${cls}">${model}</span>`;
}

async function chaos(action) {
  const r = await fetch('/api/chaos/' + action, {method:'POST'});
  const d = await r.json();
  console.log('chaos', action, d);
}

async function refreshChaos() {
  const r = await fetch('/api/chaos');
  const d = await r.json();
  if (d.active) {
    let msg = `⚠ chaos active — ${d.scenario}`;
    if (d.brownout_seconds) msg += ` (+${d.brownout_seconds}s latency)`;
    if (d.rewrites && Object.keys(d.rewrites).length) {
      const swap = Object.entries(d.rewrites)[0];
      msg += ` :: ${swap[0]} → ${swap[1]}`;
    }
    chaosBanner.textContent = msg;
    chaosBanner.classList.add('on');
  } else {
    chaosBanner.classList.remove('on');
  }
}

function percentile(sortedArr, p) {
  if (!sortedArr.length) return null;
  const idx = Math.min(sortedArr.length - 1, Math.floor((p / 100) * sortedArr.length));
  return sortedArr[idx];
}

function updateStats() {
  document.getElementById('s-total').textContent = stats.total;
  document.getElementById('s-ok').textContent = stats.ok;
  document.getElementById('s-fb').textContent = stats.fb;
  document.getElementById('s-err').textContent = stats.err;
  document.getElementById('s-tokens').textContent = stats.tokens;
  if (stats.latencies.length > 0) {
    const recent = stats.latencies.slice(-50);
    const sorted = [...recent].sort((a, b) => a - b);
    const avg = recent.reduce((a, b) => a + b, 0) / recent.length;
    document.getElementById('s-avg').textContent = avg.toFixed(0) + 'ms';
    document.getElementById('s-p50').textContent = percentile(sorted, 50).toFixed(0) + 'ms';
    document.getElementById('s-p95').textContent = percentile(sorted, 95).toFixed(0) + 'ms';
    document.getElementById('s-p99').textContent = percentile(sorted, 99).toFixed(0) + 'ms';
  }
  drawSpark();
}

function drawSpark() {
  const ctx = sparkCanvas.getContext('2d');
  const w = sparkCanvas.width, h = sparkCanvas.height;
  ctx.clearRect(0,0,w,h);
  const data = stats.latencies.slice(-30);
  if (data.length < 2) return;
  const max = Math.max(...data, 1);
  ctx.strokeStyle = '#7fc8e0'; ctx.lineWidth = 1.5;
  ctx.fillStyle = 'rgba(127,200,224,0.15)';
  ctx.beginPath();
  data.forEach((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - (v / max) * (h - 4) - 2;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath(); ctx.fill();
}

function row(ev) {
  stats.total++;
  if (ev.error) stats.err++;
  else if (ev.resolved_model && providerOf(ev.requested_model) !== providerOf(ev.resolved_model)
           && !ev.requested_model.startsWith('chaos-')) stats.fb++;
  else if (ev.resolved_model && ev.requested_model && ev.requested_model.startsWith('chaos-')
           && providerOf(ev.resolved_model) !== 'openai' && providerOf(ev.resolved_model) !== 'anthropic'
           && providerOf(ev.requested_model.replace('chaos-','').split('-')[0]) === providerOf(ev.resolved_model)) stats.ok++;
  else if (ev.chaos) stats.fb++;
  else stats.ok++;
  if (ev.latency_ms) stats.latencies.push(ev.latency_ms);
  if (ev.prompt_tokens) stats.tokens += (ev.prompt_tokens + (ev.completion_tokens || 0));
  updateStats();

  const tr = document.createElement("tr");
  const ok = ev.error == null && ev.status_code && ev.status_code < 400;
  const hopped = ev.chaos != null;
  tr.className = ev.error ? "err" : (hopped ? "fb" : (ok ? "ok" : ""));
  const t = new Date(ev.ts * 1000).toLocaleTimeString();
  const pill = ev.error
    ? `<span class="pill err">ERR</span>`
    : hopped
      ? `<span class="pill fb">FALLBACK</span>`
      : `<span class="pill ok">OK</span>`;
  const chaosPill = ev.chaos ? `<span class="pill chaos">CHAOS</span>` : ``;
  const note = ev.error
    ? ev.error
    : ev.chaos
      ? `${ev.chaos.scenario}: ${providerOf(ev.chaos.original)} → ${providerOf(ev.resolved_model)}`
      : "";
  const kindLabel = ev.kind === 'mcp' ? '<span class="kind-mcp">MCP</span> ' : '';
  tr.innerHTML = `
    <td class="small" style="padding-left:16px">${t}</td>
    <td>${kindLabel}${badge(ev.requested_model)} ${chaosPill}</td>
    <td>${badge(ev.resolved_model)}</td>
    <td>${pill} <span class="small">${ev.status_code ?? ""}</span></td>
    <td class="small">${ev.latency_ms ? ev.latency_ms.toFixed(0) + "ms" : "-"}</td>
    <td class="small">${note}</td>`;
  tbody.prepend(tr);
  while (tbody.children.length > 200) tbody.lastChild.remove();
}

refreshChaos();
const es = new EventSource("/stream");
es.addEventListener("request", e => row(JSON.parse(e.data)));
es.addEventListener("chaos", () => refreshChaos());
</script>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _HTML
