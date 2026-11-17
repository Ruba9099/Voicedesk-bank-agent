"""Operator-first call routing.

An incoming call rings an available operator. If nobody is available, or the
ringing operator does not answer within the timeout, the voice agent takes
over (see services.py). Operator claims use a single conditional UPDATE so two
simultaneous calls can never reserve the same operator.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import models


def claim_operator(db: Session, operator_id: int, call_id: str, now: datetime | None = None) -> bool:
    result = db.execute(
        update(models.Operator)
        .where(models.Operator.id == operator_id, models.Operator.status == "available")
        .values(status="ringing", current_call_id=call_id, last_assigned_at=now or models.utcnow())
    )
    return result.rowcount == 1


def assign_operator(db: Session, call: models.CallSession, now: datetime) -> models.Operator | None:
    """Reserve the longest-idle available operator for this call, if any."""
    candidates = db.scalars(
        select(models.Operator)
        .where(models.Operator.status == "available")
        .order_by(models.Operator.last_assigned_at, models.Operator.id)
    ).all()
    for op in candidates:
        if claim_operator(db, op.id, call.id, now):
            db.refresh(op)
            call.operator_id = op.id
            return op
    return None


def release_operator(db: Session, call: models.CallSession, clear_assignment: bool = False) -> None:
    if call.operator_id is None:
        return
    op = db.get(models.Operator, call.operator_id)
    if op is not None and op.current_call_id == call.id:
        op.current_call_id = None
        if op.status in ("ringing", "busy"):
            op.status = "available"
    if clear_assignment:
        call.operator_id = None
