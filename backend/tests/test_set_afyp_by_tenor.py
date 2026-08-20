"""Tests for scripts/set_afyp_by_tenor.py — AFYP conversion from payment tenor."""
import os
import sys
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import Base, Product, ProductType

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import set_afyp_by_tenor  # noqa: E402


def _p(code, tenor, schedule, ptype=ProductType.INSURANCE):
    return Product(code=code, name=code, type=ptype, base_commission_rate=Decimal("0.05"),
                   afyp_conversion=Decimal("1"), payment_tenor=tenor, commission_schedule=schedule)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autoflush=False)()
    s.add_all([
        _p("T1", 1, "upfront"),
        _p("T2", 2, "trail"),
        _p("T3", 3, "trail"),
        _p("LUMP", None, "upfront"),      # 整付
        _p("RENEW", None, "trail"),       # 每年續保 -> untouched
        _p("T5", 5, "trail"),             # regular pay -> untouched
        _p("FUND", None, "upfront", ProductType.FUND),  # non-insurance -> untouched
    ])
    s.commit()
    yield s
    s.close()


def _afyp(session, code):
    return session.execute(select(Product).where(Product.code == code)).scalar_one().afyp_conversion


def test_sets_afyp_by_tenor(session):
    updated, unchanged, buckets = set_afyp_by_tenor.apply(session)
    session.commit()
    assert _afyp(session, "T1") == Decimal("0.1000")
    assert _afyp(session, "T2") == Decimal("0.5000")
    assert _afyp(session, "T3") == Decimal("0.3333")
    assert _afyp(session, "LUMP") == Decimal("0.1000")
    # untouched
    assert _afyp(session, "RENEW") == Decimal("1")
    assert _afyp(session, "T5") == Decimal("1")
    assert _afyp(session, "FUND") == Decimal("1")
    assert updated == 4


def test_idempotent(session):
    set_afyp_by_tenor.apply(session); session.commit()
    updated, unchanged, _ = set_afyp_by_tenor.apply(session)
    assert updated == 0 and unchanged == 4
