# Backend API image. Build context is the repo root so we can copy both the
# backend package and the scripts/ directory (seed, migrations helpers).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for bcrypt/psycopg2 wheels are already provided; keep image slim.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY scripts /app/scripts

RUN chmod +x /app/backend/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/backend/entrypoint.sh"]
