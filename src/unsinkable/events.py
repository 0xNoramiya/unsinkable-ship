from __future__ import annotations

import atexit
import json
import logging
import queue
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Protocol

import httpx

log = logging.getLogger("unsinkable.events")


@dataclass
class RequestEvent:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ts: float = field(default_factory=time.time)
    method: str = ""
    url: str = ""
    requested_model: str | None = None
    resolved_model: str | None = None
    status_code: int | None = None
    latency_ms: float | None = None
    retried: bool = False
    error: str | None = None
    fallback_hops: list[str] = field(default_factory=list)
    kind: str = "llm"
    chaos: dict[str, str] | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class EventSink(Protocol):
    def emit(self, event: RequestEvent) -> None: ...


class NullSink:
    def emit(self, event: RequestEvent) -> None:
        return None


class HttpEventSink:
    """Background-drained POST sink. Errors are swallowed — the dashboard going
    down must never break the user's app."""

    def __init__(self, dashboard_url: str, timeout: float = 0.5) -> None:
        self.url = dashboard_url.rstrip("/") + "/events"
        self._client = httpx.Client(timeout=timeout)
        self._q: queue.Queue[RequestEvent | None] = queue.Queue(maxsize=1000)
        self._worker = threading.Thread(target=self._drain, daemon=True)
        self._worker.start()
        atexit.register(self._shutdown)

    def emit(self, event: RequestEvent) -> None:
        try:
            self._q.put_nowait(event)
        except queue.Full:
            log.debug("event queue full; dropping")

    def _drain(self) -> None:
        while True:
            event = self._q.get()
            if event is None:
                return
            try:
                self._client.post(
                    self.url,
                    content=event.to_json(),
                    headers={"content-type": "application/json"},
                )
            except Exception as e:  # noqa: BLE001
                log.debug("dashboard emit failed: %s", e)

    def _shutdown(self) -> None:
        deadline = time.monotonic() + 2.0
        while not self._q.empty() and time.monotonic() < deadline:
            time.sleep(0.02)
        try:
            self._q.put_nowait(None)
        except queue.Full:
            return
        self._worker.join(timeout=0.5)


def make_sink(dashboard_url: str | None) -> EventSink:
    if not dashboard_url:
        return NullSink()
    return HttpEventSink(dashboard_url)
