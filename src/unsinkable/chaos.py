"""Chaos engine. State lives in a temp file so CLI and shim processes share it
without restarts. Pairs with pre-applied TrueFoundry Virtual Models whose
priority-0 target is deliberately broken — so when the shim rewrites the model,
TF's real fallback fires for the next provider."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger("unsinkable.chaos")

STATE_PATH = Path(
    os.environ.get("UNSINKABLE_CHAOS_STATE", Path(tempfile.gettempdir()) / "unsinkable-chaos.json")
)


@dataclass
class ChaosState:
    rewrites: dict[str, str] = field(default_factory=dict)
    scenario: str | None = None
    brownout_seconds: float = 0.0
    # Extra fields the transport should merge into the outgoing request body
    # (e.g. {"max_tokens": 1} to demonstrate truncation resilience).
    body_overrides: dict[str, object] = field(default_factory=dict)

    @classmethod
    def load(cls) -> ChaosState | None:
        if not STATE_PATH.exists():
            return None
        try:
            data = json.loads(STATE_PATH.read_text())
            return cls(**data)
        except Exception as e:  # noqa: BLE001
            log.debug("could not parse chaos state: %s", e)
            return None

    def save(self) -> None:
        STATE_PATH.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def clear(cls) -> bool:
        if STATE_PATH.exists():
            STATE_PATH.unlink()
            return True
        return False


SCENARIOS: dict[str, dict[str, str]] = {
    "openai": {"resilient-chat/resilient-chat": "chaos-openai-down/chaos-openai-down"},
    "anthropic": {"resilient-chat/resilient-chat": "chaos-anthropic-down/chaos-anthropic-down"},
    "cascade": {"resilient-chat/resilient-chat": "chaos-cascade/chaos-cascade"},
    # Rate-limit scenario: route through a Virtual Model whose priority-0 target
    # is configured to fail on 429s, so the gateway-side retry/fallback path
    # gets exercised. Falls back to the same chain.
    "rate-limit": {"resilient-chat/resilient-chat": "chaos-rate-limit/chaos-rate-limit"},
}

# Body-override scenarios mutate the request payload rather than the model name.
# `truncate` clamps max_tokens to demonstrate downstream parsing resilience.
BODY_OVERRIDE_SCENARIOS: dict[str, dict[str, object]] = {
    "truncate": {"max_tokens": 1},
}

# MCP scenarios don't rewrite request bodies; they're consulted by the
# ResilientMcpClient, which skips backends matching the active scenario.
MCP_SCENARIOS = {"mcp-primary", "mcp-secondary", "mcp-all"}


def activate_mcp(scenario: str) -> ChaosState:
    if scenario not in MCP_SCENARIOS:
        raise ValueError(f"unknown MCP scenario {scenario!r}; known: {sorted(MCP_SCENARIOS)}")
    state = ChaosState(scenario=scenario)
    state.save()
    return state


def activate_body_override(scenario: str) -> ChaosState:
    if scenario not in BODY_OVERRIDE_SCENARIOS:
        raise ValueError(
            f"unknown body-override scenario {scenario!r}; "
            f"known: {sorted(BODY_OVERRIDE_SCENARIOS)}"
        )
    # Body overrides apply to the resilient-chat happy-path; no model rewrite.
    existing = ChaosState.load() or ChaosState()
    existing.body_overrides = dict(BODY_OVERRIDE_SCENARIOS[scenario])
    existing.scenario = scenario
    existing.save()
    return existing


def activate(scenario: str) -> ChaosState:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; known: {list(SCENARIOS)}")
    state = ChaosState(rewrites=SCENARIOS[scenario], scenario=scenario)
    state.save()
    return state


def activate_brownout(seconds: float) -> ChaosState:
    existing = ChaosState.load() or ChaosState()
    existing.brownout_seconds = max(0.0, float(seconds))
    if not existing.scenario:
        existing.scenario = f"brownout-{int(seconds)}s"
    existing.save()
    return existing


def _chaos_disabled() -> bool:
    # Read the env var directly so the guardrail works even if pydantic-settings
    # hasn't been instantiated yet (e.g. inside a transport before client init).
    return os.environ.get("UNSINKABLE_DISABLE_CHAOS", "0").lower() in {"1", "true", "yes", "on"}


def maybe_rewrite_body(body_bytes: bytes) -> tuple[bytes, dict[str, str] | None]:
    if _chaos_disabled():
        return body_bytes, None
    state = ChaosState.load()
    if not state or not state.rewrites:
        return body_bytes, None
    try:
        body = json.loads(body_bytes.decode("utf-8") or "{}")
    except Exception:  # noqa: BLE001
        return body_bytes, None
    if not isinstance(body, dict):
        return body_bytes, None
    original = body.get("model")
    if not isinstance(original, str) or original not in state.rewrites:
        return body_bytes, None
    # Stash the chaos overrides for the transport to apply (max_tokens clamp, etc.)
    overrides = state.body_overrides or {}
    for k, v in overrides.items():
        body[k] = v
    body["model"] = state.rewrites[original]
    info = {
        "original": original,
        "chaos": body["model"],
        "scenario": state.scenario or "",
    }
    if overrides:
        info["overrides"] = json.dumps(overrides)
    return json.dumps(body).encode("utf-8"), info


def current_brownout() -> float:
    if _chaos_disabled():
        return 0.0
    state = ChaosState.load()
    return state.brownout_seconds if state else 0.0
