import base64
import hashlib
import hmac

from tests.conftest import AHMED, HEADERS, Caller


def test_health_and_ready(client):
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["database"] == "ok"


def test_info_exposes_demo_bank_and_phone(client):
    r = client.get("/api/v1/info").json()
    assert r["bank_name"] == "Demo National Bank"
    assert r["phone"].startswith("+92")
    assert r["demo"] is True


def test_protected_endpoints_require_api_key(client):
    for path in ["/api/v1/operators", "/api/v1/complaints", "/api/v1/stats", "/api/v1/events", "/api/v1/calls"]:
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers={"X-API-Key": "wrong"}).status_code == 401, path
        assert client.get(path, headers=HEADERS).status_code == 200, path


def test_call_endpoints_are_public(client):
    assert client.post("/api/v1/calls", json={"caller_phone": "+923001112222"}).status_code == 201


def test_invalid_operator_status_is_rejected(client):
    r = client.put("/api/v1/operators/1/status", json={"status": "sleeping"}, headers=HEADERS)
    assert r.status_code == 422


def test_complaint_listing_lookup_and_status_update(client):
    call = Caller(client)
    call.say("I have a complaint")
    call.verify(AHMED)
    call.say("The ATM at the mall kept my cash yesterday evening")
    listing = client.get("/api/v1/complaints", headers=HEADERS).json()
    assert len(listing) == 1
    ref = listing[0]["reference"]
    assert client.get(f"/api/v1/complaints/{ref}", headers=HEADERS).json()["category"] == "atm_issue"
    r = client.patch(f"/api/v1/complaints/{ref}", json={"status": "resolved"}, headers=HEADERS)
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    assert client.patch(f"/api/v1/complaints/{ref}", json={"status": "bogus"}, headers=HEADERS).status_code == 422
    assert client.get("/api/v1/complaints/CMP-00000000-AAAAAA", headers=HEADERS).status_code == 404
    only_open = client.get("/api/v1/complaints?status=open", headers=HEADERS).json()
    assert only_open == []


def test_stats_reflect_activity(client):
    call = Caller(client)
    call.say("goodbye")
    s = client.get("/api/v1/stats", headers=HEADERS).json()
    assert s["calls_total"] == 1 and s["calls_handled_by_agent"] == 1
    assert s["events_published"] >= 3
    assert "operators" in s and "complaints" in s


# ------------------------------------------------------------------ telephony
def test_twilio_incoming_returns_gather_twiml(client):
    r = client.post("/telephony/incoming", data={"CallSid": "CA100", "From": "+923001234567"})
    assert r.status_code == 200 and "xml" in r.headers["content-type"]
    assert "<Gather" in r.text and "Demo National Bank" in r.text
    assert 'action="/telephony/gather"' in r.text


def test_twilio_gather_continues_the_same_conversation(client):
    client.post("/telephony/incoming", data={"CallSid": "CA101", "From": "+923001234567"})
    r = client.post("/telephony/gather", data={"CallSid": "CA101", "SpeechResult": "what is my balance"})
    assert "CNIC" in r.text and "<Gather" in r.text
    r = client.post("/telephony/gather", data={"CallSid": "CA101", "Digits": "3520212345671"})
    assert "date of birth" in r.text.lower()


def test_twilio_gather_hangs_up_when_call_ends(client):
    client.post("/telephony/incoming", data={"CallSid": "CA102", "From": "+923001234567"})
    r = client.post("/telephony/gather", data={"CallSid": "CA102", "SpeechResult": "goodbye"})
    assert "<Hangup" in r.text


def test_twilio_unknown_call_sid_is_handled_gracefully(client):
    r = client.post("/telephony/gather", data={"CallSid": "NOPE", "SpeechResult": "hi"})
    assert r.status_code == 200 and "<Hangup" in r.text


def test_pin_entry_over_phone_uses_dtmf_only():
    from app.api.telephony import build_gather_twiml

    xml = build_gather_twiml("Please enter your new PIN", "pin_new", "/telephony/gather")
    assert 'input="dtmf"' in xml and 'numDigits="4"' in xml
    xml = build_gather_twiml("How can I help?", "menu", "/telephony/gather")
    assert 'input="speech dtmf"' in xml


def test_twiml_escapes_xml_characters():
    from app.api.telephony import build_gather_twiml

    xml = build_gather_twiml("Tom & Jerry <bank>", "menu", "/telephony/gather")
    assert "&amp;" in xml and "&lt;bank&gt;" in xml


def test_twilio_signature_enforced_when_token_configured(make_client):
    client = make_client(twilio_auth_token="tok", public_base_url="https://voice.example.com")
    data = {"CallSid": "CA200", "From": "+923001234567"}
    assert client.post("/telephony/incoming", data=data).status_code == 403
    assert client.post("/telephony/incoming", data=data, headers={"X-Twilio-Signature": "bad"}).status_code == 403
    url = "https://voice.example.com/telephony/incoming"
    payload = url + "".join(k + data[k] for k in sorted(data))
    sig = base64.b64encode(hmac.new(b"tok", payload.encode(), hashlib.sha1).digest()).decode()
    assert client.post("/telephony/incoming", data=data, headers={"X-Twilio-Signature": sig}).status_code == 200
