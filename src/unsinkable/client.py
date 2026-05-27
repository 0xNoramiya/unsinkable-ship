from __future__ import annotations

import json
import time
from typing import Any

import httpx
from openai import AsyncOpenAI as _BaseAsyncOpenAI
from openai import OpenAI as _BaseOpenAI

from unsinkable.chaos import current_brownout, maybe_rewrite_body
from unsinkable.config import get_settings
from unsinkable.events import EventSink, RequestEvent, make_sink


def _extract_requested_model(request: httpx.Request) -> str | None:
    if request.method != "POST":
        return None
    try:
        body = json.loads(request.content.decode("utf-8") or "{}")
    except Exception:  # noqa: BLE001
        return None
    return body.get("model") if isinstance(body, dict) else None


def _apply_chaos(request: httpx.Request) -> tuple[httpx.Request, dict[str, str] | None]:
    if request.method != "POST":
        return request, None
    new_body, chaos_info = maybe_rewrite_body(request.content)
    if chaos_info is None:
        return request, None
    headers = httpx.Headers({k: v for k, v in request.headers.items()
                              if k.lower() != "content-length"})
    new_request = httpx.Request(
        method=request.method,
        url=request.url,
        headers=headers,
        content=new_body,
        extensions=request.extensions,
    )
    return new_request, chaos_info


def _extract_resolved_model(response: httpx.Response) -> str | None:
    # TF Virtual Models set this header to the target that actually answered.
    resolved = response.headers.get("x-tfy-resolved-model")
    if resolved:
        return resolved
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        return None
    return body.get("model") if isinstance(body, dict) else None


def _extract_token_usage(response: httpx.Response) -> tuple[int | None, int | None]:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        return None, None
    usage = body.get("usage") if isinstance(body, dict) else None
    if not isinstance(usage, dict):
        return None, None
    return usage.get("prompt_tokens"), usage.get("completion_tokens")


def _extract_fallback_hops(response: httpx.Response) -> list[str]:
    raw = response.headers.get("x-tfy-fallback-chain") or response.headers.get(
        "x-tfy-attempted-targets"
    )
    if not raw:
        return []
    return [hop.strip() for hop in raw.split(",") if hop.strip()]


class _InstrumentedSyncTransport(httpx.HTTPTransport):
    def __init__(self, sink: EventSink, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._sink = sink

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        start = time.perf_counter()
        requested = _extract_requested_model(request)
        request, chaos = _apply_chaos(request)
        brownout = current_brownout()
        if brownout > 0 and request.method == "POST":
            time.sleep(brownout)
        try:
            response = super().handle_request(request)
        except Exception as exc:  # noqa: BLE001
            self._sink.emit(
                RequestEvent(
                    method=request.method,
                    url=str(request.url),
                    requested_model=requested,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    error=f"{type(exc).__name__}: {exc}",
                    chaos=chaos,
                )
            )
            raise

        response.read()
        prompt_tokens, completion_tokens = _extract_token_usage(response)
        self._sink.emit(
            RequestEvent(
                method=request.method,
                url=str(request.url),
                requested_model=requested,
                resolved_model=_extract_resolved_model(response),
                status_code=response.status_code,
                latency_ms=(time.perf_counter() - start) * 1000,
                fallback_hops=_extract_fallback_hops(response),
                chaos=chaos,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )
        return response


class _InstrumentedAsyncTransport(httpx.AsyncHTTPTransport):
    def __init__(self, sink: EventSink, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._sink = sink

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        start = time.perf_counter()
        requested = _extract_requested_model(request)
        request, chaos = _apply_chaos(request)
        brownout = current_brownout()
        if brownout > 0 and request.method == "POST":
            time.sleep(brownout)
        try:
            response = await super().handle_async_request(request)
        except Exception as exc:  # noqa: BLE001
            self._sink.emit(
                RequestEvent(
                    method=request.method,
                    url=str(request.url),
                    requested_model=requested,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    error=f"{type(exc).__name__}: {exc}",
                    chaos=chaos,
                )
            )
            raise

        await response.aread()
        prompt_tokens, completion_tokens = _extract_token_usage(response)
        self._sink.emit(
            RequestEvent(
                method=request.method,
                url=str(request.url),
                requested_model=requested,
                resolved_model=_extract_resolved_model(response),
                status_code=response.status_code,
                latency_ms=(time.perf_counter() - start) * 1000,
                fallback_hops=_extract_fallback_hops(response),
                chaos=chaos,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )
        return response


def _wire(kwargs: dict[str, Any], async_mode: bool) -> dict[str, Any]:
    settings = get_settings()
    kwargs.setdefault("base_url", settings.openai_base_url)
    kwargs.setdefault("api_key", settings.tfy_api_key)
    if "http_client" not in kwargs:
        sink = make_sink(settings.unsinkable_dashboard_url)
        transport_cls = _InstrumentedAsyncTransport if async_mode else _InstrumentedSyncTransport
        client_cls = httpx.AsyncClient if async_mode else httpx.Client
        kwargs["http_client"] = client_cls(transport=transport_cls(sink))
    return kwargs


class OpenAI(_BaseOpenAI):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**_wire(kwargs, async_mode=False))


class AsyncOpenAI(_BaseAsyncOpenAI):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**_wire(kwargs, async_mode=True))
