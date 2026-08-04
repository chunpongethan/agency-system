# Agency Management System

Starter codebase for a multi-level agency: agents in a 4-level hierarchy sell
insurance, funds, EAM accounts and other services; the system calculates
commissions and upline overrides, generates reports, and manages client records.

**Working today:** data model, commission engine (tested), reports, REST API, demo seed.
**To build:** the full system — auth/roles, frontend, exports, payouts, production. The
plan in [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) is written for Claude Code to build
end-to-end autonomously: phase-gated, with all design decisions resolved and a pass/fail
gate command per phase. Hand it the repo and say "build this following docs/BUILD_PLAN.md".

## Quick start

```bash
cd backend
pip install -r requirements.txt
python ../scripts/seed.py       # loads demo agency, prints the commission ledger
uvicorn app.main:app --reload   # API + docs at http://localhost:8000/docs
pytest tests/
```

## Layout

```
backend/
  app/
    models/      SQLAlchemy models (hierarchy, products, txns, ledger)
    services/    commission_engine.py  ← core logic;  reports.py
    schemas/     Pydantic I/O
    main.py      FastAPI app + endpoints
  tests/         engine tests (pytest)
scripts/seed.py  demo data
docs/BUILD_PLAN.md   phased plan for Claude Code
```

## How commissions work

A settled transaction pays the **closing agent** a direct commission
(`product.base_commission_rate × notional`), then walks up the `upline` chain paying
each qualifying upline an **override** from `OverrideRule` keyed on
`(product_type, level_gap)`. The `CommissionEntry` table is a derived ledger — rebuild
it any time with `POST /reports/recompute`.
