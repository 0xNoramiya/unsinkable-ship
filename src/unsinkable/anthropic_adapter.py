"""Anthropic SDK-compatible adapter that routes through the TF OpenAI-compatible
gateway. Translates Anthropic Messages API <-> OpenAI Chat Completions API so
existing `from anthropic import Anthropic` call sites can swap to
`from unsinkable import Anthropic` and inherit gateway-side resilience.

Supports messages.create(model, messages, max_tokens, system, temperature,
stop_sequences, top_p). Tool use and streaming are not yet translated; for
those, use unsinkable.OpenAI directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from unsinkable.client import AsyncOpenAI, OpenAI


@dataclass
class _TextBlock:
    text: str
    type: str = "text"


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Message:
    """Anthropic-shaped Message returned by messages.create()."""

    id: str
    model: str
    role: str = "assistant"
    type: str = "message"
    stop_reason: str | None = None
    stop_sequence: str | None = None
    content: list[_TextBlock] = field(default_factory=list)
    usage: _Usage = field(default_factory=_Usage)


_OPENAI_TO_ANTHROPIC_STOP = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "stop_sequence",
}


def _normalize_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def _to_openai_messages(messages: list[dict], system: str | None) -> list[dict]:
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        out.append({"role": m["role"], "content": _normalize_content(m.get("content", ""))})
    return out


def _build_create_kwargs(
    model: str,
    messages: list[dict],
    max_tokens: int,
    system: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    stop_sequences: list[str] | None = None,
    **extra: Any,
) -> dict:
    body: dict[str, Any] = {
        "model": model,
        "messages": _to_openai_messages(messages, system),
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        body["temperature"] = temperature
    if top_p is not None:
        body["top_p"] = top_p
    if stop_sequences:
        body["stop"] = stop_sequences
    # Pass through any extra kwargs the caller used that map cleanly
    for k, v in extra.items():
        body[k] = v
    return body


def _response_to_message(resp: Any) -> Message:
    choice = resp.choices[0]
    text = (choice.message.content or "") if choice.message else ""
    usage = getattr(resp, "usage", None)
    return Message(
        id=getattr(resp, "id", ""),
        model=getattr(resp, "model", ""),
        stop_reason=_OPENAI_TO_ANTHROPIC_STOP.get(choice.finish_reason or "", choice.finish_reason),
        content=[_TextBlock(text=text)],
        usage=_Usage(
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
        ),
    )


class _Messages:
    def __init__(self, client: OpenAI) -> None:
        self._client = client

    def create(self, **kwargs: Any) -> Message:
        body = _build_create_kwargs(**kwargs)
        resp = self._client.chat.completions.create(**body)
        return _response_to_message(resp)


class _AsyncMessages:
    def __init__(self, client: AsyncOpenAI) -> None:
        self._client = client

    async def create(self, **kwargs: Any) -> Message:
        body = _build_create_kwargs(**kwargs)
        resp = await self._client.chat.completions.create(**body)
        return _response_to_message(resp)


class Anthropic:
    """Drop-in adapter for anthropic.Anthropic that routes through TF's
    OpenAI-compatible gateway. Use Virtual Model names for `model`
    (e.g. 'resilient-chat/resilient-chat' or 'anthropic/claude-sonnet-4-6')."""

    def __init__(self, **kwargs: Any) -> None:
        # anthropic-specific kwargs are accepted and dropped; unsinkable.OpenAI
        # handles base_url/api_key injection from env vars.
        for drop in ("auth_token", "default_headers", "default_query"):
            kwargs.pop(drop, None)
        self._client = OpenAI(**kwargs)
        self.messages = _Messages(self._client)


class AsyncAnthropic:
    """Async variant of Anthropic. messages.create returns an awaitable."""

    def __init__(self, **kwargs: Any) -> None:
        for drop in ("auth_token", "default_headers", "default_query"):
            kwargs.pop(drop, None)
        self._client = AsyncOpenAI(**kwargs)
        self.messages = _AsyncMessages(self._client)
