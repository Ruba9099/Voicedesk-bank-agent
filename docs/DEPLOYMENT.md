# Deployment

> The Docker and Render files were written but **not built or deployed** in the authoring environment (no Docker daemon, no cloud access). The app itself was run with uvicorn and smoke-tested. Run the smoke script against your deployed URL to confirm.

## 1. Push to GitHub
```bash
git init && git add . && git commit -m "VoiceDesk Bank Agent"
git branch -M main
git remote add origin https://github.com/<you>/voicedesk-bank-agent.git
git push -u origin main
```
CI (`.github/workflows/ci.yml`) runs the tests on every push.

## 2. Docker (local or any VPS)
```bash
cp .env.example .env     # set API_KEY and CNIC_PEPPER to long random values
docker compose up --build
curl http://localhost:8000/health
```
MySQL (optional): `docker compose --profile mysql up --build` with `DATABASE_URL_OVERRIDE=mysql+pymysql://voicedesk:CHANGE_ME@db:3306/voicedesk`.

## 3. Live URL on Render (free tier, good for a portfolio)
1. Push the repo to GitHub.
2. Render dashboard → **New → Blueprint** → select the repo (it reads `render.yaml`).
3. Render generates `API_KEY` and `CNIC_PEPPER`; copy `API_KEY` from the service's Environment tab.
4. Open `https://<service>.onrender.com/` (demo UI) and `/docs`.
5. Verify: `python scripts/smoke_test.py https://<service>.onrender.com <API_KEY>`

Notes: the free tier sleeps when idle (first request is slow); SQLite on the container disk resets on each deploy, which is fine for a demo. Browser microphone input needs HTTPS, which Render provides. Any host that runs a Docker image works the same way (Railway, Fly.io, a VPS).

## 4. Real phone number (optional)
1. Set `PUBLIC_BASE_URL=https://<your-url>` and `TWILIO_AUTH_TOKEN`.
2. In Twilio, set the number's *A call comes in* webhook to `POST https://<your-url>/telephony/incoming`.
3. Optionally set `OPERATOR_DIAL_NUMBER` so an accepted operator call is bridged with `<Dial>`.

## 5. Checklist before showing it publicly
- [ ] `API_KEY` and `CNIC_PEPPER` are not the defaults (the app logs a warning if they are)
- [ ] Only fictional data is loaded; keep `DEMO_MODE=true`
- [ ] `CORS_ORIGINS` restricted to your site
- [ ] Single worker (in-process pub/sub)
- [ ] You are not presenting this as a real bank service
