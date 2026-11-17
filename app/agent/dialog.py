"""Deterministic dialog engine for the voice agent.

Every sentence the agent speaks is either a fixed script or is filled from the
database. There is no generative model, so the agent cannot invent balances,
policies, rates or promises it does not have.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, routing, security
from ..config import Settings
from . import nlu
from .nlu import Intent


class State(str, Enum):
    MENU = "menu"
    AUTH_CNIC = "auth_cnic"
    AUTH_DOB = "auth_dob"
    CARD_SELECT = "card_select"
    CONFIRM_BLOCK = "confirm_block"
    ACTIVATE_VERIFY = "activate_verify"
    PIN_NEW = "pin_new"
    PIN_CONFIRM = "pin_confirm"
    ADDR_NEW = "addr_new"
    ADDR_CONFIRM = "addr_confirm"
    COMPLAINT_DESC = "complaint_desc"
    ASK_BLOCK_AFTER_COMPLAINT = "ask_block_after_complaint"
    ASK_COMPLAINT_AFTER_BLOCK = "ask_complaint_after_block"


# Caller speech in these states is sensitive and is never written to transcripts.
REDACT_STATES = {State.AUTH_CNIC, State.AUTH_DOB, State.PIN_NEW, State.PIN_CONFIRM,
                 State.ACTIVATE_VERIFY, State.ADDR_NEW}
DIGIT_STATES = {State.AUTH_CNIC, State.AUTH_DOB, State.PIN_NEW, State.PIN_CONFIRM, State.ACTIVATE_VERIFY}
FREE_TEXT_STATES = {State.ADDR_NEW, State.COMPLAINT_DESC}

AUTH_REQUIRED = {Intent.BALANCE, Intent.CARD_BLOCK, Intent.CARD_ACTIVATE,
                 Intent.CHANGE_PIN, Intent.CHANGE_ADDRESS, Intent.COMPLAINT}
HIGH_PRIORITY_CATEGORIES = {"card_misuse", "unauthorized_transaction", "account_misuse"}
FLOW_KEYS = ("pending_intent", "action", "card_id", "candidates", "reason", "category",
             "pending_pin_hash", "pending_pin_salt", "new_address", "cnic_hash", "errors", "unknown")

GREETING = ("Thank you for calling {bank}. I'm your virtual assistant. I can help with balance inquiry, "
            "blocking or activating a card, changing your PIN or address, or registering a complaint. "
            "How can I help you today?")
MENU_HELP = ("I can help with balance inquiry, blocking a card, card activation, changing your PIN, "
             "changing your address, or registering a complaint. Which would you like?")
ANYTHING_ELSE = " Is there anything else I can help you with?"
_REF_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def to_speech(text: str) -> str:
    """Text-to-speech friendly version: read references and card digits one by one."""
    text = re.sub(r"CMP-(\d{8})-([A-Z0-9]{6})",
                  lambda m: "C M P, " + " ".join(m[1]) + ", " + " ".join(m[2]), text)
    return re.sub(r"ending in (\d{4})", lambda m: "ending in " + " ".join(m[1]), text)


@dataclass
class Reply:
    text: str
    end_call: bool = False
    transfer: bool = False
    log_text: str | None = None  # what is persisted in the transcript (may omit PII)
    events: list[tuple[str, dict]] = field(default_factory=list)

    @property
    def speech(self) -> str:
        return to_speech(self.text)


def reset_flow(ctx: dict) -> None:
    for key in FLOW_KEYS:
        ctx.pop(key, None)


def money(value, currency: str) -> str:
    return f"{currency} {value:,.2f}"


class DialogEngine:
    def __init__(self, db: Session, settings: Settings, now: datetime | None = None):
        self.db = db
        self.s = settings
        self.now = now or models.utcnow()
        self.events: list[tuple[str, dict]] = []

    # ------------------------------------------------------------------ public
    def greeting(self) -> Reply:
        return Reply(GREETING.format(bank=self.s.bank_name))

    def handle(self, call: models.CallSession, text: str) -> Reply:
        ctx = dict(call.context or {})
        state = State(call.state)
        reply = self._route(call, ctx, state, (text or "").strip())
        call.context = ctx
        reply.events = self.events
        return reply

    # ----------------------------------------------------------------- helpers
    def _emit(self, topic: str, **payload) -> None:
        self.events.append((topic, payload))

    def _say(self, call, state: State, text: str, **kw) -> Reply:
        call.state = state.value
        return Reply(text, **kw)

    def _menu_reply(self, call, ctx, text: str) -> Reply:
        reset_flow(ctx)
        return self._say(call, State.MENU, text)

    def _customer(self, ctx) -> models.Customer:
        return self.db.get(models.Customer, ctx["customer_id"])

    def _bad_input(self, call, ctx, prompt: str, next_state: State | None = None) -> Reply:
        ctx["errors"] = ctx.get("errors", 0) + 1
        ctx["total_errors"] = ctx.get("total_errors", 0) + 1
        if ctx["total_errors"] >= self.s.max_total_errors:
            return self._callback(call, ctx, "too many unclear inputs")
        if ctx["errors"] >= self.s.max_unknown_turns:
            keep = ctx.get("total_errors", 0)
            reply = self._menu_reply(call, ctx, "I'm having trouble with that step, so let's start again. " + MENU_HELP)
            ctx["total_errors"] = keep
            return reply
        return self._say(call, next_state or State(call.state), prompt)

    # ------------------------------------------------------------------ router
    def _route(self, call, ctx, state: State, text: str) -> Reply:
        if state == State.MENU and nlu.detect_emergency(text) and call.priority != "high":
            call.priority = "high"
            self._emit("call.priority_raised", call_id=call.id, reason="emergency_keywords")

        if state != State.MENU and nlu.is_cancel(text, strict=state in FREE_TEXT_STATES):
            return self._menu_reply(call, ctx, "Okay, I've cancelled that." + ANYTHING_ELSE)

        if state not in FREE_TEXT_STATES:
            intent = nlu.classify_intent(text)
            if intent == Intent.GOODBYE:
                return self._goodbye(call)
            if intent == Intent.OPERATOR:
                return self._transfer(call, ctx)
            if intent == Intent.CALLBACK:
                return self._callback(call, ctx, "caller asked for a callback")

        handlers = {
            State.MENU: self._menu, State.AUTH_CNIC: self._auth_cnic, State.AUTH_DOB: self._auth_dob,
            State.CARD_SELECT: self._card_select, State.CONFIRM_BLOCK: self._confirm_block,
            State.ACTIVATE_VERIFY: self._activate_verify, State.PIN_NEW: self._pin_new,
            State.PIN_CONFIRM: self._pin_confirm, State.ADDR_NEW: self._addr_new,
            State.ADDR_CONFIRM: self._addr_confirm, State.COMPLAINT_DESC: self._complaint_desc,
            State.ASK_BLOCK_AFTER_COMPLAINT: self._ask_block_after_complaint,
            State.ASK_COMPLAINT_AFTER_BLOCK: self._ask_complaint_after_block,
        }
        return handlers[state](call, ctx, text)

    # --------------------------------------------------------------- terminals
    def _goodbye(self, call) -> Reply:
        return Reply(f"Thank you for calling {self.s.bank_name}. Take care and goodbye.", end_call=True)

    def _transfer(self, call, ctx) -> Reply:
        op = routing.assign_operator(self.db, call, self.now)
        if op is None:
            return self._menu_reply(
                call, ctx,
                "All of our operators are busy right now. I can still help you straight away. " + MENU_HELP)
        call.status = "ringing_operator"
        call.handler = "operator"
        call.ring_deadline = self.now + timedelta(seconds=self.s.ring_timeout_seconds)
        self._emit("call.transfer_requested", call_id=call.id, operator_id=op.id)
        return Reply("Please hold while I connect you to an available operator.", transfer=True)

    def _callback(self, call, ctx, why: str) -> Reply:
        ref = self._create_complaint(
            call, ctx.get("customer_id"), "callback_request", "normal",
            f"Callback requested ({why}). Caller phone: {call.caller_phone}")
        reply = Reply(
            "I'm sorry I couldn't fully help with that. I've registered a callback request, and a bank "
            f"representative will call you back on this number. Your reference is {ref}. "
            f"Thank you for calling {self.s.bank_name}, goodbye.", end_call=True)
        return reply

    # -------------------------------------------------------------------- menu
    def _menu(self, call, ctx, text: str) -> Reply:
        intent = nlu.classify_intent(text)
        if intent == Intent.HELP:
            return self._say(call, State.MENU, MENU_HELP)
        if intent == Intent.UNKNOWN:
            yn = nlu.parse_yes_no(text)
            if yn is False:
                return self._goodbye(call)
            if yn is True:
                return self._say(call, State.MENU, "Please tell me what you need help with.")
            ctx["unknown"] = ctx.get("unknown", 0) + 1
            if ctx["unknown"] >= self.s.max_unknown_turns:
                return self._callback(call, ctx, "request not understood")
            return self._say(call, State.MENU, "Sorry, I didn't catch that. " + MENU_HELP)

        ctx["unknown"] = 0
        ctx["errors"] = 0
        if intent == Intent.CARD_BLOCK:
            ctx["reason"] = nlu.detect_block_reason(text)
        if intent == Intent.COMPLAINT:
            ctx["category"] = nlu.detect_complaint_category(text)
        if intent in AUTH_REQUIRED and not ctx.get("customer_id"):
            ctx["pending_intent"] = intent.value
            return self._say(call, State.AUTH_CNIC,
                             "I can help with that. First I need to verify your identity. "
                             "Please say or enter your 13 digit CNIC number.")
        return self._begin(call, ctx, intent)

    def _begin(self, call, ctx, intent: Intent) -> Reply:
        return {
            Intent.BALANCE: self._do_balance,
            Intent.CARD_BLOCK: self._start_block,
            Intent.CARD_ACTIVATE: self._start_activate,
            Intent.CHANGE_PIN: self._start_pin,
            Intent.CHANGE_ADDRESS: self._start_address,
            Intent.COMPLAINT: self._start_complaint,
        }[intent](call, ctx)

    # -------------------------------------------------------------------- auth
    def _auth_cnic(self, call, ctx, text: str) -> Reply:
        digits = nlu.extract_digits(text)
        if len(digits) != 13 or digits[0] == "0":
            return self._bad_input(call, ctx, "I need your 13 digit CNIC number. "
                                              "Please say or enter all 13 digits.")
        ctx["cnic_hash"] = security.hash_cnic(digits, self.s.cnic_pepper)
        ctx["errors"] = 0
        return self._say(call, State.AUTH_DOB,
                         "Thank you. Now please say your date of birth, for example 15 March 1990.")

    def _auth_dob(self, call, ctx, text: str) -> Reply:
        dob = nlu.parse_dob(text, today=self.now.date())
        if dob is None:
            return self._bad_input(call, ctx, "I didn't catch a valid date of birth. "
                                              "Please say it like 15 March 1990.")
        cnic_hash = ctx.pop("cnic_hash", None)
        customer = None
        if cnic_hash:
            customer = self.db.scalars(
                select(models.Customer).where(models.Customer.cnic_hash == cnic_hash)).first()
        locked = bool(customer and customer.locked_until and customer.locked_until > self.now)
        if customer and not locked and customer.dob == dob:
            return self._auth_success(call, ctx, customer)
        return self._auth_failure(call, ctx, customer, locked)

    def _auth_success(self, call, ctx, customer) -> Reply:
        customer.failed_attempts = 0
        customer.locked_until = None
        ctx["customer_id"] = customer.id
        ctx["errors"] = 0
        call.customer_id = customer.id
        self._emit("auth.succeeded", call_id=call.id, customer_id=customer.id)
        pending = ctx.pop("pending_intent", None)
        first = customer.full_name.split()[0]
        prefix = f"Thank you, {first}. You are verified. "
        if not pending:
            return self._menu_reply(call, ctx, prefix + "How can I help you?")
        reply = self._begin(call, ctx, Intent(pending))
        reply.log_text = "You are verified. " + (reply.log_text if reply.log_text is not None else reply.text)
        reply.text = prefix + reply.text
        return reply

    def _auth_failure(self, call, ctx, customer, locked: bool) -> Reply:
        call.auth_attempts += 1
        if customer and not locked:
            customer.failed_attempts += 1
            if customer.failed_attempts >= self.s.max_failed_attempts_per_customer:
                customer.locked_until = self.now + timedelta(minutes=self.s.lockout_minutes)
                self._emit("auth.locked", call_id=call.id, customer_id=customer.id)
        self._emit("auth.failed", call_id=call.id, attempt=call.auth_attempts)
        remaining = self.s.max_auth_attempts_per_call - call.auth_attempts
        if remaining <= 0:
            self._emit("auth.call_blocked", call_id=call.id)
            return Reply("I'm sorry, I couldn't verify your identity, so for your security I'm ending this "
                         "call. Please visit your nearest branch or call back later. Goodbye.", end_call=True)
        plural = "attempt" if remaining == 1 else "attempts"
        return self._say(call, State.AUTH_CNIC,
                         f"I could not verify those details. You have {remaining} {plural} left. "
                         "Please say your CNIC number again.")

    # ----------------------------------------------------------------- balance
    def _do_balance(self, call, ctx) -> Reply:
        accounts = self.db.scalars(select(models.Account).where(
            models.Account.customer_id == ctx["customer_id"]).order_by(models.Account.id)).all()
        if not accounts:
            return self._menu_reply(call, ctx, "I couldn't find any accounts on your profile." + ANYTHING_ELSE)
        parts = []
        for a in accounts:
            part = (f"Your {a.account_type} account ending in {a.account_number[-4:]} has an available "
                    f"balance of {money(a.balance, a.currency)}.")
            if a.status != "active":
                part += f" Please note this account is currently {a.status}."
            parts.append(part)
        reply = self._menu_reply(call, ctx, " ".join(parts) + ANYTHING_ELSE)
        reply.log_text = "Balance details were read to the verified customer." + ANYTHING_ELSE
        return reply

    # -------------------------------------------------------------------- cards
    def _cards(self, ctx, statuses) -> list[models.Card]:
        return list(self.db.scalars(select(models.Card).where(
            models.Card.customer_id == ctx["customer_id"], models.Card.status.in_(statuses)
        ).order_by(models.Card.id)).all())

    @staticmethod
    def _describe(card) -> str:
        return f"{card.card_type} card ending in {card.card_last4}"

    def _choose_card(self, call, ctx, cards, action: str, verb: str) -> Reply | None:
        """Returns a prompt when the customer must pick a card, else None (single card selected)."""
        ctx["action"] = action
        if len(cards) == 1:
            ctx["card_id"] = cards[0].id
            return None
        ctx["candidates"] = [c.id for c in cards]
        listing = ", or a ".join(self._describe(c) for c in cards)
        return self._say(call, State.CARD_SELECT,
                         f"You have {len(cards)} cards: a {listing}. Which card would you like to {verb}? "
                         "Please say the last four digits.")

    def _card_select(self, call, ctx, text: str) -> Reply:
        last4 = nlu.extract_last4(text)
        card = None
        if last4:
            card = next((c for c in (self.db.get(models.Card, i) for i in ctx.get("candidates", []))
                         if c and c.card_last4 == last4), None)
        if card is None:
            return self._bad_input(call, ctx, "I couldn't match that to one of your cards. "
                                              "Please say the last four digits of the card.")
        ctx["card_id"] = card.id
        ctx["errors"] = 0
        return self._after_card_chosen(call, ctx, card)

    def _after_card_chosen(self, call, ctx, card) -> Reply:
        if ctx.get("action") == "pin":
            return self._say(call, State.PIN_NEW, self._pin_prompt())
        return self._say(call, State.CONFIRM_BLOCK,
                         f"I found your {self._describe(card)}. Shall I block it now? Please say yes or no.")

    # ---- block
    def _start_block(self, call, ctx) -> Reply:
        cards = self._cards(ctx, ("active", "inactive"))
        if not cards:
            return self._menu_reply(call, ctx, "All of your cards are already blocked." + ANYTHING_ELSE)
        prompt = self._choose_card(call, ctx, cards, "block", "block")
        return prompt or self._after_card_chosen(call, ctx, cards[0])

    def _confirm_block(self, call, ctx, text: str) -> Reply:
        yn = nlu.parse_yes_no(text)
        if yn is None:
            return self._bad_input(call, ctx, "Please say yes to block the card, or no to keep it.")
        if yn is False:
            return self._menu_reply(call, ctx, "Okay, I have not blocked your card." + ANYTHING_ELSE)
        card = self.db.get(models.Card, ctx["card_id"])
        if card is None or card.customer_id != ctx["customer_id"]:
            return self._menu_reply(call, ctx, "I couldn't find that card." + ANYTHING_ELSE)
        reason = ctx.get("reason", "customer_request")
        card.status = "blocked"
        card.blocked_reason = reason
        card.blocked_at = self.now
        self._emit("card.blocked", call_id=call.id, customer_id=card.customer_id,
                   card_last4=card.card_last4, reason=reason)
        text_out = (f"Your {self._describe(card)} has been blocked and can no longer be used. A confirmation "
                    "SMS has been sent to your registered number. A replacement card can be requested at any branch.")
        if reason in ("lost", "stolen", "suspected_fraud") and not ctx.get("complaint_done"):
            ctx.pop("card_id", None)
            ctx.pop("candidates", None)
            ctx["errors"] = 0
            return self._say(call, State.ASK_COMPLAINT_AFTER_BLOCK,
                             text_out + " Would you also like me to register a complaint about this?")
        return self._menu_reply(call, ctx, text_out + ANYTHING_ELSE)

    def _ask_complaint_after_block(self, call, ctx, text: str) -> Reply:
        yn = nlu.parse_yes_no(text)
        if yn is None:
            return self._bad_input(call, ctx, "Please say yes if you want to register a complaint, or no.")
        if yn is False:
            return self._menu_reply(call, ctx, "Okay." + ANYTHING_ELSE)
        ctx["category"] = ctx.get("category", "general")
        ctx["errors"] = 0
        return self._start_complaint(call, ctx)

    # ---- activate
    def _start_activate(self, call, ctx) -> Reply:
        cards = self._cards(ctx, ("inactive",))
        if not cards:
            return self._menu_reply(
                call, ctx, "There is no card waiting for activation on your profile. If your card is already "
                           "active, no action is needed. A blocked card must be replaced at a branch." + ANYTHING_ELSE)
        ctx["candidates"] = [c.id for c in cards]
        return self._say(call, State.ACTIVATE_VERIFY,
                         "For your security, please say the last four digits of the card you want to activate.")

    def _activate_verify(self, call, ctx, text: str) -> Reply:
        last4 = nlu.extract_last4(text)
        card = None
        if last4:
            card = next((c for c in (self.db.get(models.Card, i) for i in ctx.get("candidates", []))
                         if c and c.card_last4 == last4 and c.status == "inactive"), None)
        if card is None:
            return self._bad_input(call, ctx, "That doesn't match a card waiting for activation. "
                                              "Please say the last four digits again.")
        card.status = "active"
        self._emit("card.activated", call_id=call.id, customer_id=card.customer_id, card_last4=card.card_last4)
        return self._menu_reply(
            call, ctx, f"Your {self._describe(card)} has been activated and is ready to use. "
                       "You can ask me to set your PIN at any time." + ANYTHING_ELSE)

    # --------------------------------------------------------------------- PIN
    @staticmethod
    def _pin_prompt() -> str:
        return ("Please say or enter your new four digit PIN. Choose one that is hard to guess "
                "and do not share it with anyone.")

    def _start_pin(self, call, ctx) -> Reply:
        cards = self._cards(ctx, ("active",))
        if not cards:
            return self._menu_reply(call, ctx, "You don't have an active card. Please activate your card first." + ANYTHING_ELSE)
        prompt = self._choose_card(call, ctx, cards, "pin", "set a new PIN for")
        if prompt:
            return prompt
        return self._say(call, State.PIN_NEW, self._pin_prompt())

    def _pin_new(self, call, ctx, text: str) -> Reply:
        pin = nlu.extract_pin(text)
        if pin is None:
            return self._bad_input(call, ctx, "A PIN must be exactly four digits. Please try again.")
        if security.is_weak_pin(pin):
            return self._bad_input(call, ctx, "That PIN is too easy to guess. Please choose a different four digit PIN.")
        ctx["pending_pin_hash"], ctx["pending_pin_salt"] = security.hash_pin(pin)
        ctx["errors"] = 0
        return self._say(call, State.PIN_CONFIRM, "Thank you. Please repeat the new PIN to confirm.")

    def _pin_confirm(self, call, ctx, text: str) -> Reply:
        pin = nlu.extract_pin(text)
        salt, hashed = ctx.get("pending_pin_salt"), ctx.get("pending_pin_hash")
        if pin is None or not salt or not hashed:
            return self._bad_input(call, ctx, "Please repeat the four digit PIN to confirm.")
        if not security.verify_pin(pin, salt, hashed):
            ctx.pop("pending_pin_hash", None)
            ctx.pop("pending_pin_salt", None)
            return self._bad_input(call, ctx, "The PINs did not match. Let's try again. "
                                              "Please say your new four digit PIN.", next_state=State.PIN_NEW)
        card = self.db.get(models.Card, ctx["card_id"])
        if card is None or card.customer_id != ctx["customer_id"] or card.status != "active":
            return self._menu_reply(call, ctx, "I couldn't update the PIN for that card." + ANYTHING_ELSE)
        card.pin_hash, card.pin_salt, card.pin_changed_at = hashed, salt, self.now
        self._emit("pin.changed", call_id=call.id, customer_id=card.customer_id, card_last4=card.card_last4)
        return self._menu_reply(
            call, ctx, f"Your PIN has been changed successfully for the {self._describe(card)}. "
                       "Please never share your PIN with anyone, including bank staff." + ANYTHING_ELSE)

    # ----------------------------------------------------------------- address
    def _start_address(self, call, ctx) -> Reply:
        return self._say(call, State.ADDR_NEW, "Please tell me your new full address, including house "
                                               "number, street, area and city.")

    def _addr_new(self, call, ctx, text: str) -> Reply:
        clean = " ".join(text.split())
        if not (10 <= len(clean) <= 200 and len(clean.split()) >= 3):
            return self._bad_input(call, ctx, "Please give your complete address, with house number, "
                                              "street, area and city.")
        ctx["new_address"] = clean
        ctx["errors"] = 0
        return self._say(call, State.ADDR_CONFIRM,
                         f"I heard: {clean}. Shall I update the address on your profile? Please say yes or no.",
                         log_text="I read the new address back for confirmation.")

    def _addr_confirm(self, call, ctx, text: str) -> Reply:
        yn = nlu.parse_yes_no(text)
        if yn is None:
            return self._bad_input(call, ctx, "Please say yes to update the address, or no to re-enter it.")
        if yn is False:
            ctx.pop("new_address", None)
            return self._bad_input(call, ctx, "No problem. Please tell me the new address again.",
                                   next_state=State.ADDR_NEW)
        customer = self._customer(ctx)
        new = ctx.pop("new_address")
        self.db.add(models.AddressHistory(customer_id=customer.id, old_address=customer.address,
                                          new_address=new, call_id=call.id, changed_at=self.now))
        customer.address = new
        self._emit("address.changed", call_id=call.id, customer_id=customer.id)
        return self._menu_reply(
            call, ctx, "Your address has been updated successfully. For your security, a confirmation "
                       "SMS has been sent to your registered number." + ANYTHING_ELSE)

    # --------------------------------------------------------------- complaints
    def _start_complaint(self, call, ctx) -> Reply:
        return self._say(call, State.COMPLAINT_DESC, "I'm sorry to hear that. Please briefly describe "
                                                     "what happened, and I will register your complaint.")

    def _complaint_desc(self, call, ctx, text: str) -> Reply:
        if len(text) < 8:
            return self._bad_input(call, ctx, "Could you describe the problem in a little more detail?")
        description = security.redact_digits(text)[:1000]
        category = ctx.get("category", "general")
        if category == "general":
            category = nlu.detect_complaint_category(description)
        priority = "high" if (category in HIGH_PRIORITY_CATEGORIES or call.priority == "high") else "normal"
        ref = self._create_complaint(call, ctx["customer_id"], category, priority, description)
        ctx["complaint_done"] = True
        msg = (f"Your complaint has been registered. Your reference number is {ref}. Please note it down. "
               f"Our team will contact you within {self.s.complaint_sla_hours} working hours.")
        if priority == "high":
            msg += " It has been marked as high priority."
        if category in HIGH_PRIORITY_CATEGORIES and self._cards(ctx, ("active", "inactive")):
            ctx["errors"] = 0
            return self._say(call, State.ASK_BLOCK_AFTER_COMPLAINT,
                             msg + " Since this may involve unauthorized use, would you like me to block "
                                   "your card right now as a precaution?")
        return self._menu_reply(call, ctx, msg + ANYTHING_ELSE)

    def _ask_block_after_complaint(self, call, ctx, text: str) -> Reply:
        yn = nlu.parse_yes_no(text)
        if yn is None:
            return self._bad_input(call, ctx, "Please say yes to block your card, or no.")
        if yn is False:
            return self._menu_reply(call, ctx, "Okay, I have not blocked your card." + ANYTHING_ELSE)
        ctx["reason"] = "suspected_fraud"
        ctx["errors"] = 0
        return self._start_block(call, ctx)

    def _create_complaint(self, call, customer_id, category, priority, description) -> str:
        ref = ""
        for _ in range(10):
            ref = f"CMP-{self.now:%Y%m%d}-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(6))
            if not self.db.scalars(select(models.Complaint).where(models.Complaint.reference == ref)).first():
                break
        self.db.add(models.Complaint(
            reference=ref, customer_id=customer_id, call_id=call.id, caller_phone=call.caller_phone,
            category=category, priority=priority, description=description, created_at=self.now))
        self._emit("complaint.created", call_id=call.id, customer_id=customer_id,
                   reference=ref, category=category, priority=priority)
        return ref
