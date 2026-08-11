# Single-VM deployment (Docker Compose + Caddy)

Runs the whole system on one Linux VM: Postgres + FastAPI + the built frontend,
behind Caddy with automatic HTTPS. See `../docs/DEPLOY.md` for the data policy
and the full hardening checklist.

## What's here

| File | Purpose |
|------|---------|
| `docker-compose.prod.yml` | Production stack (db + api + web + caddy) |
| `Caddyfile` | Reverse proxy + automatic TLS for the two domains |
| `.env.example` | Copy to `.env` and fill in secrets/domains |

## Prerequisites

- A Linux VM (2 vCPU / 2–4 GB) in a region near your users (e.g. Hong Kong).
- Docker + Docker Compose installed.
- Two DNS **A records** pointing at the VM's public IP:
  - `app.yourdomain.com`  → the web app
  - `api.yourdomain.com`  → the API
- Ports **80** and **443** open in the firewall/security group.

## Deploy

```bash
git clone <your-repo> agency-system && cd agency-system
cp deploy/.env.example deploy/.env
# edit deploy/.env — set domains, SECRET_KEY, POSTGRES_PASSWORD, ADMIN_*, ACME_EMAIL

docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d --build
```

On first boot the API waits for Postgres, runs migrations, creates your admin
from `ADMIN_*` (no demo data), and starts. Caddy provisions TLS certs the first
time each domain is hit. Then open `https://app.yourdomain.com` and log in.

## Operate

```bash
# logs
docker compose -f deploy/docker-compose.prod.yml logs -f api

# update to a new version
git pull
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d --build

# database backup (schedule via cron)
docker compose -f deploy/docker-compose.prod.yml exec -T db \
  pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup-$(date +%F).sql
```

## Notes

- **Only Caddy** binds host ports (80/443); Postgres/API/web are reachable only
  on the internal Docker network.
- **CORS** is locked to `https://${WEB_DOMAIN}` via the `CORS_ORIGINS` env var.
- **PDF Chinese** renders because the backend image bundles `fonts-wqy-zenhei`.
- To add another admin later, run `scripts/bootstrap_admin.py` with `ADMIN_*`
  env against the same `DATABASE_URL` (see `../docs/DEPLOY.md`).
