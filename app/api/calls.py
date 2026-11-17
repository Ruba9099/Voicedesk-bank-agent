from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, services
from ..schemas import CallOut, MessageIn, StartCallIn, TranscriptOut, TurnOut
from .deps import commit_and_publish, get_db, get_settings_dep, require_api_key, turn_out

router = APIRouter(prefix="/api/v1/calls", tags=["calls"])


def call_out(db: Session, call: models.CallSession) -> CallOut:
    rows = db.scalars(select(models.Transcript).where(models.Transcript.call_id == call.id)
                      .order_by(models.Transcript.id)).all()
    return CallOut(
        call_id=call.id, status=call.status, handler=call.handler, state=call.state,
        authenticated=bool((call.context or {}).get("customer_id")), priority=call.priority,
        channel=call.channel, caller_phone=call.caller_phone, operator_id=call.operator_id,
        started_at=call.started_at, ended_at=call.ended_at,
        transcript=[TranscriptOut(id=t.id, speaker=t.speaker, text=t.text, created_at=t.created_at) for t in rows])


@router.post("", response_model=TurnOut, status_code=201, summary="Start a call (operator-first routing)")
async def start_call(body: StartCallIn, request: Request, db: Session = Depends(get_db),
                     settings=Depends(get_settings_dep)):
    turn = services.start_call(db, settings, body.caller_phone, body.channel)
    await commit_and_publish(request, db, turn.events)
    return turn_out(turn)


@router.get("", response_model=list[CallOut], dependencies=[Depends(require_api_key)],
            summary="List recent calls (admin)")
async def list_calls(db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=200)):
    calls = db.scalars(select(models.CallSession).order_by(models.CallSession.started_at.desc()).limit(limit)).all()
    return [call_out(db, c) for c in calls]


@router.post("/{call_id}/message", response_model=TurnOut, summary="Send what the caller said (text of the speech)")
async def message(call_id: str, body: MessageIn, request: Request, db: Session = Depends(get_db),
                  settings=Depends(get_settings_dep)):
    turn = services.process_message(db, settings, call_id, body.text)
    await commit_and_publish(request, db, turn.events)
    return turn_out(turn)


@router.get("/{call_id}", response_model=CallOut, summary="Call state and redacted transcript")
async def get_call(call_id: str, request: Request, db: Session = Depends(get_db),
                   settings=Depends(get_settings_dep)):
    call = services.get_call(db, call_id)
    events = services.sweep_call(db, settings, call, models.utcnow())
    await commit_and_publish(request, db, events)
    return call_out(db, call)


@router.post("/{call_id}/end", response_model=CallOut, summary="Hang up")
async def end_call(call_id: str, request: Request, db: Session = Depends(get_db)):
    call = services.get_call(db, call_id)
    events = services.end_call(db, call, models.utcnow(), reason="hangup")
    await commit_and_publish(request, db, events)
    return call_out(db, call)
