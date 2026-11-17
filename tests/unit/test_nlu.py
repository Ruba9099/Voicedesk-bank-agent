from datetime import date

import pytest

from app.agent import nlu
from app.agent.nlu import Intent


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I want to block my card", Intent.CARD_BLOCK),
        ("my card was stolen", Intent.CARD_BLOCK),
        ("I lost my debit card", Intent.CARD_BLOCK),
        ("card band kar do", Intent.CARD_BLOCK),
        ("what is my balance", Intent.BALANCE),
        ("balance inquiry please", Intent.BALANCE),
        ("mera balance kitna hai", Intent.BALANCE),
        ("I want to register a complaint", Intent.COMPLAINT),
        ("someone misused my account", Intent.COMPLAINT),
        ("there is an unauthorized transaction", Intent.COMPLAINT),
        ("mujhe shikayat darj karni hai", Intent.COMPLAINT),
        ("activate my new card", Intent.CARD_ACTIVATE),
        ("I want to change my pin", Intent.CHANGE_PIN),
        ("reset my PIN", Intent.CHANGE_PIN),
        ("mera pin badlo", Intent.CHANGE_PIN),
        ("pin tabdeel karna hai", Intent.CHANGE_PIN),
        ("mera pata badlo", Intent.CHANGE_ADDRESS),
        ("pata tabdeel karna hai", Intent.CHANGE_ADDRESS),
        ("change my address", Intent.CHANGE_ADDRESS),
        ("update my personal information", Intent.CHANGE_ADDRESS),
        ("let me talk to a human operator", Intent.OPERATOR),
        ("call me back later", Intent.CALLBACK),
        ("goodbye", Intent.GOODBYE),
        ("what are your interest rates on loans", Intent.UNKNOWN),
        ("tell me a joke", Intent.UNKNOWN),
        ("", Intent.UNKNOWN),
    ],
)
def test_classify_intent(text, expected):
    assert nlu.classify_intent(text) == expected


def test_deactivate_is_not_activation():
    assert nlu.classify_intent("deactivate my card") != Intent.CARD_ACTIVATE


@pytest.mark.parametrize(
    "text,digits",
    [
        ("35202-1234567-1", "3520212345671"),
        ("3 5 2 0 2 1 2 3 4 5 6 7 1", "3520212345671"),
        ("my cnic is 3520212345671", "3520212345671"),
        ("three five two zero two one two three four five six seven one", "3520212345671"),
        ("teen paanch do sifar do aik do teen char paanch chay saat aik", "3520212345671"),
    ],
)
def test_extract_digits(text, digits):
    assert nlu.extract_digits(text) == digits


def test_extract_last4_and_pin():
    assert nlu.extract_last4("ending in 4 3 2 1") == "4321"
    assert nlu.extract_last4("card 4111 1111 1111 9876") == "9876"
    assert nlu.extract_last4("hello") is None
    assert nlu.extract_pin("4 8 2 1") == "4821"
    assert nlu.extract_pin("12345") is None
    assert nlu.extract_pin("abc") is None


@pytest.mark.parametrize(
    "text",
    [
        "15 March 1990",
        "15th of March 1990",
        "March 15, 1990",
        "15-03-1990",
        "15/03/1990",
        "1990-03-15",
        "15 03 1990",
        "15031990",
        "my date of birth is 15 march 1990",
    ],
)
def test_parse_dob_variants(text):
    assert nlu.parse_dob(text, today=date(2026, 11, 17)) == date(1990, 3, 15)


def test_parse_dob_day_first_default_and_disambiguation():
    assert nlu.parse_dob("05/04/1990", today=date(2026, 1, 1)) == date(1990, 4, 5)
    assert nlu.parse_dob("25/12/1990", today=date(2026, 1, 1)) == date(1990, 12, 25)


@pytest.mark.parametrize("text", ["", "hello", "31 February 1990", "15 03 2090", "15 03 1800", "99/99/1990"])
def test_parse_dob_rejects_invalid(text):
    assert nlu.parse_dob(text, today=date(2026, 11, 17)) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("yes", True),
        ("yes please", True),
        ("haan ji", True),
        ("correct", True),
        ("go ahead", True),
        ("no", False),
        ("nahi", False),
        ("no thanks", False),
        ("maybe later", None),
        ("yes no", None),
        ("", None),
    ],
)
def test_parse_yes_no(text, expected):
    assert nlu.parse_yes_no(text) is expected


def test_emergency_detection():
    assert nlu.detect_emergency("this is an emergency")
    assert nlu.detect_emergency("my card is stolen")
    assert nlu.detect_emergency("someone hacked my account")
    assert not nlu.detect_emergency("what is my balance")


def test_block_reason_detection():
    assert nlu.detect_block_reason("I lost my card") == "lost"
    assert nlu.detect_block_reason("it was stolen") == "stolen"
    assert nlu.detect_block_reason("someone misused it") == "suspected_fraud"
    assert nlu.detect_block_reason("just block it") == "customer_request"


def test_complaint_category_detection():
    assert nlu.detect_complaint_category("someone misused my card") == "card_misuse"
    assert nlu.detect_complaint_category("unauthorized transaction on my account") == "unauthorized_transaction"
    assert nlu.detect_complaint_category("my account was hacked") == "account_misuse"
    assert nlu.detect_complaint_category("the atm kept my cash") == "atm_issue"
    assert nlu.detect_complaint_category("staff at the branch was rude") == "service_quality"
    assert nlu.detect_complaint_category("I have a complaint") == "general"


def test_is_cancel():
    assert nlu.is_cancel("cancel")
    assert nlu.is_cancel("never mind")
    assert nlu.is_cancel("go back to the main menu")
    assert not nlu.is_cancel("House 5 Bus Stop Road Lahore", strict=True)
    assert nlu.is_cancel("stop", strict=True)
