"""Deterministic natural-language understanding.

No generative model is involved: intent and entity extraction are rule based,
so the agent can only ever act on what it recognises. Anything else maps to
UNKNOWN and gets a safe, scripted fallback (no hallucination by design).
Understands English plus common Roman Urdu phrases.
"""
from __future__ import annotations

import re
from datetime import date
from enum import Enum


class Intent(str, Enum):
    CARD_BLOCK = "card_block"
    BALANCE = "balance"
    COMPLAINT = "complaint"
    CARD_ACTIVATE = "card_activate"
    CHANGE_PIN = "change_pin"
    CHANGE_ADDRESS = "change_address"
    OPERATOR = "operator"
    CALLBACK = "callback"
    GOODBYE = "goodbye"
    HELP = "help"
    UNKNOWN = "unknown"


def normalize(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"[^\w\s/\-.,']", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_BLOCK = [
    r"\b(block|blocked|blocking|freeze|frozen|disable|deactivate|band)\b.*\bcard\b",
    r"\bcard\b.*\b(block|blocked|blocking|freeze|frozen|disable|deactivate|band|lost|stolen|gum|chori)\b",
    r"\b(lost|stolen|misplaced)\b.*\bcard\b",
    r"\bblock\b",
]
_COMPLAINT = [
    r"\b(complain|complaint|complaints|shikayat|shikayet)\b",
    r"\b(misuse|misused|misusing)\b",
    r"\bunauthori[sz]ed\b",
    r"\b(fraud|fraudulent|suspicious|dispute)\b",
    r"\b(did not|didn't|didnt) (make|do|authori[sz]e)\b",
]
_PIN = [
    r"\b(change|reset|new|set|update|forgot|forgotten|badal|badlo|badlen|tabdeel)\b.*\bpin\b",
    r"\bpin\b.*\b(change|reset|new|set|update|badal|badlo|badlen|tabdeel)\b",
]
_ADDRESS = [
    r"\b(change|update|new|correct|edit|modify|badal|badlo|badlen|tabdeel)\b.*\b(address|pata)\b",
    r"\b(address|pata)\b.*\b(change|update|badal|badlo|badlen|tabdeel)\b",
    r"\bpersonal (information|details|info)\b",
]
_ACTIVATE = [r"\bactivat\w*\b", r"\bnew card\b.*\b(start|use|enable)\b"]
_BALANCE = [
    r"\bbalance\b",
    r"\bhow much (money|do i have)\b",
    r"\baccount (summary|statement)\b",
    r"\b(kitna|kitne) (paisa|paise|paisay)\b",
]
_OPERATOR = [
    r"\b(operator|human|representative|real person|live person|insan|banda)\b",
    r"\b(talk|speak) to (a |an )?(person|someone|officer)\b",
]
_CALLBACK = [r"\bcall (me )?back\b", r"\bcallback\b", r"\bcall me later\b"]
_GOODBYE = [
    r"\b(bye|goodbye|good bye)\b",
    r"\b(that is all|that's all|thats all|nothing else|end call|hang up)\b",
    r"\b(khuda hafiz|allah hafiz)\b",
]
_HELP = [r"\b(help|what can you do|options|menu)\b"]


def _any(patterns: list[str], t: str) -> bool:
    return any(re.search(p, t) for p in patterns)


def classify_intent(text: str) -> Intent:
    t = normalize(text)
    if not t:
        return Intent.UNKNOWN
    if _any(_GOODBYE, t):
        return Intent.GOODBYE
    if _any(_CALLBACK, t):
        return Intent.CALLBACK
    if _any(_OPERATOR, t):
        return Intent.OPERATOR
    if _any(_BLOCK, t):
        return Intent.CARD_BLOCK
    if _any(_COMPLAINT, t):
        return Intent.COMPLAINT
    if _any(_PIN, t):
        return Intent.CHANGE_PIN
    if _any(_ADDRESS, t):
        return Intent.CHANGE_ADDRESS
    if _any(_ACTIVATE, t):
        return Intent.CARD_ACTIVATE
    if _any(_BALANCE, t):
        return Intent.BALANCE
    if _any(_HELP, t):
        return Intent.HELP
    return Intent.UNKNOWN


# ---------------------------------------------------------------- entities
_NUMBER_WORDS = {
    "zero": "0", "oh": "0", "sifar": "0",
    "one": "1", "ek": "1", "aik": "1",
    "two": "2", "do": "2",
    "three": "3", "teen": "3",
    "four": "4", "char": "4", "chaar": "4",
    "five": "5", "paanch": "5", "panch": "5",
    "six": "6", "chay": "6", "che": "6", "chhe": "6",
    "seven": "7", "saat": "7",
    "eight": "8", "aath": "8",
    "nine": "9", "nau": "9",
}


def extract_digits(text: str) -> str:
    """All digits in the utterance, converting spoken number words."""
    out: list[str] = []
    for tok in re.findall(r"[a-z]+|\d+", (text or "").lower()):
        if tok.isdigit():
            out.append(tok)
        elif tok in _NUMBER_WORDS:
            out.append(_NUMBER_WORDS[tok])
    return "".join(out)


def extract_last4(text: str) -> str | None:
    digits = extract_digits(text)
    return digits[-4:] if len(digits) >= 4 else None


def extract_pin(text: str) -> str | None:
    digits = extract_digits(text)
    return digits if len(digits) == 4 else None


_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


def _make_date(y: int, m: int, d: int, today: date) -> date | None:
    try:
        result = date(y, m, d)
    except ValueError:
        return None
    if result.year < 1900 or result > today:
        return None
    return result


def parse_dob(text: str, today: date | None = None) -> date | None:
    today = today or date.today()
    t = (text or "").lower()
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t)
    t = re.sub(r"\bof\b", " ", t).replace(",", " ")
    t = re.sub(r"\s+", " ", t)

    m = re.search(r"\b(\d{4})[-/. ](\d{1,2})[-/. ](\d{1,2})\b", t)
    if m:
        return _make_date(int(m[1]), int(m[2]), int(m[3]), today)
    m = re.search(r"\b(\d{1,2})[-/. ](\d{1,2})[-/. ](\d{4})\b", t)
    if m:
        return _make_date(int(m[3]), int(m[2]), int(m[1]), today)
    m = re.search(r"\b(\d{1,2}) ([a-z]+) (\d{4})\b", t)
    if m and m[2] in _MONTHS:
        return _make_date(int(m[3]), _MONTHS[m[2]], int(m[1]), today)
    m = re.search(r"\b([a-z]+) (\d{1,2}) (\d{4})\b", t)
    if m and m[1] in _MONTHS:
        return _make_date(int(m[3]), _MONTHS[m[1]], int(m[2]), today)
    m = re.search(r"\b(\d{2})(\d{2})(\d{4})\b", t)
    if m:
        return _make_date(int(m[3]), int(m[2]), int(m[1]), today)
    return None


