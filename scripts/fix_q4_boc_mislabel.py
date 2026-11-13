"""
One-off repair for the 承瑞 2026 Q4 import (run once, after commit dcd3757's data).

The 承瑞 Q4 PDF has no 中銀人壽 BOC Life heading, so its five BOC plans were read as
China Life and created as 21 new products INS-CLIFE-028..048. The corrected data
files map those rows to the existing BOC Life products (INS-BOC-001..019) and to
new BOC products INS-BOC-021..027 instead.

This removes the 21 mislabelled products (and their per-company rate rows). It is
deliberately strict: every code must still have exactly the name and provider it
was created with, and if ANY of them is used by a transaction nothing is deleted.
It also cleans INS-CPIC-019's name, which picked up the PDF's page footer
("…≥100,000USD20 / 22 · PI") — only while the name is still exactly that.

Dry-run by default.

Then re-run the corrected imports:
    python scripts/import_products.py --file scripts/data/insurance_products_2026Q4_new.json \
        --rate-company heritree --strict-codes --commit
    python scripts/update_company_rates.py --file scripts/data/heritree_rates_2026Q4.json \
        --company heritree --commit

Usage:
    python scripts/fix_q4_boc_mislabel.py            # dry run
    python scripts/fix_q4_boc_mislabel.py --commit
"""
from __future__ import annotations

import argparse
import os
import sys

try:  # CJK names below; keep output legible on a non-UTF-8 console
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from app.models.models import Base, Product, ProductRate, Transaction

WRONG_PROVIDER = "China Life"
WRONG = [
    ('INS-CLIFE-028', '鑄富世代環球終身壽險計劃 (Eternal Fortune Global Whole Life Insurance Plan) · 5年 · PI'),
    ('INS-CLIFE-029', '鑄富世代環球終身壽險計劃 (Eternal Fortune Global Whole Life Insurance Plan) · 5年'),
    ('INS-CLIFE-030', '寰御安心環球終身保險計劃 (Assure Together Global Whole Life Insurance Plan) · 2年 · HKD & USD · PI'),
    ('INS-CLIFE-031', '寰御安心環球終身保險計劃 (Assure Together Global Whole Life Insurance Plan) · 2年 · CNY · PI'),
    ('INS-CLIFE-032', '寰御安心環球終身保險計劃 (Assure Together Global Whole Life Insurance Plan) · 2年 · HKD & USD'),
    ('INS-CLIFE-033', '寰御安心環球終身保險計劃 (Assure Together Global Whole Life Insurance Plan) · 2年 · CNY'),
    ('INS-CLIFE-034', '寰御安心環球終身保險計劃 (Assure Together Global Whole Life Insurance Plan) · 5年 · HKD & USD · PI'),
    ('INS-CLIFE-035', '寰御安心環球終身保險計劃 (Assure Together Global Whole Life Insurance Plan) · 5年 · CNY · PI'),
    ('INS-CLIFE-036', '寰御安心環球終身保險計劃 (Assure Together Global Whole Life Insurance Plan) · 5年 · HKD & USD'),
    ('INS-CLIFE-037', '寰御安心環球終身保險計劃 (Assure Together Global Whole Life Insurance Plan) · 5年 · CNY'),
    ('INS-CLIFE-038', '薪火傳承環球終身壽險計劃 (Glamorous Glow Global Whole Life Insurance Plan) · 整付'),
    ('INS-CLIFE-039', '薪火傳承環球終身壽險計劃 (Glamorous Glow Global Whole Life Insurance Plan) · 2年 · PI'),
    ('INS-CLIFE-040', '薪火傳承環球終身壽險計劃 (Glamorous Glow Global Whole Life Insurance Plan) · 2年'),
    ('INS-CLIFE-041', '薪火傳承環球終身壽險計劃 (Glamorous Glow Global Whole Life Insurance Plan) · 3年 · PI'),
    ('INS-CLIFE-042', '薪火傳承環球終身壽險計劃 (Glamorous Glow Global Whole Life Insurance Plan) · 3年'),
    ('INS-CLIFE-043', '薪火傳承環球終身壽險計劃 (Glamorous Glow Global Whole Life Insurance Plan) · 5年 · PI'),
    ('INS-CLIFE-044', '薪火傳承環球終身壽險計劃 (Glamorous Glow Global Whole Life Insurance Plan) · 5年'),
    ('INS-CLIFE-045', '延期年金計劃(終身) (Deferred Annuity (Lifetime)) · 5年'),
    ('INS-CLIFE-046', '月悅出息終身享保險計劃 (IncomeJoy Lifelong Insurance Plan) · 2年'),
    ('INS-CLIFE-047', '月悅出息終身享保險計劃 (IncomeJoy Lifelong Insurance Plan) · 5年 · PI'),
    ('INS-CLIFE-048', '月悅出息終身享保險計劃 (IncomeJoy Lifelong Insurance Plan) · 5年'),
]


