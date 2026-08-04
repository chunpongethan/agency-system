"""Print 'yes' if the DB has no agents yet (first run), else 'no'."""
from __future__ import annotations

import os

from sqlalchemy import create_engine, inspect, text

url = os.getenv("DATABASE_URL", "sqlite:///./agency.db")
engine = create_engine(url)
insp = inspect(engine)
need = True
if "agents" in insp.get_table_names():
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM agents")).scalar()
        need = (count == 0)
print("yes" if need else "no")
