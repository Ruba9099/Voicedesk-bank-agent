# Conversation flows

## Demo customers (fictional)
| Name | CNIC | Date of birth | Accounts | Cards |
|---|---|---|---|---|
| Ahmed Raza | 35202-1234567-1 | 15 March 1990 | savings 250,000.50 | debit 4321 (active), credit 9876 (inactive) |
| Fatima Noor | 42101-7654321-8 | 2 November 1985 | current 1,250,000.00; savings 75,500.75 | debit 5544 (active) |
| Usman Tariq | 61101-1122334-5 | 21 July 2000 | savings 18,250.00 | debit 3002 (inactive) |

Demo operators: Ayesha Khan (busy), Bilal Ahmed (offline). Use the operator desk in the UI or `PUT /api/v1/operators/{id}/status` to make one available.

## Accepted input
* CNIC: `35202-1234567-1`, `3520212345671`, spoken digits `three five two…`, Roman Urdu digits (`teen paanch do…`).
* Date of birth: `15 March 1990`, `March 15, 1990`, `15-03-1990`, `15/03/1990`, `1990-03-15`, `15031990` (day first).
* Yes/no: `yes, yeah, okay, haan, ji` / `no, nahi`.
* Intents also in Roman Urdu: `card band karo`, `balance kitna hai`, `shikayat`, `pin badlo`, `pata badlo`.
* Say `cancel` any time to return to the menu, `operator` to ask for a human, `callback` to request a call-back.

## Emergency: stolen card
```
Caller: My card was stolen
Agent : I can help with that. First I need to verify your identity. Please say or enter your 13 digit CNIC number.   (priority → high)
Caller: 42101-7654321-8
Agent : Thank you. Now please say your date of birth…
Caller: 2 November 1985
Agent : Thank you, Fatima. You are verified. I found your debit card ending in 5544. Shall I block it now?
Caller: Yes
Agent : Your debit card ending in 5544 has been blocked… Would you also like me to register a complaint about this?
```

## Balance inquiry
`balance` → CNIC → DOB → reads each account (`Your savings account ending in 0001 has an available balance of PKR 250,000.50.`).

## Card activation
`activate my card` → CNIC → DOB → "say the last four digits of the card" → must match an inactive card.

## PIN change
`change my pin` → verify → choose card (if several) → new 4-digit PIN (weak ones such as 1234 or 1111 rejected) → repeat to confirm → stored as salted hash. On the phone channel the PIN is keypad-only.

## Address change
`change my address` → verify → new address (house, street, area, city) → agent reads back → yes → updated, history stored, SMS queued.

## Complaint
`someone misused my card` → verify → "describe what happened" → reference `CMP-YYYYMMDD-XXXXXX`, category and priority set (misuse/unauthorised/hacked = high) → offers to block the card.

## When the agent is not sure
Unrecognised request → scripted menu (never an invented answer) → after 3 misses a **callback request** is registered and the call ends politely.
