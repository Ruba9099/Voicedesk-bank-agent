from typing import AsyncIterator

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .. import security
from ..config import Settings
from ..schemas import TurnOut
from ..services import Turn


async def get_db(request: Request) -> AsyncIterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    if not security.api_key_ok(x_api_key, request.app.state.settings.api_key):
        raise HTTPException(status_code=401, detail="invalid or missing API key")


async def commit_and_publish(request: Request, db: Session, events: list) -> None:
    """Outbox pattern: persist first, then publish to subscribers."""
    db.commit()
    await request.app.state.bus.publish_many(events)


def turn_out(turn: Turn) -> TurnOut:
    call = turn.call
    return TurnOut(
        call_id=call.id, status=call.status, handler=call.handler, state=call.state,
        authenticated=bool((call.context or {}).get("customer_id")), priority=call.priority,
        reply_text=turn.reply.text, reply_speech=turn.reply.speech, end_call=turn.reply.end_call)


__all__ = ["get_db", "get_settings_dep", "require_api_key", "commit_and_publish", "turn_out", "Depends"]
