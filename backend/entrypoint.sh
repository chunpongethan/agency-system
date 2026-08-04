#!/usr/bin/env bash
# Container entrypoint: wait for the DB, apply migrations, seed on first run,
# then start the API server.
set -e

cd /app/backend

echo "[entrypoint] waiting for database…"
python /app/scripts/db_ready.py

echo "[entrypoint] applying migrations…"
alembic upgrade head

echo "[entrypoint] checking whether to seed…"
NEED_SEED="$(python /app/scripts/needs_seed.py)"
if [ "$NEED_SEED" = "yes" ]; then
  echo "[entrypoint] seeding demo data…"
  python /app/scripts/seed.py || echo "[entrypoint] seed skipped/failed (continuing)"
else
  echo "[entrypoint] data already present — skipping seed"
fi

echo "[entrypoint] starting uvicorn on :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
