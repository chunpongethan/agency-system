# Deployment

The repo ships a full container stack: `docker-compose.yml` (Postgres + FastAPI +
nginx-served frontend), Dockerfiles for each service, and a backend
`entrypoint.sh` that waits for the DB → runs Alembic migrations → optionally seeds
→ starts uvicorn. Deploying is mostly **configuration and hardening**.

---

## Production vs. demo data

`scripts/seed.py` loads **demo** data — fake agents, clients, and transactions —
and sets every account's password to a known value. It must **never** run in
production. The entrypoint now gates it behind `SEED_DEMO`:

- **Dev / staging:** `SEED_DEMO=true` → the demo dataset is loaded on an empty DB
  (this is the `docker-compose.yml` default, so local `docker compose up` still
  gives you the demo).
- **Production:** leave `SEED_DEMO` unset/`false`. Instead provide
  `ADMIN_EMAIL` + `ADMIN_PASSWORD` and the entrypoint runs
  `scripts/bootstrap_admin.py`, which creates **one real admin** (bcrypt-hashed
  password) and nothing else. It is idempotent — safe on every deploy.

Then log in as that admin and enter your real data through the UI, in this order:
**Products → Override rules → Agents (hierarchy) → Clients**. Transactions and
commissions accumulate as you book real deals.

> Start production from an **empty** database. Don't try to delete demo rows out
> of a seeded DB — a clean slate avoids leftover ID/reference assumptions.

---

## Quick start — single VM + Docker Compose

1. Provision a small Linux VM, install Docker + Compose, clone the repo.
2. Create a `.env` next to `docker-compose.yml`:

   ```env
   # secrets
   SECRET_KEY=<long random string>
   POSTGRES_PASSWORD=<strong password>

   # production data policy
   SEED_DEMO=false
   ADMIN_EMAIL=admin@yourco.com
   ADMIN_PASSWORD=<strong admin password>
   ADMIN_NAME=Administrator

   # the public API origin, baked into the frontend at build time
   VITE_API_URL=https://api.yourdomain.com
   ```

3. Put a TLS reverse proxy in front (**Caddy** is the least effort — automatic
   Let's Encrypt): route the web app and `api.yourdomain.com → api:8000`.
4. `docker compose up -d --build`. Migrations run; the real admin is created; no
   demo data is loaded.

---

## Pre-production checklist

| Item | Where | Action |
|------|-------|--------|
| **Demo data off** | `SEED_DEMO` | Leave unset/`false`; set `ADMIN_EMAIL`/`ADMIN_PASSWORD` |
| **JWT secret** | `SECRET_KEY` | Long random value from a secret store |
| **DB password** | `POSTGRES_PASSWORD` | Strong; never commit |
| **CORS** | `backend/app/main.py` (`allow_origins=["*"]`) | Restrict to your web origin |
| **PDF CJK font** | `backend/Dockerfile` bundles `fonts-wqy-zenhei` | Handled — exported-PDF Chinese renders. Override with `CJK_FONT_PATH=/path/to/font.ttf` if you prefer another TrueType CJK font |
| **Frontend API URL** | `VITE_API_URL` (build arg) | Public API URL; baked in at build |
| **HTTPS** | reverse proxy | Terminate TLS (Caddy/Traefik/nginx) |
| **Backups** | `postgres-data` volume | Scheduled `pg_dump` / managed snapshots |
| **Token expiry** | `ACCESS_TOKEN_EXPIRE_MINUTES` | Tune to policy (default 480 min) |

---

## Bootstrapping an admin manually

Outside Docker (or to add another admin), run against the target DB:

```bash
DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/db \
ADMIN_EMAIL=admin@yourco.com ADMIN_PASSWORD='strong-password' \
ADMIN_NAME='Administrator' ADMIN_CODE=A000 \
python scripts/bootstrap_admin.py
```

It creates the admin only if no agent with that code/email exists.

---

## Managed-PaaS alternative

Render / Railway / Fly.io: API as a Docker web service, Postgres as a managed
add-on (set `DATABASE_URL`), frontend as a static site from the Vite `dist/`
(HashRouter → **no SPA rewrite rules needed**). Set the same env vars; you get
TLS, managed backups, and CI deploys with minimal ops.
