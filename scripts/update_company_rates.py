"""
Update ONE company's commission rates for existing products from a rate JSON.

Products are shared across companies; each company keeps its own ProductRate
(基本比率 + Yr1..Yr10 schedule). This script rewrites a single company's
ProductRate for each product matched BY CODE — it never touches the other
company's rates or any shared product field (name, type, schedule, …).

For insurance the base_commission_rate is set to Yr1 (mirrors PATCH /products).
Matching is by product code; a code with no product is reported and skipped.
Dry-run by default; only mutates with --commit.

JSON shape:
    { "products": [ {code, year_commissions:[...], base_commission_rate?}, ... ] }

Usage:
    python scripts/update_company_rates.py --file scripts/data/heritree_rates_2026Q2.json --company heritree
    python scripts/update_company_rates.py --file <path> --company heritree --commit
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


def _decs(values):
    return [str(Decimal(str(v))) for v in (values or [])]


def update_rates(session, company: str, rows: list[dict]):
    """Returns (updated, unchanged, missing_codes)."""
    by_code = {p.code: p for p in session.execute(select(Product)).scalars()}
    updated = unchanged = 0
    missing: list[str] = []
    for row in rows:
        code = (row.get("code") or "").strip()
        product = by_code.get(code)
        if product is None:
            missing.append(code)
            continue
        year_comm = _decs(row.get("year_commissions"))
        if product.type == ProductType.INSURANCE and year_comm:
            base = Decimal(str(year_comm[0]))
        else:
            base = Decimal(str(row.get("base_commission_rate", "0")))

        pr = session.execute(select(ProductRate).where(
            ProductRate.product_id == product.id,
            ProductRate.company == company)).scalars().first()
        if pr is None:
            pr = ProductRate(product_id=product.id, company=company)
            session.add(pr)
            pr.base_commission_rate = base
            pr.year_commissions = year_comm or None
            updated += 1
            continue
        # Detect a no-op so dry-runs report real changes only.
        same = (pr.base_commission_rate == base and
                (pr.year_commissions or None) == (year_comm or None))
        if same:
            unchanged += 1
            continue
        pr.base_commission_rate = base
        pr.year_commissions = year_comm or None
        updated += 1
    return updated, unchanged, missing


def run(path: str, company: str, database_url: str, commit: bool) -> int:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    rows = data.get("products", data if isinstance(data, list) else [])

    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    updated, unchanged, missing = update_rates(session, company, rows)

    print(f"File: {path}")
    print(f"Company: {company}")
    print(f"Parsed {len(rows)} rate row(s).")
    print(f"To update: {updated}   unchanged: {unchanged}   missing product code: {len(missing)}")
    if missing:
        print("\nCodes with no matching product (skipped):")
        for c in missing[:50]:
            print(f"  - {c}")
        if len(missing) > 50:
            print(f"  ... and {len(missing) - 50} more")

    if commit:
        session.commit()
        print("\nCommitted.")
    else:
        session.rollback()
        print("\nDry run -> nothing committed. Re-run with --commit to write.")
    session.close()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Update one company's product rates from a rate JSON.")
    p.add_argument("--file", required=True, help="Path to the rate JSON")
    p.add_argument("--company", required=True, help="Company key, e.g. heritree or cpm")
    p.add_argument("--database-url",
                   default=os.getenv("DATABASE_URL", "sqlite:///./backend/agency.db"))
    p.add_argument("--commit", action="store_true", help="write to the DB (default: dry run)")
    args = p.parse_args()
    return run(args.file, args.company, args.database_url, args.commit)


if __name__ == "__main__":
    raise SystemExit(main())
