# Deploy on AWS (EC2 + Docker Compose + Caddy)

Runs the API on one EC2 server with automatic HTTPS. This setup was chosen because the app needs a **WebSocket** (live events) and **one copy** (in-process pub/sub), and a plain server handles both without surprises.

> The files were checked locally (the `.env` script ran, the compose YAML parses) but **not run on AWS or with Docker** in the authoring environment. Run the smoke test at the end to confirm your deployment.

## Why not the other AWS services?
| Service | Verdict |
|---|---|
| **EC2** (or a Lightsail *instance*) | Recommended: WebSockets work, exactly one copy, simple. |
| Lightsail container service | Simple with a built-in HTTPS link, but AWS's docs do not state WebSocket support, so `/ws/events` would need testing. Keep the scale at 1. |
| App Runner | Not recommended: an [AWS answer](https://repost.aws/questions/QU0jOAcOoTQqigUj6B9oGDxg/websockets-on-apprunner) describes it as meant for standard HTTPS apps. |

## Steps
1. **Launch the server.** EC2 → *Launch instance*: Ubuntu 24.04 LTS, `t3.small` (or `t3.micro` if free-tier eligible), create and download a key pair.
   Security group: port **22 only from your IP**, ports **80** and **443** from anywhere. Do **not** open 8000.
2. **Fixed address.** Allocate an **Elastic IP** and associate it with the instance (AWS bills for public IPv4 addresses; check your billing page).
3. **Install Docker.**
   ```bash
   ssh -i yourkey.pem ubuntu@YOUR_ELASTIC_IP
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER && exit      # reconnect with ssh
   ```
4. **Get the code and create secrets.**
   ```bash
   git clone https://github.com/Ruba9099/Voicedesk-bank-agent.git
   cd Voicedesk-bank-agent
   ./scripts/make_env.sh        # strong API_KEY + CNIC_PEPPER, free HTTPS name like 3-110-1-2.sslip.io
   ```
   Copy the printed `API_KEY` somewhere private. To use your own domain: `./scripts/make_env.sh YOUR_IP bank.yourdomain.com` and point its DNS **A record** at the Elastic IP first.
5. **Start.**
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build
   docker compose ps
   ```
   The first HTTPS request can take a few seconds while the certificate is issued.
6. **Verify** (from your own computer):
   ```bash
   curl https://<your-domain>/health
   python scripts/smoke_test.py https://<your-domain> <API_KEY>
   ```
   Open `https://<your-domain>/` for the demo UI, enter the API key and press *Connect dashboard* to check the live feed.

## Everyday commands
```bash
docker compose -f docker-compose.yml -f docker-compose.aws.yml logs -f      # logs
git pull && docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build   # update
docker compose -f docker-compose.yml -f docker-compose.aws.yml down -v       # stop AND reset demo data
```
Data lives in a Docker volume and survives restarts. The smoke test blocks the demo customer's card, so reset with `down -v` and start again before showing the demo.

## Troubleshooting
* **No HTTPS / certificate error:** ports 80 and 443 must be open in the security group; check `docker compose logs caddy`. For your own domain, the DNS A record must already point to the server.
* **`sslip.io` rate limits:** Let's Encrypt limits certificates per domain; use your own domain if you hit them.
* **Microphone not working:** the browser only allows it on HTTPS. Use the HTTPS address.
* **502 from Caddy:** the API is still starting or crashed; `docker compose logs api`.

## Cost and safety
* Stop the instance when you are not demoing it. Release the Elastic IP if you delete the server.
* Keep `API_KEY` private; it unlocks the operator desk and live events.
* The demo uses fictional data only. Do not load real customer data.
