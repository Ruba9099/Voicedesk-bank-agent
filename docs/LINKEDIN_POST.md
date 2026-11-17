# LinkedIn post draft

Replace the two placeholders, then post. Attach a short screen recording of the demo UI (call → stolen card → card blocked → complaint reference).

---

I built a voice agent that answers the bank's phone when every operator is busy.

The idea: someone with a stolen card should not sit in a queue. VoiceDesk rings a human operator first. If nobody is free (or nobody answers in time), the agent takes the call, verifies the customer, and handles the routine work: balance inquiry, card block, card activation, PIN change, address change and complaint registration, with a reference number.

What I focused on:
• Zero hallucination by design: a deterministic dialog state machine, no generative model. Every number comes from the database.
• Emergency handling: "stolen" or "fraud" raises priority and goes straight to blocking the card.
• Pub/sub event bus feeding an audit log, an SMS outbox, metrics and a live WebSocket dashboard.
• Privacy: CNIC stored only as an HMAC, PINs as salted hashes and never logged, sensitive speech redacted from transcripts.
• Built test-first: 152 automated tests, 96% coverage, plus a smoke test against the live API.

Stack: Python, FastAPI, SQLAlchemy, WebSockets, Twilio-compatible webhook, Docker.

It is a demo with fictional data (not a real bank), and I documented the limits honestly, including that a real deployment needs OTP-based verification.

Live demo: <YOUR_LIVE_URL>
Code: <YOUR_GITHUB_URL>

#FastAPI #Python #AI #VoiceAI #Banking #SoftwareEngineering #Automation
