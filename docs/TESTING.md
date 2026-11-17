# Testing

```bash
pip install -r requirements-dev.txt
pytest --cov=app --cov-report=term-missing
```

**Result at delivery: 152 passed, 96% line coverage.**

## Method
Built test-first. For each layer the tests were written before the code and run to confirm they failed for the right reason (import errors, since the modules did not exist), then the minimal implementation made them pass:

1. Unit tests for `security`, `nlu`, `events` → red (ImportError) → green (79 tests).
2. Integration tests for flows, routing, pub/sub, API security, telephony → red (missing `app.config`) → green.

## What is covered
| Area | Examples |
|---|---|
| Unit | CNIC hashing/masking, PIN hashing, weak PINs, redaction, Twilio signature, intents (EN + Roman Urdu), digit/DOB/yes-no parsing, event-bus patterns, ordering, failure isolation, dead letters |
| Routing | operator-first, accept, ring-timeout fallback, operator offline while ringing, round-robin, **atomic claim under contention**, auth survives fallback |
| Flows | balance, block (single/multiple cards, decline, stolen → complaint), activation, PIN (weak/mismatch/success), address, complaints (priority, block offer, redaction), fallback callback, cancel, goodbye |
| Security | lockout after 5 failures across calls, no account enumeration, secrets absent from transcripts/audit/context, API-key protection, WebSocket auth, Twilio signature |
| Pub/sub | lifecycle events audited, ordering, live WebSocket delivery, failing subscriber does not break the call, background sweeper running |
| Telephony | TwiML gather/hold/resume/hangup, DTMF-only PIN, XML escaping |

## Bugs found and fixed while testing
1. Activation reply said "is now active" instead of a clear "activated" confirmation → wording fixed in the dialog engine.
2. A transcript assertion matched the agent's own scripted example date, not caller data → test narrowed to caller rows (caller speech remains fully redacted).
3. Roman Urdu `pin badlo` / `pata badlo` were documented but not matched (only `badal`/`tabdeel` were) → failing tests added first, patterns extended.
4. A flaky-by-chance assertion (`"4821" in pin_hash`) was replaced by hash-verification assertions.

## Smoke test against a running server
`python scripts/smoke_test.py [BASE_URL] [API_KEY]` runs 18 end-to-end checks (health, auth, balance, stolen-card block, complaint, operator ring/accept, audit events, stats). It passed against a real uvicorn process. A separate check confirmed the background sweeper moves an unanswered call to the agent and that WebSocket events arrive live.

## Not covered
Live Twilio call, MySQL backend, Docker image build, load/performance testing.