_YES = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "correct", "confirm",
        "confirmed", "proceed", "haan", "han", "ji", "jee", "theek", "right"}
_NO = {"no", "nope", "nahi", "nahin", "dont", "don't", "never"}


def parse_yes_no(text: str) -> bool | None:
    t = normalize(text)
    if not t:
        return None
    tokens = set(re.findall(r"[a-z']+", t))
    yes = bool(tokens & _YES) or "go ahead" in t or "do it" in t
    no = bool(tokens & _NO) or "do not" in t
    if yes and no:
        return None
    if yes:
        return True
    if no:
        return False
    return None


def detect_emergency(text: str) -> bool:
    return bool(re.search(
        r"\b(emergency|urgent|urgently|immediately|asap|stolen|theft|robbed|lost|fraud|hacked|unauthori[sz]ed)\b",
        normalize(text),
    ))


def detect_block_reason(text: str) -> str:
    t = normalize(text)
    if re.search(r"\blost\b|\bgum\b|\bmisplaced\b", t):
        return "lost"
    if re.search(r"\b(stolen|theft|chori|robbed)\b", t):
        return "stolen"
    if re.search(r"\b(misuse|misused|fraud|fraudulent|unauthori[sz]ed|hacked|suspicious)\b", t):
        return "suspected_fraud"
    return "customer_request"


def detect_complaint_category(text: str) -> str:
    t = normalize(text)
    misuse = re.search(r"\b(misuse|misused|misusing|fraud|fraudulent)\b", t)
    if "card" in t and misuse:
        return "card_misuse"
    if re.search(r"\bunauthori[sz]ed\b|\bnot me\b|\bdid not make\b|\bdidn't make\b|\bdeducted\b", t):
        return "unauthorized_transaction"
    if re.search(r"\baccount\b", t) and re.search(r"\b(misuse|misused|hacked|fraud)\b", t):
        return "account_misuse"
    if re.search(r"\bhacked\b", t):
        return "account_misuse"
    if re.search(r"\batm\b", t):
        return "atm_issue"
    if re.search(r"\b(staff|branch|rude|service|delay|delayed|behaviou?r)\b", t):
        return "service_quality"
    return "general"


_CANCEL = re.compile(r"\b(cancel|stop|start over|main menu|go back|never mind|nevermind)\b")


def is_cancel(text: str, strict: bool = False) -> bool:
    t = normalize(text)
    if not t:
        return False
    if strict:
        return bool(_CANCEL.search(t)) and len(t.split()) <= 4
    return bool(_CANCEL.search(t))
