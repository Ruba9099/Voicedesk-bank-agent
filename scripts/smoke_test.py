#!/usr/bin/env python3
"""End-to-end smoke test against a RUNNING server (local or deployed). Stdlib only.

    python scripts/smoke_test.py                       # http://127.0.0.1:8000, key "change-me"
    python scripts/smoke_test.py https://your-app.onrender.com YOUR_API_KEY

Needs the demo seed data (SEED_DEMO_DATA=true). Uses the fictional demo customer
Ahmed Raza. It blocks his debit card, so reset the DB (or redeploy) to re-run it.
"""
import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
KEY = sys.argv[2] if len(sys.argv) > 2 else "change-me"
passed = failed = 0


def req(method, path, body=None, admin=False):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if admin:
        headers["X-API-Key"] = KEY
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def say(call_id, text):
    code, body = req("POST", f"/api/v1/calls/{call_id}/message", {"text": text})
    assert code == 200, (code, body)
    print(f"        caller: {text!r}\n        agent : {body['reply_text'][:110]!r}")
    return body


print(f"Smoke test against {BASE}")
code, body = req("GET", "/health")
check("GET /health", code == 200 and body["status"] == "ok")
code, body = req("GET", "/ready")
check("GET /ready (database reachable)", code == 200 and body["database"] == "ok")
code, body = req("GET", "/api/v1/info")
check("GET /api/v1/info", code == 200 and "bank_name" in body, str(body))
code, _ = req("GET", "/api/v1/operators")
check("admin endpoint rejects missing API key", code == 401)

# Make every operator busy so the agent must take the call
code, ops = req("GET", "/api/v1/operators", admin=True)
check("GET /api/v1/operators with key", code == 200 and len(ops) >= 1, str(ops))
for op in ops:
    req("PUT", f"/api/v1/operators/{op['id']}/status", {"status": "busy"}, admin=True)

print("\nScenario 1: operators busy -> agent answers, balance inquiry")
code, call = req("POST", "/api/v1/calls", {"caller_phone": "+923001234567"})
check("call starts handled by agent", code == 201 and call["handler"] == "agent", str(call))
cid = call["call_id"]
r = say(cid, "what is my balance")
check("agent asks for CNIC", r["state"] == "auth_cnic")
say(cid, "35202-1234567-1")
r = say(cid, "15 March 1990")
check("verified and balance read from DB", r["authenticated"] and "250,000.50" in r["reply_text"])

print("\nScenario 2: block a lost card (emergency)")
r = say(cid, "my debit card was stolen, block it")
check("high priority raised", r["priority"] == "high")
check("asks which card or confirmation", r["state"] in ("card_select", "confirm_block"))
if r["state"] == "card_select":
    r = say(cid, "4321")
r = say(cid, "yes")
check("card blocked", "blocked" in r["reply_text"].lower())
r = say(cid, "yes")
r = say(cid, "My card was stolen from my bag at the market this afternoon")
check("complaint registered with reference", "CMP-" in r["reply_text"], r["reply_text"])
say(cid, "goodbye")

print("\nScenario 3: operator available -> rings first, falls to agent if ignored is covered by tests")
req("PUT", f"/api/v1/operators/{ops[0]['id']}/status", {"status": "available"}, admin=True)
code, call2 = req("POST", "/api/v1/calls", {"caller_phone": "+923001112222"})
check("call rings the available operator", call2["status"] == "ringing_operator", str(call2))
code, acc = req("POST", f"/api/v1/operators/{ops[0]['id']}/accept", {"call_id": call2["call_id"]}, admin=True)
check("operator accepts, call is with operator", code == 200 and acc["status"] == "with_operator", str(acc))
code, _ = req("POST", f"/api/v1/calls/{call2['call_id']}/message", {"text": "hello"})
check("agent stays silent while operator has the call (409)", code == 409)
req("POST", f"/api/v1/calls/{call2['call_id']}/end")

print("\nAdmin views")
code, complaints = req("GET", "/api/v1/complaints", admin=True)
check("complaint visible to admin", code == 200 and any(c["reference"].startswith("CMP-") for c in complaints))
code, events = req("GET", "/api/v1/events?limit=200", admin=True)
topics = {e["event_type"] for e in events}
check("pub/sub events audited", {"call.started", "card.blocked", "complaint.created", "call.ended"} <= topics, str(topics))
code, stats = req("GET", "/api/v1/stats", admin=True)
check("stats endpoint", code == 200 and stats["calls_total"] >= 2, str(stats))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
