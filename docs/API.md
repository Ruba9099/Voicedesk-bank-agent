# API reference

Base URL: `http://127.0.0.1:8000`. Interactive docs: `/docs`, OpenAPI: `/openapi.json`.
Admin endpoints require header `X-API-Key: <API_KEY>`; otherwise `401`.

## Calls (public)

### `POST /api/v1/calls`
```json
{ "caller_phone": "+923001234567", "channel": "web" }
```
→ `201`
```json
{ "call_id": "…", "status": "with_agent", "handler": "agent", "state": "menu",
  "authenticated": false, "priority": "normal",
  "reply_text": "Thank you for calling Demo National Bank…",
  "reply_speech": "…", "end_call": false }
```
`status` is `ringing_operator` / `handler: operator` when an operator was available.

### `POST /api/v1/calls/{call_id}/message`
Body `{ "text": "what is my balance" }` (the transcribed speech, 1–1000 chars) → same shape as above.
* `reply_text` is for display; `reply_speech` is TTS-friendly (references and card digits spelled out).
* `409` if the call has ended or is with a human operator; `404` unknown call; `422` invalid body.
* If status is `ringing_operator` the reply is a "please hold" message; poll `GET /calls/{id}`.

### `GET /api/v1/calls/{call_id}`
State, `authenticated`, `priority`, and the **redacted** transcript. Applies the ring-timeout check lazily.

### `POST /api/v1/calls/{call_id}/end`
Hang up; frees the operator.

### `GET /api/v1/calls?limit=50` (admin)

## Operators (admin)
* `GET /api/v1/operators` → `[{id, name, status, current_call_id}]` (`available | ringing | busy | offline`)
* `PUT /api/v1/operators/{id}/status` body `{"status": "available|busy|offline"}`: `409` while the operator has an active call.
* `POST /api/v1/operators/{id}/accept` body `{"call_id": "…"}`: operator answers a ringing call; `409` if it is not ringing for that operator.

## Complaints (admin)
* `GET /api/v1/complaints?status=open&limit=100`
* `GET /api/v1/complaints/{reference}`
* `PATCH /api/v1/complaints/{reference}` body `{"status": "open|in_progress|resolved"}`

## Observability (admin)
* `GET /api/v1/events?limit=100`: audited pub/sub events
* `GET /api/v1/stats`: call, operator, complaint counts, events published, dead letters
* `WS /ws/events?key=<API_KEY>`: live JSON events `{id, topic, payload, timestamp}`; bad key closes with code `4401`

## System
* `GET /health` → `{"status":"ok"}` · `GET /ready` → checks the database (`503` if down) · `GET /api/v1/info` → bank name, demo phone

## Telephony (Twilio-compatible)
Point the number's voice webhook to `POST {PUBLIC_BASE_URL}/telephony/incoming`. Endpoints `/telephony/gather` and `/telephony/resume` are used via TwiML. Set `TWILIO_AUTH_TOKEN` and `PUBLIC_BASE_URL` to enforce `X-Twilio-Signature` (invalid → `403`). PIN entry uses keypad digits only.

## Call states
`menu, auth_cnic, auth_dob, card_select, confirm_block, activate_verify, pin_new, pin_confirm, addr_new, addr_confirm, complaint_desc, ask_block_after_complaint, ask_complaint_after_block`
