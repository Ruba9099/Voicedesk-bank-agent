from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\+?[0-9][0-9\- ]{4,19}$")]


class StartCallIn(BaseModel):
    caller_phone: Phone
    channel: Literal["web", "phone"] = "web"


class MessageIn(BaseModel):
    text: Text


class TurnOut(BaseModel):
    call_id: str
    status: str
    handler: str
    state: str
    authenticated: bool
    priority: str
    reply_text: str
    reply_speech: str
    end_call: bool


class TranscriptOut(BaseModel):
    id: int
    speaker: str
    text: str
    created_at: datetime


class CallOut(BaseModel):
    call_id: str
    status: str
    handler: str
    state: str
    authenticated: bool
    priority: str
    channel: str
    caller_phone: str
    operator_id: int | None
    started_at: datetime
    ended_at: datetime | None
    transcript: list[TranscriptOut]


class OperatorOut(BaseModel):
    id: int
    name: str
    status: str
    current_call_id: str | None


class OperatorStatusIn(BaseModel):
    status: Literal["available", "busy", "offline"]


class AcceptIn(BaseModel):
    call_id: str


class ComplaintOut(BaseModel):
    reference: str
    category: str
    priority: str
    status: str
    description: str
    call_id: str | None
    customer_id: int | None
    created_at: datetime


class ComplaintPatch(BaseModel):
    status: Literal["open", "in_progress", "resolved"]


class EventOut(BaseModel):
    id: int
    event_type: str
    call_id: str | None
    customer_id: int | None
    payload: dict = Field(default_factory=dict)
    created_at: datetime
