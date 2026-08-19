"""
Create the first real admin account from environment variables — the production
alternative to the demo seed (scripts/seed.py). Idempotent and non-destructive:
if an agent with the given code or email already exists it does nothing, so it is
safe to run on every deploy.

Creates the Heritree admin from ADMIN_* and, when set, the CPM admin from CPM_ADMIN_*.

Required env (Heritree admin):
  ADMIN_EMAIL      admin login email
  ADMIN_PASSWORD   admin password (stored bcrypt-hashed)
Optional env:
  ADMIN_CODE       agent code (default "A000")
  ADMIN_NAME       display name (default "Administrator")
  CPM_ADMIN_EMAIL / CPM_ADMIN_PASSWORD  create the CPM admin too (code must start
                   "cpm"; defaults CPM_ADMIN_CODE="cpm000", CPM_ADMIN_NAME)
  DATABASE_URL     SQLAlchemy URL (default local sqlite)

Usage:  ADMIN_EMAIL=... ADMIN_PASSWORD=... python scripts/bootstrap_admin.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import sessionmaker

from app.models.models import Base, Agent, Role
from app.security import hash_password


def _company_for_code(code: str) -> str:
    return "cpm" if (code or "").lower().startswith("cpm") else "heritree"


def _ensure_admin(db, code: str, name: str, email: str, password: str) -> None:
    existing = db.execute(
        select(Agent).where(or_(Agent.code == code, Agent.email == email))
    ).scalars().first()
    if existing is not None:
        print(f"bootstrap_admin: agent code={existing.code!r} / email={existing.email!r} "
              f"already exists — leaving it untouched")
        return
    db.add(Agent(code=code, name=name, email=email, level=1, role=Role.ADMIN,
                 is_active=True, company=_company_for_code(code),
                 password_hash=hash_password(password)))
    db.commit()
    print(f"bootstrap_admin: created admin {name} ({code}) <{email}> [{_company_for_code(code)}]")


email = os.getenv("ADMIN_EMAIL")
password = os.getenv("ADMIN_PASSWORD")
if not email or not password:
    print("bootstrap_admin: ADMIN_EMAIL and ADMIN_PASSWORD are required", file=sys.stderr)
    sys.exit(1)

engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///./backend/agency.db"))
Base.metadata.create_all(engine)
db = sessionmaker(bind=engine)()

_ensure_admin(db, os.getenv("ADMIN_CODE", "A000"),
              os.getenv("ADMIN_NAME", "Administrator"), email, password)

# Second company (CPM) admin — created only when its credentials are provided.
cpm_email = os.getenv("CPM_ADMIN_EMAIL")
cpm_password = os.getenv("CPM_ADMIN_PASSWORD")
if cpm_email and cpm_password:
    _ensure_admin(db, os.getenv("CPM_ADMIN_CODE", "cpm000"),
                  os.getenv("CPM_ADMIN_NAME", "CPM Administrator"), cpm_email, cpm_password)

db.close()
