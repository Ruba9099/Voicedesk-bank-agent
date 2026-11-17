# Roadmap

## Phase 1: MVP (done)
- [x] Operator-first routing, ring timeout, automatic fallback to agent
- [x] CNIC + DOB verification, per-call attempts, account lockout
- [x] Balance, card block, card activation, PIN change, address change, complaints
- [x] Emergency priority, callback fallback
- [x] Pub/sub: audit, SMS outbox, metrics, WebSocket feed
- [x] REST API, Twilio-compatible webhook, browser demo UI
- [x] 152 automated tests, smoke script, Docker/Render/CI files

## Phase 2: Production hardening
- [ ] OTP to the registered mobile as second factor (replace knowledge-only verification)
- [ ] Real SMS gateway consuming the notifications outbox
- [ ] Redis/Kafka event bus for multi-instance deployments; Postgres/MySQL migrations (Alembic)
- [ ] Rate limiting and IP allow-listing on public call endpoints
- [ ] Core-banking adapter interface (replace demo tables)
- [ ] Live Twilio end-to-end test with a real number
- [ ] Urdu speech replies and Urdu intent coverage

## Phase 3: Platform
- [ ] Department packs: hospital appointment desk, railway enquiry, emergency-centre triage (swap intent set + actions)
- [ ] Supervisor dashboard (queue, SLA, complaint workflow)
- [ ] Voice biometrics and call-recording consent flows
- [ ] Optional LLM *only* for intent classification (never for facts), behind the same deterministic action layer

## Ordered build tasks (MVP, as executed)
1. Security, NLU, event bus (tests first) → 2. Models, routing → 3. Dialog engine → 4. Services, subscribers → 5. API + telephony → 6. Demo UI → 7. Integration tests, debug → 8. Docs, Docker, CI → 9. Live server smoke test.
