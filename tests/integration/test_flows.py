import re
from datetime import datetime

from sqlalchemy import select

from app import models, security
from tests.conftest import AHMED, FATIMA, USMAN


# ------------------------------------------------------------------ routing
def test_agent_answers_when_all_operators_busy(caller):
    assert caller.start["handler"] == "agent"
    assert caller.start["status"] == "with_agent"
    assert "demo national bank" in caller.start["reply_text"].lower()
    assert caller.start["authenticated"] is False


# ------------------------------------------------------------ authentication
def test_balance_flow_requires_cnic_then_dob_then_reads_balance(caller):
    r = caller.say("what is my balance")
    assert r["state"] == "auth_cnic" and "cnic" in r["reply_text"].lower()
    r = caller.say(AHMED["cnic"])
    assert r["state"] == "auth_dob"
    r = caller.say(AHMED["dob"])
    assert r["authenticated"] is True
    assert "250,000.50" in r["reply_text"]
    assert r["state"] == "menu"


def test_spoken_cnic_words_are_understood(caller):
    caller.say("balance")
    caller.say("three five two zero two one two three four five six seven one")
    r = caller.say("fifteen march 1990")  # not parseable -> asks again
    assert r["authenticated"] is False and r["state"] == "auth_dob"
    r = caller.say("15 03 1990")
    assert r["authenticated"] is True


def test_invalid_cnic_length_is_reprompted_without_burning_an_attempt(caller, db):
    caller.say("balance")
    r = caller.say("12345")
    assert r["state"] == "auth_cnic" and "13" in r["reply_text"]
    cust = db.scalars(select(models.Customer).where(models.Customer.full_name == "Ahmed Raza")).one()
    assert cust.failed_attempts == 0


def test_three_wrong_dobs_end_the_call_and_count_failures(caller, db):
    caller.say("balance")
    for _ in range(2):
        r = caller.say(AHMED["cnic"]) if caller.last["state"] == "auth_cnic" else caller.last
        r = caller.say("1 January 1980")
        assert r["authenticated"] is False and r["end_call"] is False
    caller.say(AHMED["cnic"])
    r = caller.say("1 January 1980")
    assert r["end_call"] is True
    assert caller.info()["status"] == "ended"
    cust = db.scalars(select(models.Customer).where(models.Customer.full_name == "Ahmed Raza")).one()
    assert cust.failed_attempts == 3


def test_unknown_cnic_and_wrong_dob_give_identical_replies(new_caller):
    a = new_caller()
    a.say("balance")
    a.say("99999-9999999-9")
    unknown = a.say("15 March 1990")["reply_text"]
    b = new_caller()
    b.say("balance")
    b.say(AHMED["cnic"])
    wrong = b.say("1 January 1980")["reply_text"]
    assert unknown == wrong  # no account enumeration


def test_customer_is_locked_after_five_failures_across_calls(new_caller, db):
    c1 = new_caller()
    c1.say("balance")
    for _ in range(3):
        c1.say(AHMED["cnic"])
        c1.say("1 January 1980")
    c2 = new_caller()
    c2.say("balance")
    for _ in range(2):
        c2.say(AHMED["cnic"])
        c2.say("1 January 1980")
    cust = db.scalars(select(models.Customer).where(models.Customer.full_name == "Ahmed Raza")).one()
    assert cust.locked_until is not None and cust.locked_until > datetime.utcnow()
    c3 = new_caller()
    c3.say("balance")
    c3.say(AHMED["cnic"])
    r = c3.say(AHMED["dob"])  # correct credentials, still refused while locked
    assert r["authenticated"] is False


# ---------------------------------------------------------------- card block
def test_block_card_with_single_card_asks_confirmation_and_blocks(caller, db):
    caller.say("I want to block my card")
    r = caller.verify(FATIMA)
    assert r["state"] == "confirm_block" and "5544" in r["reply_text"]
    r = caller.say("yes")
    assert "blocked" in r["reply_text"].lower()
    card = db.scalars(select(models.Card).where(models.Card.card_last4 == "5544")).one()
    assert card.status == "blocked"
    assert db.scalars(select(models.AuditLog).where(models.AuditLog.event_type == "card.blocked")).first()
    assert db.scalars(select(models.Notification)).first()


