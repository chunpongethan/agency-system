"""
Import insurance products from a rate-table JSON (e.g. the TR 費率總表 export).

Mirrors the POST /products write path: creates each Product and seeds a
ProductRate for BOTH companies (heritree, cpm) from the same Yr1..Yr10 schedule
— products are shared; each company may diverge its rate later. For insurance
the base_commission_rate is the Yr1 commission.

Idempotent by product code: an existing code is left untouched (skipped), so the
script is safe to re-run and to ship on every deploy. Dry-run by default.

JSON shape (see scripts/data/insurance_rates_2026Q3.json):
    { "products": [ {code, name, type, provider, payment_tenor,
                     professional_investor, age_min, age_max,
                     commission_schedule, year_commissions:[...],
                     base_commission_rate}, ... ] }

Usage:
    python scripts/import_products.py --file scripts/data/insurance_rates_2026Q3.json
    python scripts/import_products.py --file <path> --commit
    python scripts/import_products.py --file <path> --commit \
        --database-url postgresql+psycopg2://user:pass@host/db
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.models import Base, Product, ProductRate, ProductType

COMPANIES = ("heritree", "cpm")


def _to_decimals(values):
    return [str(Decimal(str(v))) for v in (values or [])]


def import_products(session, products: list[dict]) -> tuple[int, int, list[str]]:
    """Returns (created, skipped, errors)."""
    existing = {row[0] for row in session.execute(select(Product.code))}
    created = skipped = 0
    errors: list[str] = []
    seen: set[str] = set()

    for i, row in enumerate(products, start=1):
        code = (row.get("code") or "").strip()
        if not code:
            errors.append(f"item {i}: missing code")
            continue
        if code in seen:
            errors.append(f"item {i}: duplicate code in file: {code}")
            continue
        seen.add(code)
        if code in existing:
            skipped += 1
            continue
        try:
            ptype = ProductType(row["type"])
        except (KeyError, ValueError):
            errors.append(f"{code}: invalid type {row.get('type')!r}")
            continue

        year_comm = _to_decimals(row.get("year_commissions"))
        # For insurance the base (upfront) rate is Yr1.
        if ptype == ProductType.INSURANCE and year_comm:
            base = Decimal(str(year_comm[0]))
        else:
            base = Decimal(str(row.get("base_commission_rate", "0")))

        product = Product(
            code=code,
            name=row["name"],
            type=ptype,
            provider=row.get("provider"),
            base_commission_rate=base,
            afyp_conversion=Decimal(str(row.get("afyp_conversion", "1"))),
            commission_schedule=row.get("commission_schedule", "upfront"),
            payment_tenor=row.get("payment_tenor"),
            professional_investor=row.get("professional_investor"),
            age_min=row.get("age_min"),
            age_max=row.get("age_max"),
            year_commissions=year_comm or None,
            is_active=True,
        )
        session.add(product)
        session.flush()  # assign id for the ProductRate rows
        for company in COMPANIES:
            session.add(ProductRate(
                product_id=product.id, company=company,
                base_commission_rate=base,
                year_commissions=year_comm or None,
            ))
        created += 1
    return created, skipped, errors


def run(path: str, database_url: str, commit: bool) -> int:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    products = data.get("products", data if isinstance(data, list) else [])

    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    created, skipped, errors = import_products(session, products)

    print(f"File: {path}")
    print(f"Parsed {len(products)} product(s).")
    print(f"To create: {created}   already present (skipped): {skipped}")
    if errors:
        print(f"\n{len(errors)} problem(s):")
        for e in errors:
            print(f"  - {e}")
        session.rollback()
        session.close()
        print("\nErrors present -> nothing committed (fix and retry).")
        return 1

    if commit:
        session.commit()
        print("\nCommitted.")
    else:
        session.rollback()
        print("\nDry run -> nothing committed. Re-run with --commit to write.")
    session.close()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Import insurance products from rate-table JSON.")
    p.add_argument("--file", required=True, help="Path to the rate-table JSON")
    p.add_argument("--database-url",
                   default=os.getenv("DATABASE_URL", "sqlite:///./backend/agency.db"))
    p.add_argument("--commit", action="store_true", help="write to the DB (default: dry run)")
    args = p.parse_args()
    return run(args.file, args.database_url, args.commit)


if __name__ == "__main__":
    raise SystemExit(main())
