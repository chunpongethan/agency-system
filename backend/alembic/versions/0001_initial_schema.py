"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-04

DECISION: the baseline migration builds the full schema from the SQLAlchemy
metadata via create_all/drop_all rather than hand-written op.create_table calls.
This guarantees the migrated schema matches the models exactly and applies
cleanly on both Postgres and SQLite (it also avoids Alembic emitting duplicate
CREATE TYPE statements for shared native enums on Postgres). Later schema changes
should use `alembic revision --autogenerate`.
"""
from alembic import op

from app.models.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
