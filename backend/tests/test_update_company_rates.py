"""Tests for scripts/update_company_rates.py — per-company rate updates."""
import os
import sys
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import Base, Product, ProductRate, ProductType

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import update_company_rates  # noqa: E402


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autoflush=False)()
    # one shared insurance product with a rate for BOTH companies (as import seeds)
    p = Product(code="INS-X-001", name="Plan", type=ProductType.INSURANCE,
                base_commission_rate=Decimal("0.05"),
                commission_schedule="trail", year_commissions=["0.05", "0.01"])
    s.add(p); s.flush()
    for company in ("heritree", "cpm"):
        s.add(ProductRate(product_id=p.id, company=company,
                          base_commission_rate=Decimal("0.05"),
                          year_commissions=["0.05", "0.01"]))
    s.commit()
    yield s
    s.close()


def _rate(session, company):
    p = session.execute(select(Product).where(Product.code == "INS-X-001")).scalar_one()
    return session.execute(select(ProductRate).where(
        ProductRate.product_id == p.id, ProductRate.company == company)).scalar_one()


def test_updates_only_target_company(session):
    rows = [{"code": "INS-X-001", "year_commissions": ["0.021", "0.003"]}]
    updated, unchanged, missing = update_company_rates.update_rates(session, "heritree", rows)
    session.commit()
    assert (updated, unchanged, missing) == (1, 0, [])
    # heritree changed; base = Yr1
    h = _rate(session, "heritree")
    assert h.year_commissions == ["0.021", "0.003"]
    assert h.base_commission_rate == Decimal("0.021")
    # cpm untouched
    c = _rate(session, "cpm")
    assert c.year_commissions == ["0.05", "0.01"]
    assert c.base_commission_rate == Decimal("0.05")


def test_reports_missing_codes(session):
    rows = [{"code": "NOPE", "year_commissions": ["0.1"]}]
    updated, unchanged, missing = update_company_rates.update_rates(session, "heritree", rows)
    assert updated == 0 and missing == ["NOPE"]


def test_no_op_when_rate_unchanged(session):
    rows = [{"code": "INS-X-001", "year_commissions": ["0.05", "0.01"]}]
    updated, unchanged, missing = update_company_rates.update_rates(session, "heritree", rows)
    assert updated == 0 and unchanged == 1
