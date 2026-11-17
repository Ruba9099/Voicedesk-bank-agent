"""In-process publish/subscribe event bus.

Topics are dotted strings ("card.blocked"). Subscriptions may use fnmatch
patterns ("call.*", "*"). Handlers may be sync or async and run in
subscription order. A failing handler never blocks the others; the failure
is recorded in ``dead_letters``.
"""
from __future__ import annotations

import inspect
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from typing import Any, Awaitable, Callable

logger = logging.getLogger("voicedesk.events")


@dataclass(frozen=True)
class Event:
    topic: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


Handler = Callable[[Event], Any | Awaitable[Any]]


class EventBus:
    def __init__(self) -> None:
        self._subs: list[tuple[str, Handler]] = []
        self.dead_letters: deque[dict[str, Any]] = deque(maxlen=200)
        self.published_count = 0

    def subscribe(self, pattern: str, handler: Handler) -> Callable[[], None]:
        entry = (pattern, handler)
        self._subs.append(entry)

        def unsubscribe() -> None:
            if entry in self._subs:
                self._subs.remove(entry)

        return unsubscribe

    async def publish(self, topic: str, payload: dict[str, Any] | None = None) -> Event:
        event = Event(topic=topic, payload=dict(payload or {}))
        self.published_count += 1
        for pattern, handler in list(self._subs):
            if not fnmatchcase(topic, pattern):
                continue
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # noqa: BLE001 - isolate subscriber failures
                logger.exception("event handler failed for %s", topic)
                self.dead_letters.append(
                    {"topic": topic, "pattern": pattern, "error": repr(exc), "event_id": event.id}
                )
        return event

    async def publish_many(self, items: list[tuple[str, dict[str, Any]]]) -> list[Event]:
        return [await self.publish(topic, payload) for topic, payload in items]
