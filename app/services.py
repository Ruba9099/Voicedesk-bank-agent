"""Call lifecycle services. Functions mutate the DB session and return the pub/sub
events to publish; the API layer commits first and publishes afterwards (outbox
pattern), so subscribers never observe uncommitted state."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, routing, security
from .agent import dialog
from .agent.dialog import DialogEngine, Reply, State
from .config import Settings

Event = tuple[str, dict]
_MONEY = re.compile(r"(PKR|USD|EUR)\s?[\d,]+(?:\.\d+)?")


class ServiceError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class Turn:
    call: models.CallSession
    reply: Reply
    events: list[Event]


# -------------------------------------------------------------- transcripts
def _log(db: Session, call_id: str, speaker: str, text: str, now: datetime) -> None:
    db.add(models.Transcript(call_id=call_id, speaker=speaker, text=text, created_at=now))


def _log_caller(db, call, text: str, now) -> None:
    if State(call.state) in dialog.REDACT_STATES:
        stored = "[REDACTED]"
    else:
        stored = security.redact_digits(text)
    _log(db, call.id, "caller", stored, now)


def _log_agent(db, call_id: str, reply: Reply, now) -> None:
    stored = reply.log_text if reply.log_text is not None else reply.text
    _log(db, call_id, "agent", _MONEY.sub(r"\1 [AMOUNT]", stored), now)


# ---------------------------------------------------------------- lifecycle
def start_call(db: Session, settings: Settings, caller_phone: str, channel: str = "web",
               external_id: str | None = None, now: datetime | None = None) -> Turn:
    now = now or models.utcnow()
    call = models.CallSession(id=str(uuid.uuid4()), external_id=external_id, caller_phone=caller_phone,
                              channel=channel, started_at=now, status="with_agent", handler="agent",
                              state=State.MENU.value, context={}, priority="normal")
    db.add(call)
    db.flush()
    events: list[Event] = [("call.started", {"call_id": call.id, "channel": channel})]
    op = routing.assign_operator(db, call, now)
    if op:
        call.status, call.handler = "ringing_operator", "operator"
        call.ring_deadline = now + timedelta(seconds=settings.ring_timeout_seconds)
        reply = Reply(f"Thank you for calling {settings.bank_name}. Please hold while we connect you "
                      "to an available operator.", transfer=True)
        events.append(("call.routed", {"call_id": call.id, "target": "operator", "operator_id": op.id}))
    else:
        reply = DialogEngine(db, settings, now).greeting()
        events.append(("call.routed", {"call_id": call.id, "target": "agent", "reason": "no_operator_available"}))
    _log_agent(db, call.id, reply, now)
    return Turn(call, reply, events)


def end_call(db: Session, call: models.CallSession, now: datetime, reason: str = "completed") -> list[Event]:
    if call.status == "ended":
        return []
    handler = call.handler
    routing.release_operator(db, call)
    call.status = "ended"
    call.ended_at = now
    call.ring_deadline = None
    duration = int((now - call.started_at).total_seconds())
    return [("call.ended", {"call_id": call.id, "handler": handler, "duration_seconds": duration,
                            "reason": reason})]


def fallback_to_agent(db: Session, settings: Settings, call: models.CallSession, now: datetime,
                      reason: str) -> list[Event]:
    routing.release_operator(db, call, clear_assignment=True)
    call.status, call.handler, call.ring_deadline = "with_agent", "agent", None
    ctx = dict(call.context or {})
    dialog.reset_flow(ctx)
    call.context = ctx
    call.state = State.MENU.value
    reply = Reply("I'm sorry, our operators are still busy, so I'll take care of you right away. " + dialog.MENU_HELP)
    _log_agent(db, call.id, reply, now)
    return [("call.fallback_to_agent", {"call_id": call.id, "reason": reason})]


def _ring_failed(db: Session, call: models.CallSession, now: datetime) -> str | None:
    if call.status != "ringing_operator":
        return None
    op = db.get(models.Operator, call.operator_id) if call.operator_id else None
    if op is None or op.status != "ringing" or op.current_call_id != call.id:
        return "operator_unavailable"
    if call.ring_deadline is not None and call.ring_deadline <= now:
        return "ring_timeout"
    return None


def sweep_call(db: Session, settings: Settings, call: models.CallSession, now: datetime) -> list[Event]:
    reason = _ring_failed(db, call, now)
    return fallback_to_agent(db, settings, call, now, reason) if reason else []


def sweep(db: Session, settings: Settings, now: datetime) -> list[Event]:
    events: list[Event] = []
    for call in db.scalars(select(models.CallSession).where(models.CallSession.status == "ringing_operator")).all():
        events += sweep_call(db, settings, call, now)
    return events


def get_call(db: Session, call_id: str) -> models.CallSession:
    call = db.get(models.CallSession, call_id)
    if call is None:
        raise ServiceError(404, "call not found")
    return call


def process_message(db: Session, settings: Settings, call_id: str, text: str,
                    now: datetime | None = None) -> Turn:
    now = now or models.utcnow()
    call = get_call(db, call_id)
    if call.status == "ended":
        raise ServiceError(409, "call has ended")
    events = sweep_call(db, settings, call, now)
    if call.status == "with_operator":
        raise ServiceError(409, "this call is being handled by a human operator")
    _log_caller(db, call, text, now)
    if call.status == "ringing_operator":
        reply = Reply("Please hold. We are connecting you to an operator.", transfer=True)
        _log_agent(db, call.id, reply, now)
        return Turn(call, reply, events)
    reply = DialogEngine(db, settings, now).handle(call, text)
    _log_agent(db, call.id, reply, now)
    events += reply.events
    if reply.end_call:
        events += end_call(db, call, now, reason="completed")
    return Turn(call, reply, events)


# ---------------------------------------------------------------- operators
def set_operator_status(db: Session, settings: Settings, operator_id: int, status: str,
                        now: datetime | None = None) -> tuple[models.Operator, list[Event]]:
    now = now or models.utcnow()
    op = db.get(models.Operator, operator_id)
    if op is None:
        raise ServiceError(404, "operator not found")
    events: list[Event] = []
    if op.status == "busy" and op.current_call_id:
        raise ServiceError(409, "operator has an active call; end it first")
    if op.status == "ringing" and op.current_call_id:
        call = db.get(models.CallSession, op.current_call_id)
        if call is not None and call.status == "ringing_operator":
            events += fallback_to_agent(db, settings, call, now, "operator_unavailable")
    op.status = status
    events.append(("operator.status_changed", {"operator_id": op.id, "status": status}))
    return op, events


def accept_call(db: Session, settings: Settings, operator_id: int, call_id: str,
                now: datetime | None = None) -> tuple[models.CallSession, list[Event]]:
    now = now or models.utcnow()
    op = db.get(models.Operator, operator_id)
    call = get_call(db, call_id)
    if op is None:
        raise ServiceError(404, "operator not found")
    events = sweep_call(db, settings, call, now)
    if (call.status != "ringing_operator" or call.operator_id != op.id
            or op.status != "ringing" or op.current_call_id != call.id):
        raise ServiceError(409, "this call is not ringing for that operator")
    op.status = "busy"
    call.status, call.handler = "with_operator", "operator"
    call.accepted_at, call.ring_deadline = now, None
    events.append(("call.operator_accepted", {"call_id": call.id, "operator_id": op.id}))
    return call, events
