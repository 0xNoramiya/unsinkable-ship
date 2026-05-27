"""Anthropic adapter — request/response translation without live network."""

from unsinkable.anthropic_adapter import (
    _build_create_kwargs,
    _normalize_content,
    _response_to_message,
    _Usage,
)


class _FakeUsage:
    prompt_tokens = 12
    completion_tokens = 7


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, text="hi from gateway", finish_reason="stop"):
        self.message = _FakeMessage(text)
        self.finish_reason = finish_reason


class _FakeResp:
    id = "msg_abc"
    model = "gpt-4o-mini-2024-07-18"
    usage = _FakeUsage()

    def __init__(self, finish_reason="stop"):
        self.choices = [_FakeChoice(finish_reason=finish_reason)]


def test_normalize_string_content():
    assert _normalize_content("plain") == "plain"


def test_normalize_block_content():
    blocks = [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]
    assert _normalize_content(blocks) == "first\nsecond"


def test_build_kwargs_injects_system_as_first_message():
    body = _build_create_kwargs(
        model="resilient-chat/resilient-chat",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=50,
        system="You are helpful.",
        temperature=0.7,
    )
    assert body["model"] == "resilient-chat/resilient-chat"
    assert body["max_tokens"] == 50
    assert body["temperature"] == 0.7
    assert body["messages"][0] == {"role": "system", "content": "You are helpful."}
    assert body["messages"][1] == {"role": "user", "content": "hi"}


def test_build_kwargs_omits_system_when_absent():
    body = _build_create_kwargs(
        model="x", messages=[{"role": "user", "content": "hi"}], max_tokens=10,
    )
    assert all(m["role"] != "system" for m in body["messages"])


def test_stop_sequences_become_stop():
    body = _build_create_kwargs(
        model="x", messages=[{"role": "user", "content": "hi"}], max_tokens=10,
        stop_sequences=["END"],
    )
    assert body["stop"] == ["END"]


def test_response_to_message_translates_stop_reason():
    msg = _response_to_message(_FakeResp(finish_reason="stop"))
    assert msg.role == "assistant"
    assert msg.stop_reason == "end_turn"
    assert msg.content[0].text == "hi from gateway"
    assert msg.usage.input_tokens == 12
    assert msg.usage.output_tokens == 7


def test_response_to_message_length_becomes_max_tokens():
    msg = _response_to_message(_FakeResp(finish_reason="length"))
    assert msg.stop_reason == "max_tokens"


def test_response_to_message_passes_unknown_reason_through():
    msg = _response_to_message(_FakeResp(finish_reason="some_new_value"))
    assert msg.stop_reason == "some_new_value"