def test_block_card_with_multiple_cards_asks_which_one(caller, db):
    caller.say("block my card")
    r = caller.verify(AHMED)
    assert r["state"] == "card_select"
    assert "4321" in r["reply_text"] and "9876" in r["reply_text"]
    r = caller.say("the one ending 4321")
    assert r["state"] == "confirm_block"
    caller.say("yes")
    cards = {c.card_last4: c.status for c in db.scalars(select(models.Card)).all()}
    assert cards["4321"] == "blocked" and cards["9876"] == "inactive"


def test_declining_block_leaves_card_untouched(caller, db):
    caller.say("block my card")
    caller.verify(FATIMA)
    r = caller.say("no")
    assert r["state"] == "menu"
    card = db.scalars(select(models.Card).where(models.Card.card_last4 == "5544")).one()
    assert card.status == "active"


def test_stolen_card_raises_priority_and_offers_complaint(caller, db):
    r = caller.say("my card was stolen")
    assert r["priority"] == "high"
    caller.verify(FATIMA)
    r = caller.say("yes")
    assert "complaint" in r["reply_text"].lower()
    r = caller.say("yes")
    assert r["state"] == "complaint_desc"
    caller.say("My card was stolen from my bag at the market today")
    comp = db.scalars(select(models.Complaint)).one()
    assert comp.priority == "high" and comp.category == "general"
    assert db.scalars(select(models.AuditLog).where(models.AuditLog.event_type == "call.priority_raised")).first()


# ------------------------------------------------------------- card activation
def test_activate_card_requires_matching_last_four(caller, db):
    caller.say("activate my new card")
    r = caller.verify(USMAN)
    assert r["state"] == "activate_verify"
    r = caller.say("1111")
    assert r["state"] == "activate_verify"
    r = caller.say("3 0 0 2")
    assert "activated" in r["reply_text"].lower()
    card = db.scalars(select(models.Card).where(models.Card.card_last4 == "3002")).one()
    assert card.status == "active"


def test_activate_when_no_inactive_card_says_so(caller):
    caller.say("activate my card")
    r = caller.verify(FATIMA)
    assert "no card" in r["reply_text"].lower() or "already active" in r["reply_text"].lower()


# ----------------------------------------------------------------- change PIN
def test_change_pin_full_flow_stores_only_a_hash(caller, db):
    caller.say("I want to change my pin")
    r = caller.verify(FATIMA)
    assert r["state"] == "pin_new"
    r = caller.say("1234")
    assert r["state"] == "pin_new" and "easy" in r["reply_text"].lower()
    r = caller.say("4821")
    assert r["state"] == "pin_confirm"
    r = caller.say("4822")
    assert r["state"] == "pin_new" and "match" in r["reply_text"].lower()
    caller.say("4821")
    r = caller.say("4821")
    assert "changed" in r["reply_text"].lower()
    card = db.scalars(select(models.Card).where(models.Card.card_last4 == "5544")).one()
    assert card.pin_hash and card.pin_hash != "4821"  # stored as a salted hash, not plaintext
    assert security.verify_pin("4821", card.pin_salt, card.pin_hash)
    assert not security.verify_pin("4822", card.pin_salt, card.pin_hash)


def test_pin_is_never_written_to_transcript_audit_or_context(caller, db):
    caller.say("change my pin")
    caller.verify(FATIMA)
    caller.say("4821")
    caller.say("4821")
    for row in db.scalars(select(models.Transcript)).all():
        assert "4821" not in row.text
    for row in db.scalars(select(models.AuditLog)).all():
        assert "4821" not in str(row.payload)
    call = db.get(models.CallSession, caller.id)
    assert "4821" not in str(call.context)


# --------------------------------------------------------------- change address
def test_change_address_requires_confirmation_and_keeps_history(caller, db):
    caller.say("I need to change my address")
    r = caller.verify(USMAN)
    assert r["state"] == "addr_new"
    r = caller.say("Lahore")
    assert r["state"] == "addr_new"  # too short
    r = caller.say("House 7, Street 2, Johar Town, Lahore")
    assert r["state"] == "addr_confirm" and "Johar Town" in r["reply_text"]
    r = caller.say("yes")
    assert "updated" in r["reply_text"].lower()
    cust = db.scalars(select(models.Customer).where(models.Customer.full_name == "Usman Tariq")).one()
    assert cust.address == "House 7, Street 2, Johar Town, Lahore"
    hist = db.scalars(select(models.AddressHistory)).one()
    assert hist.old_address != hist.new_address


