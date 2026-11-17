# Product Brief: VoiceDesk Bank Agent

## Problem
Bank helplines have long hold times. A customer with a stolen card or suspected fraud may wait many minutes for a free operator while money is at risk. Operators also spend much of their time on routine, scripted requests (balance, card block, PIN change) that do not need a human.

## Target users
* **Callers**: bank customers, especially those in an emergency.
* **Operators / supervisors**: want routine calls handled and complaints captured with a reference number.
* **Bank IT / security**: need auditability, privacy-safe logs and predictable behaviour.
* The same engine can serve other departments later (hospital desk, railway enquiry, emergency centre) by swapping the intent set and actions.

## Goals
1. No caller waits when operators are busy: the agent answers immediately.
2. Complete the top routine requests without a human.
3. Emergencies (stolen/lost card, fraud) are prioritised and protected first.
4. The agent never invents information.
5. Everything is audited without storing secrets.

## Success metrics
| Metric | Target |
|---|---|
| Time to first response when operators are busy | < 1 s |
| Calls resolved by the agent without operator | ≥ 70% (demo flows) |
| Card-block completion time after verification | < 60 s |
| Hallucinated facts in replies | 0 (deterministic engine) |
| Secrets (CNIC/PIN/DOB) found in logs/transcripts | 0 |

## Scope
**MVP (built)**: operator-first routing with timeout fallback · CNIC+DOB verification with lockout · balance inquiry · card block (with card selection + confirmation) · card activation · PIN change (weak-PIN rejection, double entry) · address change (confirmation + history) · complaint registration (reference number, priority, optional card block) · callback request fallback · emergency priority · pub/sub (audit, SMS outbox, metrics, live feed) · REST API, Twilio-compatible webhook, browser demo UI.

**Nice-to-have (later)**: OTP second factor · Urdu replies · real SMS gateway · supervisor dashboard · call recording consent flows · other departments.

**Out of scope**: real core-banking integration, payments/transfers, real telephony numbers, voice biometrics.

## User stories & acceptance criteria (MVP)
1. *As a caller, when all operators are busy I am answered by the agent.* AC: call starts with `handler=agent`; greeting returned.
2. *As a caller, if the ringing operator does not answer, the agent takes over.* AC: after `RING_TIMEOUT_SECONDS` the call is `with_agent`, operator freed, auth state preserved.
3. *As a customer, I verify with CNIC and date of birth.* AC: 3 attempts per call; 5 failures lock the account; unknown CNIC and wrong DOB look identical.
4. *As a customer, I hear my balance.* AC: balances come from the DB only; not stored in transcripts.
5. *As a customer with a stolen card, I block it quickly.* AC: priority becomes high; card chosen by last four digits; explicit yes/no; card status `blocked`; SMS queued.
6. *As a customer, I activate a new card.* AC: requires matching last four digits.
7. *As a customer, I change my PIN.* AC: weak PINs rejected; entered twice; stored only as salted hash; never logged.
8. *As a customer, I change my address.* AC: read-back confirmation; history row stored.
9. *As a customer, I register a complaint.* AC: reference `CMP-YYYYMMDD-XXXXXX`; fraud-type complaints are high priority and offer a card block.
10. *As an admin, I watch live activity.* AC: WebSocket feed, audited events, stats.

## Risks, assumptions, open questions
| Risk / assumption | Mitigation |
|---|---|
| CNIC + DOB is weak authentication | Documented; roadmap adds OTP/biometrics. |
| ASR errors on digits/dates | Re-prompts, read-back confirmations, DTMF for PIN on phone. |
| Agent misunderstands intent | Fallback menu, callback request after 3 misses. |
| In-process pub/sub limits scale | Interface isolated in `EventBus`; swap for Redis/Kafka. |
| Open: regulator requirements for recorded calls and PII retention | To be confirmed per bank. |
| Open: which core-banking APIs to integrate | Out of scope for the demo. |
