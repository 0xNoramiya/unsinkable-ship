import importlib
import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def chaos_state_file(tmp_path, monkeypatch):
    path = tmp_path / "chaos.json"
    monkeypatch.setenv("UNSINKABLE_CHAOS_STATE", str(path))
    import unsinkable.chaos as chaos
    importlib.reload(chaos)
    yield chaos
    importlib.reload(chaos)


def test_activate_writes_state(chaos_state_file):
    chaos = chaos_state_file
    state = chaos.activate("openai")
    assert state.scenario == "openai"
    assert "resilient-chat/resilient-chat" in state.rewrites
    assert Path(os.environ["UNSINKABLE_CHAOS_STATE"]).exists()


def test_clear_removes_state(chaos_state_file):
    chaos = chaos_state_file
    chaos.activate("openai")
    assert chaos.ChaosState.clear() is True
    assert chaos.ChaosState.load() is None


def test_rewrite_swaps_matching_model(chaos_state_file):
    chaos = chaos_state_file
    chaos.activate("openai")
    body = json.dumps({"model": "resilient-chat/resilient-chat", "messages": []}).encode()
    new_body, info = chaos.maybe_rewrite_body(body)
    parsed = json.loads(new_body)
    assert parsed["model"] == "chaos-openai-down/chaos-openai-down"
    assert info == {
        "original": "resilient-chat/resilient-chat",
        "chaos": "chaos-openai-down/chaos-openai-down",
        "scenario": "openai",
    }


def test_rewrite_passthrough_when_no_match(chaos_state_file):
    chaos = chaos_state_file
    chaos.activate("openai")
    body = json.dumps({"model": "gpt-4o", "messages": []}).encode()
    new_body, info = chaos.maybe_rewrite_body(body)
    assert new_body == body
    assert info is None


def test_rewrite_passthrough_when_no_chaos(chaos_state_file):
    chaos = chaos_state_file
    body = json.dumps({"model": "resilient-chat/resilient-chat", "messages": []}).encode()
    new_body, info = chaos.maybe_rewrite_body(body)
    assert new_body == body
    assert info is None


def test_unknown_scenario_raises(chaos_state_file):
    chaos = chaos_state_file
    with pytest.raises(ValueError):
        chaos.activate("nonexistent")
