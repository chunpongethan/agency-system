"""
Import insurance products from a rate-table JSON (e.g. the TR 費率總表 export).

Mirrors the POST /products write path: creates each Product and seeds a
ProductRate for BOTH companies (heritree, cpm) from the same Yr1..Yr10 schedule
— products are shared; each company may diverge its rate later. For insurance
the base_commission_rate is the Yr1 commission.

Idempotent by product code: an existing code is left untouched (skipped), so the
script is safe to re-run and to ship on every deploy. Dry-run by default.

--rate-company <key> gives the file's rates to ONE company only (e.g. a 承瑞-only
card): that company's ProductRate gets the Yr1..Yr10 schedule, while the
product's shared default and every other company's ProductRate are set to an
explicit 0, so neither the engine's shared-rate fallback nor the startup
backfill (_seed_product_rates) can hand those rates to the other company.

--strict-codes reports "code already exists" as an error when the existing
product's name differs, so new codes can't silently collide with products made
in the UI.

JSON shape (see scripts/data/insurance_rates_2026Q3.json):
    { "products": [ {code, name, type, provider, payment_tenor,
                     professional_investor, age_min, age_max,
                     commission_schedule, year_commissions:[...],
                     base_commission_rate}, ... ] }

Usage:
    python scripts/import_products.py --file scripts/data/insurance_rates_2026Q3.json
    python scripts/import_products.py --file <path> --commit
    python scripts/import_products.py --file scripts/data/insurance_products_2026Q4_new.json \
        --rate-company heritree --strict-codes --commit
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


def import_products(session, products: list[dict], rate_company: str | None = None,
                    strict_codes: bool = False) -> tuple[int, int, list[str]]:
    """Returns (created, skipped, errors). See the module docstring for the options."""
    if rate_company is not None and rate_company not in COMPANIES:
        return 0, 0, [f"unknown company {rate_company!r} (expected one of {COMPANIES})"]
    existing = dict(session.execute(select(Product.code, Product.name)).all())
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
            if strict_codes and existing[code] != row.get("name"):
                errors.append(f"{code}: already used by a different product ({existing[code]!r})")
                continue
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

        zero = Decimal("0")
        product = Product(
            code=code,
            name=row["name"],
            type=ptype,
            provider=row.get("provider"),
            base_commission_rate=base if rate_company is None else zero,
            afyp_conversion=Decimal(str(row.get("afyp_conversion", "1"))),
            commission_schedule=row.get("commission_schedule", "upfront"),
            payment_tenor=row.get("payment_tenor"),
            professional_investor=row.get("professional_investor"),
            age_min=row.get("age_min"),
            age_max=row.get("age_max"),
            year_commissions=(year_comm or None) if rate_company is None else None,
            is_active=True,
        )
        session.add(product)
        session.flush()  # assign id for the ProductRate rows
        for company in COMPANIES:
            gets = rate_company is None or company == rate_company
            session.add(ProductRate(
                product_id=product.id, company=company,
                base_commission_rate=base if gets else zero,
                year_commissions=(year_comm or None) if gets else None,
            ))
        created += 1
    return created, skipped, errors


def run(path: str, database_url: str, commit: bool, rate_company: str | None = None,
        strict_codes: bool = False) -> int:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    products = data.get("products", data if isinstance(data, list) else [])

    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    created, skipped, errors = import_products(session, products, rate_company, strict_codes)

    print(f"File: {path}")
    print(f"Parsed {len(products)} product(s)."
          + (f"  Rates for {rate_company} only (other companies get 0)." if rate_company else ""))
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
    p.add_argument("--rate-company", choices=COMPANIES,
                   help="give the file's rates to this company only; others get an explicit 0")
    p.add_argument("--strict-codes", action="store_true",
                   help="error if a code already exists with a different name")
    args = p.parse_args()
    return run(args.file, args.database_url, args.commit, args.rate_company, args.strict_codes)


if __name__ == "__main__":
    raise SystemExit(main())
