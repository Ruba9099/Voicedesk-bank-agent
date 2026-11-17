from tests.conftest import HEADERS


def _call(client, sid, **extra):
    return client.post("/telephony/incoming", data={"CallSid": sid, "From": "+923001234567", **extra})


def test_phone_call_rings_operator_then_agent_takes_over_after_timeout(make_client):
    client = make_client(ring_timeout_seconds=0)
    client.put("/api/v1/operators/2/status", json={"status": "available"}, headers=HEADERS)
    r = _call(client, "CA300")
    assert "<Pause" in r.text and "/telephony/resume" in r.text and "hold" in r.text.lower()
    r = client.post("/telephony/resume", data={"CallSid": "CA300"})
    assert "<Gather" in r.text  # agent now speaks
    assert "operators are still busy" in r.text


def test_phone_resume_connects_operator_when_accepted(make_client):
    client = make_client()
    client.put("/api/v1/operators/2/status", json={"status": "available"}, headers=HEADERS)
    _call(client, "CA301")
    calls = client.get("/api/v1/calls", headers=HEADERS).json()
    call_id = calls[0]["call_id"]
    client.post("/api/v1/operators/2/accept", json={"call_id": call_id}, headers=HEADERS)
    r = client.post("/telephony/resume", data={"CallSid": "CA301"})
    assert "connected to an operator" in r.text


def test_phone_resume_dials_operator_number_when_configured(make_client):
    client = make_client(operator_dial_number="+920000000000")
    client.put("/api/v1/operators/2/status", json={"status": "available"}, headers=HEADERS)
    _call(client, "CA302")
    call_id = client.get("/api/v1/calls", headers=HEADERS).json()[0]["call_id"]
    client.post("/api/v1/operators/2/accept", json={"call_id": call_id}, headers=HEADERS)
    r = client.post("/telephony/resume", data={"CallSid": "CA302"})
    assert "<Dial>+920000000000</Dial>" in r.text


def test_phone_resume_unknown_call_hangs_up(client):
    r = client.post("/telephony/resume", data={"CallSid": "NOPE"})
    assert "<Hangup" in r.text


def test_phone_resume_keeps_holding_while_still_ringing(client):
    client.put("/api/v1/operators/2/status", json={"status": "available"}, headers=HEADERS)
    _call(client, "CA303")
    r = client.post("/telephony/resume", data={"CallSid": "CA303"})
    assert "<Pause" in r.text


def test_phone_caller_asks_for_operator_mid_call_gets_hold_twiml(client):
    _call(client, "CA304")
    client.put("/api/v1/operators/2/status", json={"status": "available"}, headers=HEADERS)
    r = client.post("/telephony/gather", data={"CallSid": "CA304", "SpeechResult": "operator please"})
    assert "<Pause" in r.text and "/telephony/resume" in r.text


def test_phone_silence_reprompts(client):
    _call(client, "CA305")
    r = client.post("/telephony/gather", data={"CallSid": "CA305"})
    assert "didn't hear" in r.text and "<Gather" in r.text


def test_phone_message_during_human_call_is_handled_without_error(client):
    client.put("/api/v1/operators/2/status", json={"status": "available"}, headers=HEADERS)
    _call(client, "CA306")
    call_id = client.get("/api/v1/calls", headers=HEADERS).json()[0]["call_id"]
    client.post("/api/v1/operators/2/accept", json={"call_id": call_id}, headers=HEADERS)
    r = client.post("/telephony/gather", data={"CallSid": "CA306", "SpeechResult": "hello"})
    assert r.status_code == 200
