#!/usr/bin/env bash
# Container entrypoint: wait for the DB, apply migrations, seed on first run,
# then start the API server.
set -e

cd /app/backend

echo "[entrypoint] waiting for database…"
python /app/scripts/db_ready.py

echo "[entrypoint] applying migrations…"
alembic upgrade head

# Demo seed only when explicitly enabled — NEVER in production. The demo seed
# creates fake agents/clients/transactions and sets every password to a known
# value, so production must leave SEED_DEMO unset/false and instead bootstrap a
# real admin from ADMIN_EMAIL / ADMIN_PASSWORD.
if [ "${SEED_DEMO:-false}" = "true" ]; then
  echo "[entrypoint] SEED_DEMO=true — checking whether to seed demo data…"
  NEED_SEED="$(python /app/scripts/needs_seed.py)"
  if [ "$NEED_SEED" = "yes" ]; then
    echo "[entrypoint] seeding demo data…"
    python /app/scripts/seed.py || echo "[entrypoint] seed skipped/failed (continuing)"
  else
    echo "[entrypoint] data already present — skipping demo seed"
  fi
else
  echo "[entrypoint] SEED_DEMO not enabled — skipping demo seed (production default)"
  if [ -n "${ADMIN_EMAIL:-}" ] && [ -n "${ADMIN_PASSWORD:-}" ]; then
    echo "[entrypoint] bootstrapping admin from ADMIN_EMAIL…"
    python /app/scripts/bootstrap_admin.py || echo "[entrypoint] admin bootstrap skipped/failed (continuing)"
  else
    echo "[entrypoint] no ADMIN_EMAIL/ADMIN_PASSWORD set — create an admin manually"
  fi
fi

echo "[entrypoint] starting uvicorn on :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
