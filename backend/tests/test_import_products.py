"""Tests for scripts/import_products.py — the rate-table product importer."""
import os
import sys
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import Base, Product, ProductRate, ProductType

# make scripts/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import import_products  # noqa: E402


SAMPLE = [
    {"code": "INS-T-001", "name": "Trail plan", "type": "insurance",
     "provider": "AIA", "payment_tenor": 5, "professional_investor": True,
     "age_min": 0, "age_max": 65, "commission_schedule": "trail",
     "year_commissions": ["0.35", "0.04", "0.04"]},
    {"code": "INS-T-002", "name": "Upfront plan", "type": "insurance",
     "provider": "AIA", "payment_tenor": None, "professional_investor": False,
     "age_min": 0, "age_max": 65, "commission_schedule": "upfront",
     "year_commissions": ["0.038"]},
]


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autoflush=False)()
    yield s
    s.close()


def test_import_creates_products_and_per_company_rates(session):
    created, skipped, errors = import_products.import_products(session, SAMPLE)
    session.commit()
    assert (created, skipped, errors) == (2, 0, [])

    p = session.execute(select(Product).where(Product.code == "INS-T-001")).scalar_one()
    assert p.type == ProductType.INSURANCE
    assert p.commission_schedule.value == "trail"
    assert p.professional_investor is True
    assert p.payment_tenor == 5
    # insurance base rate is Yr1
    assert p.base_commission_rate == Decimal("0.35")
    # a ProductRate seeded for BOTH companies, mirroring POST /products
    rates = session.execute(
        select(ProductRate).where(ProductRate.product_id == p.id)).scalars().all()
    assert {r.company for r in rates} == {"heritree", "cpm"}
    assert all(r.year_commissions == ["0.35", "0.04", "0.04"] for r in rates)


def test_import_is_idempotent_by_code(session):
    import_products.import_products(session, SAMPLE); session.commit()
    created, skipped, errors = import_products.import_products(session, SAMPLE)
    session.commit()
    assert created == 0 and skipped == 2 and errors == []
    # no duplicate products or rate rows
    assert session.execute(select(Product)).scalars().all().__len__() == 2
    assert session.execute(select(ProductRate)).scalars().all().__len__() == 4


def test_import_reports_duplicate_codes_in_file(session):
    dup = SAMPLE + [dict(SAMPLE[0])]
    created, skipped, errors = import_products.import_products(session, dup)
    assert any("duplicate" in e for e in errors)