def test_address_with_the_word_stop_is_not_treated_as_cancel(caller):
    caller.say("change my address")
    caller.verify(USMAN)
    r = caller.say("House 5 Bus Stop Road Gulberg Lahore")
    assert r["state"] == "addr_confirm"


# ------------------------------------------------------------------ complaints
def test_misuse_complaint_is_high_priority_and_offers_block(caller, db):
    caller.say("someone misused my card and I want to register a complaint")
    r = caller.verify(FATIMA)
    assert r["state"] == "complaint_desc"
    r = caller.say("There were three transactions yesterday that I did not make")
    assert re.search(r"CMP-\d{8}-[A-Z0-9]{6}", r["reply_text"])
    assert re.search(r"C M P", r["reply_speech"])
    assert r["state"] == "ask_block_after_complaint"
    r = caller.say("yes")
    assert "blocked" in r["reply_text"].lower() or r["state"] == "confirm_block"
    comp = db.scalars(select(models.Complaint)).one()
    assert comp.category == "card_misuse" and comp.priority == "high"


def test_general_complaint_has_normal_priority_and_no_block_offer(caller, db):
    caller.say("I have a complaint about the branch staff")
    caller.verify(AHMED)
    r = caller.say("The staff at the Gulberg branch were rude to me yesterday")
    assert r["state"] == "menu"
    comp = db.scalars(select(models.Complaint)).one()
    assert comp.category == "service_quality" and comp.priority == "normal"
    assert comp.customer_id is not None and comp.call_id == caller.id


def test_long_digit_runs_in_complaint_text_are_redacted(caller, db):
    caller.say("I have a complaint")
    caller.verify(AHMED)
    caller.say("My card 4111111111111111 was charged twice at the store")
    comp = db.scalars(select(models.Complaint)).one()
    assert "4111111111111111" not in comp.description


# ------------------------------------------------------- fallback / no hallucination
def test_unknown_requests_get_scripted_menu_and_never_invented_facts(caller):
    r = caller.say("what is your interest rate on car loans")
    assert "balance" in r["reply_text"].lower() and "complaint" in r["reply_text"].lower()
    assert not re.search(r"\d|%", r["reply_text"])


def test_three_unintelligible_turns_register_a_callback_and_end(caller, db):
    for _ in range(3):
        r = caller.say("blah blah")
    assert r["end_call"] is True
    comp = db.scalars(select(models.Complaint)).one()
    assert comp.category == "callback_request"


def test_cancel_returns_to_menu_but_keeps_session(caller):
    caller.say("balance")
    r = caller.say("cancel")
    assert r["state"] == "menu"


def test_goodbye_ends_the_call(caller):
    r = caller.say("goodbye")
    assert r["end_call"] is True
    assert caller.info()["status"] == "ended"


def test_message_after_call_ended_is_rejected(caller, client):
    caller.say("goodbye")
    r = client.post(f"/api/v1/calls/{caller.id}/message", json={"text": "hello"})
    assert r.status_code == 409


def test_unknown_call_id_is_404(client):
    assert client.post("/api/v1/calls/does-not-exist/message", json={"text": "hi"}).status_code == 404
    assert client.get("/api/v1/calls/does-not-exist").status_code == 404


def test_transcripts_never_contain_cnic_dob_or_balances(caller, db):
    caller.say("balance")
    caller.verify(AHMED)
    rows = db.scalars(select(models.Transcript)).all()
    caller_text = " ".join(t.text for t in rows if t.speaker == "caller")
    all_text = " ".join(t.text for t in rows)
    # what the caller said (CNIC, DOB) is never stored; the agent's own scripted example date is not caller data
    assert "35202" not in all_text and "1234567" not in all_text
    assert "1990" not in caller_text and "March" not in caller_text
    assert caller_text.count("[REDACTED]") == 2
    assert "250,000" not in all_text


def test_empty_text_is_rejected_by_validation(caller, client):
    r = client.post(f"/api/v1/calls/{caller.id}/message", json={"text": ""})
    assert r.status_code == 422
