from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

EPOCH = datetime(1970, 1, 1)


def utcnow() -> datetime:
    """Naive UTC timestamp (stored without tzinfo for SQLite/MySQL parity)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    cnic_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cnic_masked: Mapped[str] = mapped_column(String(20))
    dob: Mapped[date] = mapped_column(Date)
    phone: Mapped[str] = mapped_column(String(20))
    address: Mapped[str] = mapped_column(String(255))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    account_number: Mapped[str] = mapped_column(String(24), unique=True)
    account_type: Mapped[str] = mapped_column(String(20))
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="PKR")
    status: Mapped[str] = mapped_column(String(12), default="active")


class Card(Base):
    __tablename__ = "cards"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    card_last4: Mapped[str] = mapped_column(String(4))
    card_type: Mapped[str] = mapped_column(String(10))  # debit | credit
    status: Mapped[str] = mapped_column(String(10), default="inactive")  # inactive | active | blocked
    pin_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pin_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pin_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Operator(Base):
    __tablename__ = "operators"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(10), default="offline")  # available|ringing|busy|offline
    current_call_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_assigned_at: Mapped[datetime] = mapped_column(DateTime, default=EPOCH)


class CallSession(Base):
    __tablename__ = "calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    caller_phone: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str] = mapped_column(String(10), default="web")
    handler: Mapped[str] = mapped_column(String(10), default="agent")  # agent | operator
    status: Mapped[str] = mapped_column(String(20), default="with_agent")
    state: Mapped[str] = mapped_column(String(32), default="menu")
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("operators.id"), nullable=True)
    auth_attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ring_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Transcript(Base):
    __tablename__ = "transcripts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), index=True)
    speaker: Mapped[str] = mapped_column(String(10))  # caller | agent
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    call_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    caller_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    category: Mapped[str] = mapped_column(String(30))
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open|in_progress|resolved
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32))
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    call_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    """Simulated SMS outbox (a real SMS gateway would consume this table)."""

    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    channel: Mapped[str] = mapped_column(String(10), default="sms")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AddressHistory(Base):
    __tablename__ = "address_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    old_address: Mapped[str] = mapped_column(String(255))
    new_address: Mapped[str] = mapped_column(String(255))
    call_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
