import asyncio

from sqlalchemy import select

from app import models, routing
from tests.conftest import AHMED, FATIMA, HEADERS, Caller


def set_status(client, op_id, status):
    return client.put(f"/api/v1/operators/{op_id}/status", json={"status": status}, headers=HEADERS)


# ------------------------------------------------------- operator-first routing
def test_available_operator_gets_the_call_first(client):
    assert set_status(client, 2, "available").status_code == 200
    call = Caller(client)
    assert call.start["status"] == "ringing_operator" and call.start["handler"] == "operator"
    ops = {o["id"]: o for o in client.get("/api/v1/operators", headers=HEADERS).json()}
    assert ops[2]["status"] == "ringing" and ops[2]["current_call_id"] == call.id


def test_operator_accept_then_agent_stays_silent(client):
    set_status(client, 2, "available")
    call = Caller(client)
    r = client.post("/api/v1/operators/2/accept", json={"call_id": call.id}, headers=HEADERS)
    assert r.status_code == 200
    assert call.info()["status"] == "with_operator"
    r = client.post(f"/api/v1/calls/{call.id}/message", json={"text": "hello"})
    assert r.status_code == 409
    ops = {o["id"]: o for o in client.get("/api/v1/operators", headers=HEADERS).json()}
    assert ops[2]["status"] == "busy"


def test_ending_call_frees_the_operator(client):
    set_status(client, 2, "available")
    call = Caller(client)
    client.post("/api/v1/operators/2/accept", json={"call_id": call.id}, headers=HEADERS)
    assert client.post(f"/api/v1/calls/{call.id}/end").status_code == 200
    ops = {o["id"]: o for o in client.get("/api/v1/operators", headers=HEADERS).json()}
    assert ops[2]["status"] == "available" and ops[2]["current_call_id"] is None


def test_unanswered_ring_falls_back_to_agent_automatically(make_client):
    client = make_client(ring_timeout_seconds=0)
    set_status(client, 2, "available")
    call = Caller(client)
    assert call.start["status"] == "ringing_operator"
    info = call.info()  # lazy sweep on read
    assert info["status"] == "with_agent" and info["handler"] == "agent"
    assert any(t["speaker"] == "agent" for t in info["transcript"])
    ops = {o["id"]: o for o in client.get("/api/v1/operators", headers=HEADERS).json()}
    assert ops[2]["status"] == "available"
    r = client.post(f"/api/v1/calls/{call.id}/message", json={"text": "balance"})
    assert r.json()["state"] == "auth_cnic"


def test_operator_going_offline_while_ringing_releases_call_to_agent(client):
    set_status(client, 2, "available")
    call = Caller(client)
    assert set_status(client, 2, "offline").status_code == 200
    assert call.info()["status"] == "with_agent"


def test_operator_cannot_change_status_during_active_call(client):
    set_status(client, 2, "available")
    call = Caller(client)
    client.post("/api/v1/operators/2/accept", json={"call_id": call.id}, headers=HEADERS)
    assert set_status(client, 2, "available").status_code == 409


def test_accepting_someone_elses_call_is_rejected(client):
    set_status(client, 2, "available")
    call = Caller(client)
    r = client.post("/api/v1/operators/1/accept", json={"call_id": call.id}, headers=HEADERS)
    assert r.status_code == 409


def test_caller_asking_for_operator_when_all_busy_stays_with_agent(caller):
    r = caller.say("let me talk to a human operator")
    assert r["handler"] == "agent" and "busy" in r["reply_text"].lower()


def test_caller_asking_for_operator_when_one_is_free_is_transferred(client):
    call = Caller(client)
    set_status(client, 2, "available")
    r = call.say("I want to speak to an operator")
    assert r["status"] == "ringing_operator"
    r = client.post(f"/api/v1/calls/{call.id}/message", json={"text": "hello?"}).json()
    assert "hold" in r["reply_text"].lower()


def test_authentication_survives_operator_timeout_fallback(make_client):
    client = make_client(ring_timeout_seconds=0)
    call = Caller(client)
    call.say("balance")
    call.verify(AHMED)
    set_status(client, 2, "available")
    call.say("operator please")
    info = call.info()  # sweep -> back to agent
    assert info["status"] == "with_agent" and info["authenticated"] is True


def test_round_robin_between_available_operators(client):
    set_status(client, 1, "available")
    set_status(client, 2, "available")
    first = Caller(client)
    second = Caller(client)
    ops = {o["id"]: o for o in client.get("/api/v1/operators", headers=HEADERS).json()}
    assert ops[1]["current_call_id"] and ops[2]["current_call_id"]
    assert {ops[1]["current_call_id"], ops[2]["current_call_id"]} == {first.id, second.id}


def test_claim_operator_is_atomic_under_contention(client):
    set_status(client, 2, "available")
    sf = client.app.state.session_factory
    with sf() as a, sf() as b:
        assert routing.claim_operator(a, 2, "call-a") is True
        a.commit()
        assert routing.claim_operator(b, 2, "call-b") is False


# ------------------------------------------------------------------- pub / sub
def test_lifecycle_events_are_audited(client, db):
    call = Caller(client)
    call.say("goodbye")
    types = [r.event_type for r in db.scalars(select(models.AuditLog)).all()]
    assert "call.started" in types and "call.routed" in types and "call.ended" in types


def test_events_never_contain_secrets(client, db):
    call = Caller(client)
    call.say("balance")
    call.verify(FATIMA)
    blob = " ".join(str(r.payload) for r in db.scalars(select(models.AuditLog)).all())
    assert "42101" not in blob and "7654321" not in blob and "1985" not in blob


def test_websocket_receives_live_events(client):
    with client.websocket_connect("/ws/events?key=test-key") as ws:
        Caller(client)
        msg = ws.receive_json()
        assert msg["topic"] == "call.started"
        assert "id" in msg and "timestamp" in msg


def test_websocket_rejects_bad_key(client):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/events?key=wrong") as ws:
            ws.receive_json()


def test_failing_subscriber_does_not_break_the_call(client):
    def boom(event):
        raise RuntimeError("subscriber down")

    client.app.state.bus.subscribe("call.*", boom)
    call = Caller(client)
    assert call.say("balance")["state"] == "auth_cnic"
    assert len(client.app.state.bus.dead_letters) >= 1


def test_bus_publishes_in_causal_order(client):
    seen = []
    client.app.state.bus.subscribe("*", lambda e: seen.append(e.topic))
    call = Caller(client)
    call.say("goodbye")
    assert seen.index("call.started") < seen.index("call.routed") < seen.index("call.ended")


def test_background_sweeper_task_is_running(client):
    task = client.app.state.sweeper_task
    assert task is not None and not task.done()
