"""Pub/sub subscribers: audit log, SMS notifications, metrics and live WebSocket feed."""
from __future__ import annotations

from collections import Counter
from typing import Callable

from fastapi import WebSocket
from sqlalchemy.orm import Session, sessionmaker

from . import models
from .config import Settings
from .events import Event, EventBus

_SECRET_KEYS = {"pin", "cnic", "dob", "password", "otp"}


def sanitize(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k.lower() not in _SECRET_KEYS}


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.connections.discard(ws)

    async def broadcast(self, message: dict) -> None:
        for ws in list(self.connections):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 - drop dead sockets
                self.disconnect(ws)


def _sms_text(settings: Settings, topic: str, p: dict) -> str | None:
    bank, phone = settings.bank_name, settings.bank_phone
    last4 = p.get("card_last4", "")
    return {
        "card.blocked": f"{bank}: your card ending {last4} has been blocked. Not you? Call {phone} now.",
        "card.activated": f"{bank}: your card ending {last4} is now active.",
        "pin.changed": f"{bank}: the PIN for your card ending {last4} was changed. Not you? Call {phone} now.",
        "address.changed": f"{bank}: your address on file was updated. Not you? Call {phone} now.",
        "complaint.created": f"{bank}: complaint {p.get('reference', '')} registered. We will contact you shortly.",
    }.get(topic)


def register_subscribers(bus: EventBus, session_factory: sessionmaker[Session], ws: ConnectionManager,
                         settings: Settings) -> Counter:
    metrics: Counter = Counter()

    def audit(event: Event) -> None:
        payload = sanitize(event.payload)
        with session_factory() as db:
            db.add(models.AuditLog(
                event_id=event.id, event_type=event.topic, call_id=payload.get("call_id"),
                customer_id=payload.get("customer_id"), payload=payload))
            db.commit()

    def notify(event: Event) -> None:
        customer_id = event.payload.get("customer_id")
        text = _sms_text(settings, event.topic, event.payload)
        if not customer_id or not text:
            return
        with session_factory() as db:
            db.add(models.Notification(customer_id=customer_id, channel="sms", message=text))
            db.commit()

    def count(event: Event) -> None:
        metrics[event.topic] += 1

    async def live(event: Event) -> None:
        await ws.broadcast({"id": event.id, "topic": event.topic, "payload": sanitize(event.payload),
                            "timestamp": event.timestamp.isoformat()})

    bus.subscribe("*", audit)
    bus.subscribe("card.*", notify)
    bus.subscribe("pin.*", notify)
    bus.subscribe("address.*", notify)
    bus.subscribe("complaint.*", notify)
    bus.subscribe("*", count)
    bus.subscribe("*", live)
    return metrics
