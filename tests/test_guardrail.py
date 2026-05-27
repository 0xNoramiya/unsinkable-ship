"""UNSINKABLE_DISABLE_CHAOS turns the engine into a no-op even with a state file."""

import importlib
import json
import os

import pytest


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    path = tmp_path / "chaos.json"
    monkeypatch.setenv("UNSINKABLE_CHAOS_STATE", str(path))
    import unsinkable.chaos as chaos
    importlib.reload(chaos)
    yield chaos
    monkeypatch.delenv("UNSINKABLE_DISABLE_CHAOS", raising=False)
    importlib.reload(chaos)


def _body(model="resilient-chat/resilient-chat"):
    return json.dumps({"model": model, "messages": []}).encode()


def test_rewrite_active_when_guardrail_off(state_file, monkeypatch):
    chaos = state_file
    monkeypatch.delenv("UNSINKABLE_DISABLE_CHAOS", raising=False)
    chaos.activate("openai")
    new_body, info = chaos.maybe_rewrite_body(_body())
    assert info is not None
    assert info["chaos"] == "chaos-openai-down/chaos-openai-down"


def test_rewrite_disabled_when_guardrail_on(state_file, monkeypatch):
    chaos = state_file
    chaos.activate("openai")
    monkeypatch.setenv("UNSINKABLE_DISABLE_CHAOS", "1")
    body = _body()
    new_body, info = chaos.maybe_rewrite_body(body)
    assert info is None
    assert new_body == body


def test_brownout_zero_when_guardrail_on(state_file, monkeypatch):
    chaos = state_file
    chaos.activate_brownout(5.0)
    assert chaos.current_brownout() == 5.0
    monkeypatch.setenv("UNSINKABLE_DISABLE_CHAOS", "1")
    assert chaos.current_brownout() == 0.0


def test_guardrail_accepts_truthy_strings(state_file, monkeypatch):
    chaos = state_file
    chaos.activate("openai")
    for v in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("UNSINKABLE_DISABLE_CHAOS", v)
        _, info = chaos.maybe_rewrite_body(_body())
        assert info is None, f"guardrail not honored for value {v!r}"
    monkeypatch.setenv("UNSINKABLE_DISABLE_CHAOS", "false")
    _, info = chaos.maybe_rewrite_body(_body())
    assert info is not None
