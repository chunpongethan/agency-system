"""
Set insurance products' AFYP 轉換 (afyp_conversion) from their 供款年期.

Business rule (AFYP = Annualised First-Year Premium factor on the notional):
    供款年期 = 1 年      -> 10.00%   (0.1000)
    供款年期 = 2 年      -> 50.00%   (0.5000)
    供款年期 = 3 年      -> 33.33%   (0.3333)
    供款年期 = 整付       -> 10.00%   (0.1000)   (single-pay: null tenor + upfront)
    其他 (5年+ / 每年續保) -> unchanged (regular pay stays at 100%)

整付 (single premium) and 每年續保 (annual-renewal medical) both store
payment_tenor = NULL; they are told apart by commission_schedule (整付 is always
UPFRONT, 每年續保 always TRAIL), so 每年續保 is left untouched.

afyp_conversion is a SHARED product field, so this affects both companies.
Only INSURANCE products are considered. Idempotent; dry-run by default.

Usage:
    python scripts/set_afyp_by_tenor.py            # dry run
    python scripts/set_afyp_by_tenor.py --commit
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from decimal import Decimal

try:  # CJK labels below; keep output legible on a non-UTF-8 console (Windows).
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.models import Base, Product, ProductType, CommissionSchedule

TENOR_AFYP = {1: Decimal("0.1000"), 2: Decimal("0.5000"), 3: Decimal("0.3333")}
LUMP_AFYP = Decimal("0.1000")


def target_afyp(p: Product) -> Decimal | None:
    """The AFYP factor this product should have, or None to leave unchanged."""
    if p.type != ProductType.INSURANCE:
        return None
    if p.payment_tenor in TENOR_AFYP:
        return TENOR_AFYP[p.payment_tenor]
    # 整付 (single-pay): null tenor + upfront. 每年續保 (null + trail) is skipped.
    if p.payment_tenor is None and p.commission_schedule == CommissionSchedule.UPFRONT:
        return LUMP_AFYP
    return None


def apply(session):
    updated = unchanged = 0
    buckets: Counter = Counter()
    for p in session.execute(select(Product)).scalars():
        want = target_afyp(p)
        if want is None:
            continue
        label = "整付" if p.payment_tenor is None else f"{p.payment_tenor}年"
        buckets[label] += 1
        if p.afyp_conversion == want:
            unchanged += 1
            continue
        p.afyp_conversion = want
        updated += 1
    return updated, unchanged, buckets


def run(database_url: str, commit: bool) -> int:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    updated, unchanged, buckets = apply(session)
    print("AFYP conversion by 供款年期:")
    for label, n in sorted(buckets.items()):
        print(f"  {label:>6}: {n} product(s)")
    print(f"To update: {updated}   already correct: {unchanged}")

    if commit:
        session.commit()
        print("\nCommitted.")
    else:
        session.rollback()
        print("\nDry run -> nothing committed. Re-run with --commit to write.")
    session.close()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Set insurance AFYP conversion from payment tenor.")
    p.add_argument("--database-url",
                   default=os.getenv("DATABASE_URL", "sqlite:///./backend/agency.db"))
    p.add_argument("--commit", action="store_true", help="write to the DB (default: dry run)")
    args = p.parse_args()
    return run(args.database_url, args.commit)


if __name__ == "__main__":
    raise SystemExit(main())
