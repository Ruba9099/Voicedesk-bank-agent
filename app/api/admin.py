from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models, services
from ..schemas import (AcceptIn, CallOut, ComplaintOut, ComplaintPatch, EventOut, OperatorOut,
                       OperatorStatusIn)
from .calls import call_out
from .deps import commit_and_publish, get_db, get_settings_dep, require_api_key

router = APIRouter(prefix="/api/v1", tags=["admin"], dependencies=[Depends(require_api_key)])


def _op(o: models.Operator) -> OperatorOut:
    return OperatorOut(id=o.id, name=o.name, status=o.status, current_call_id=o.current_call_id)


# ---------------------------------------------------------------- operators
@router.get("/operators", response_model=list[OperatorOut])
async def list_operators(request: Request, db: Session = Depends(get_db), settings=Depends(get_settings_dep)):
    await commit_and_publish(request, db, services.sweep(db, settings, models.utcnow()))
    return [_op(o) for o in db.scalars(select(models.Operator).order_by(models.Operator.id)).all()]


@router.put("/operators/{operator_id}/status", response_model=OperatorOut)
async def set_status(operator_id: int, body: OperatorStatusIn, request: Request,
                     db: Session = Depends(get_db), settings=Depends(get_settings_dep)):
    op, events = services.set_operator_status(db, settings, operator_id, body.status)
    await commit_and_publish(request, db, events)
    return _op(op)


@router.post("/operators/{operator_id}/accept", response_model=CallOut,
             summary="Operator answers a ringing call")
async def accept(operator_id: int, body: AcceptIn, request: Request, db: Session = Depends(get_db),
                 settings=Depends(get_settings_dep)):
    call, events = services.accept_call(db, settings, operator_id, body.call_id)
    await commit_and_publish(request, db, events)
    return call_out(db, call)


# --------------------------------------------------------------- complaints
def _complaint(c: models.Complaint) -> ComplaintOut:
    return ComplaintOut(reference=c.reference, category=c.category, priority=c.priority, status=c.status,
                        description=c.description, call_id=c.call_id, customer_id=c.customer_id,
                        created_at=c.created_at)


@router.get("/complaints", response_model=list[ComplaintOut])
async def list_complaints(db: Session = Depends(get_db), status: str | None = None,
                          limit: int = Query(100, ge=1, le=500)):
    q = select(models.Complaint).order_by(models.Complaint.id.desc()).limit(limit)
    if status:
        q = q.where(models.Complaint.status == status)
    return [_complaint(c) for c in db.scalars(q).all()]


def _get_complaint(db: Session, reference: str) -> models.Complaint:
    c = db.scalars(select(models.Complaint).where(models.Complaint.reference == reference)).first()
    if c is None:
        raise HTTPException(404, "complaint not found")
    return c


@router.get("/complaints/{reference}", response_model=ComplaintOut)
async def get_complaint(reference: str, db: Session = Depends(get_db)):
    return _complaint(_get_complaint(db, reference))


@router.patch("/complaints/{reference}", response_model=ComplaintOut)
async def update_complaint(reference: str, body: ComplaintPatch, request: Request, db: Session = Depends(get_db)):
    c = _get_complaint(db, reference)
    c.status = body.status
    await commit_and_publish(request, db, [("complaint.updated", {"reference": c.reference, "status": c.status})])
    return _complaint(c)


# ------------------------------------------------------------ events / stats
@router.get("/events", response_model=list[EventOut], summary="Recent audited pub/sub events")
async def list_events(db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=500)):
    rows = db.scalars(select(models.AuditLog).order_by(models.AuditLog.id.desc()).limit(limit)).all()
    return [EventOut(id=r.id, event_type=r.event_type, call_id=r.call_id, customer_id=r.customer_id,
                     payload=r.payload or {}, created_at=r.created_at) for r in rows]


def _count(db: Session, col) -> dict[str, int]:
    return {k: v for k, v in db.execute(select(col, func.count()).group_by(col)).all()}


@router.get("/stats")
async def stats(request: Request, db: Session = Depends(get_db)):
    calls_total = db.scalar(select(func.count()).select_from(models.CallSession)) or 0
    active = db.scalar(select(func.count()).select_from(models.CallSession)
                       .where(models.CallSession.status != "ended")) or 0
    agent = db.scalar(select(func.count()).select_from(models.CallSession).where(
        models.CallSession.status.in_(("with_agent",)) | (models.CallSession.handler == "agent"))) or 0
    bus = request.app.state.bus
    return {
        "calls_total": calls_total,
        "calls_active": active,
        "calls_handled_by_agent": agent,
        "calls_handled_by_operator": calls_total - agent,
        "operators": _count(db, models.Operator.status),
        "complaints": _count(db, models.Complaint.status),
        "events_published": bus.published_count,
        "dead_letters": len(bus.dead_letters),
        "events_by_topic": dict(request.app.state.metrics),
    }
