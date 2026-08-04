"""Wait until the database accepts connections (used by the Docker entrypoint)."""
from __future__ import annotations

import os
import sys
import time

from sqlalchemy import create_engine, text

url = os.getenv("DATABASE_URL", "sqlite:///./agency.db")
deadline = time.time() + 60
last_err = None
while time.time() < deadline:
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("database ready")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        last_err = exc
        print("waiting for database…")
        time.sleep(2)

print(f"database not ready after 60s: {last_err}", file=sys.stderr)
sys.exit(1)
