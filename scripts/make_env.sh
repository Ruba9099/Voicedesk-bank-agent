#!/usr/bin/env bash
# Creates a .env with strong random secrets and a free HTTPS hostname (sslip.io).
#   ./scripts/make_env.sh                       # detects this server's public IP
#   ./scripts/make_env.sh 3.110.1.2             # use a given IP
#   ./scripts/make_env.sh 3.110.1.2 bank.example.com   # use your own domain
set -euo pipefail

if [ -f .env ]; then
  echo ".env already exists, not overwriting it." >&2
  exit 1
fi

IP="${1:-$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')}"
DOMAIN="${2:-${IP//./-}.sslip.io}"

umask 077
cat > .env <<EOF
API_KEY=$(openssl rand -hex 24)
CNIC_PEPPER=$(openssl rand -hex 24)
DOMAIN=${DOMAIN}
CORS_ORIGINS=https://${DOMAIN}
EOF

echo "Created .env for https://${DOMAIN}"
echo "API_KEY (keep private): $(grep '^API_KEY=' .env | cut -d= -f2)"