RENAMES = [
    ('INS-CPIC-019',
     '世代悅享儲蓄保險計劃3 (Everlasting Joy Savings Insurance Plan 3) · 2年 · 特別折扣 20%，總保費 ≥100,000USD20 / 22 · PI',
     '世代悅享儲蓄保險計劃3 (Everlasting Joy Savings Insurance Plan 3) · 2年 · 特別折扣 20%，總保費 ≥100,000USD · PI'),
]


def renames(session):
    """Products whose name still carries the PDF page footer ("20 / 22")."""
    out = []
    for code, old, new in RENAMES:
        p = session.execute(select(Product).where(Product.code == code)).scalars().first()
        if p is not None and p.name == old:
            out.append((p, new))
    return out


def plan(session):
    """Returns (products_to_delete, problems)."""
    found, problems = [], []
    for code, name in WRONG:
        p = session.execute(select(Product).where(Product.code == code)).scalars().first()
        if p is None:
            continue                     # already removed (or never created) — fine
        if p.name != name or p.provider != WRONG_PROVIDER:
            problems.append(f"{code}: is now {p.name!r} / {p.provider!r} — not the mislabelled product")
            continue
        used = session.execute(select(func.count()).select_from(Transaction)
                               .where(Transaction.product_id == p.id)).scalar()
        if used:
            problems.append(f"{code}: used by {used} transaction(s)")
            continue
        found.append(p)
    return found, problems


def run(database_url: str, commit: bool) -> int:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    found, problems = plan(session)
    to_rename = renames(session)
    print(f"Mislabelled products present: {len(found)} of {len(WRONG)}")
    for p in found:
        print(f"  - {p.code}  {p.name}")
    print(f"Names to clean: {len(to_rename)}")
    for p, new in to_rename:
        print(f"  - {p.code}  -> {new}")
    if problems:
        print(f"\n{len(problems)} problem(s) — nothing changed:")
        for e in problems:
            print(f"  - {e}")
        session.close()
        return 1
    if not found and not to_rename:
        print("Nothing to do.")
        session.close()
        return 0
    ids = [p.id for p in found]
    if ids:
        session.execute(delete(ProductRate).where(ProductRate.product_id.in_(ids)))
        session.execute(delete(Product).where(Product.id.in_(ids)))
    for p, new in to_rename:
        p.name = new
    if commit:
        session.commit()
        print(f"\nDeleted {len(ids)} product(s), renamed {len(to_rename)}. Committed.")
    else:
        session.rollback()
        print("\nDry run -> nothing deleted. Re-run with --commit.")
    session.close()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Remove the 21 mislabelled 承瑞 Q4 BOC products.")
    p.add_argument("--database-url", default=os.getenv("DATABASE_URL", "sqlite:///./backend/agency.db"))
    p.add_argument("--commit", action="store_true")
    args = p.parse_args()
    return run(args.database_url, args.commit)


if __name__ == "__main__":
    raise SystemExit(main())
