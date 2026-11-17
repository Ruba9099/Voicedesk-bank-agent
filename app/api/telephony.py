"""Twilio-compatible voice webhook. Uses the same dialog engine as the REST API.

Spoken PINs are avoided on the phone channel: PIN states ask for keypad (DTMF)
digits only.
"""
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, security, services
from ..agent.dialog import to_speech
from .deps import commit_and_publish, get_db, get_settings_dep

router = APIRouter(prefix="/telephony", tags=["telephony"])

_DTMF_STATES = {"pin_new": 4, "pin_confirm": 4}


def _xml(body: str) -> Response:
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>',
                    media_type="application/xml")


def build_gather_twiml(text: str, state: str, action: str) -> str:
    say = escape(to_speech(text))
    if state in _DTMF_STATES:
        attrs = f'input="dtmf" numDigits="{_DTMF_STATES[state]}" timeout="8"'
    else:
        attrs = 'input="speech dtmf" speechTimeout="auto" timeout="6" finishOnKey="#"'
    return (f'<?xml version="1.0" encoding="UTF-8"?><Response><Gather {attrs} action="{action}" method="POST">'
            f"<Say>{say}</Say></Gather><Say>We did not receive any input. Goodbye.</Say><Hangup/></Response>")


def _gather(text: str, state: str) -> Response:
    return Response(build_gather_twiml(text, state, "/telephony/gather"), media_type="application/xml")


async def verify_twilio(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    if settings.twilio_auth_token:
        base = settings.public_base_url.rstrip("/")
        url = f"{base}{request.url.path}" if base else str(request.url)
        if not security.verify_twilio_signature(settings.twilio_auth_token, url, params,
                                                request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(403, "invalid Twilio signature")
    return params


def _last_agent_text(db: Session, call_id: str) -> str:
    row = db.scalars(select(models.Transcript).where(
        models.Transcript.call_id == call_id, models.Transcript.speaker == "agent"
    ).order_by(models.Transcript.id.desc())).first()
    return row.text if row else "How can I help you?"


def _hold(call, settings) -> Response:
    pause = settings.ring_timeout_seconds + 1
    return _xml(f'<Say>Please hold while we connect you to an operator.</Say><Pause length="{pause}"/>'
                '<Redirect method="POST">/telephony/resume</Redirect>')


@router.post("/incoming", summary="Twilio voice webhook: a new call arrives")
async def incoming(request: Request, db: Session = Depends(get_db), settings=Depends(get_settings_dep),
                   params: dict = Depends(verify_twilio)):
    turn = services.start_call(db, settings, params.get("From", "unknown")[:20] or "unknown",
                               channel="phone", external_id=params.get("CallSid"))
    await commit_and_publish(request, db, turn.events)
    if turn.call.status == "ringing_operator":
        return _hold(turn.call, settings)
    return _gather(turn.reply.text, turn.call.state)


@router.post("/resume", summary="After the operator ring window: operator, or the agent takes over")
async def resume(request: Request, db: Session = Depends(get_db), settings=Depends(get_settings_dep),
                 params: dict = Depends(verify_twilio)):
    call = db.scalars(select(models.CallSession).where(
        models.CallSession.external_id == params.get("CallSid"))).first()
    if call is None:
        return _xml("<Say>Sorry, something went wrong. Goodbye.</Say><Hangup/>")
    await commit_and_publish(request, db, services.sweep_call(db, settings, call, models.utcnow()))
    if call.status == "with_operator":
        if settings.operator_dial_number:
            return _xml(f"<Dial>{escape(settings.operator_dial_number)}</Dial>")
        return _xml("<Say>You are now connected to an operator.</Say><Hangup/>")
    if call.status == "with_agent":
        return _gather(_last_agent_text(db, call.id), call.state)
    return _hold(call, settings)


@router.post("/gather", summary="Twilio voice webhook: the caller spoke or pressed keys")
async def gather(request: Request, db: Session = Depends(get_db), settings=Depends(get_settings_dep),
                 params: dict = Depends(verify_twilio)):
    call = db.scalars(select(models.CallSession).where(
        models.CallSession.external_id == params.get("CallSid"))).first()
    if call is None or call.status == "ended":
        return _xml("<Say>Sorry, I could not find your call. Goodbye.</Say><Hangup/>")
    text = (params.get("SpeechResult") or params.get("Digits") or "").strip()
    if not text:
        return _gather("Sorry, I didn't hear anything. Could you please repeat that?", call.state)
    try:
        turn = services.process_message(db, settings, call.id, text)
    except services.ServiceError:
        return _xml("<Say>Please hold while we connect you.</Say><Hangup/>")
    await commit_and_publish(request, db, turn.events)
    if turn.reply.end_call:
        return _xml(f"<Say>{escape(turn.reply.speech)}</Say><Hangup/>")
    if turn.call.status == "ringing_operator":
        return _hold(turn.call, settings)
    return _gather(turn.reply.text, turn.call.state)
