# Agency Management System

Starter codebase for a multi-level agency: agents in a 4-level hierarchy sell
insurance, funds, EAM accounts and other services; the system calculates
commissions and upline overrides, generates reports, and manages client records.

**Status: built end-to-end.** Backend (FastAPI, 40 passing tests), commission engine
(effective-dated rules, trailing commissions, clawbacks), JWT auth with role-based
row-level scoping, reporting + CSV/PDF exports, period locking, idempotent payouts, a
React + Vite + TypeScript frontend, Alembic migrations, an audit log, bulk import, and a
Docker Compose stack.

See **[`docs/HANDOFF.md`](docs/HANDOFF.md)** for what was built, how to run it (local +
Docker), the resolved design decisions, and the API surface. The original phased plan is
in [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md).

### Run it

```bash
# Backend
cd backend && pip install -r requirements.txt
python ../scripts/seed.py && uvicorn app.main:app --reload   # :8000/docs
# Frontend
cd frontend && npm install && npm run dev                    # :5173
# Or the whole stack
docker compose up -d --build                                 # web :5173, api :8000
```

Demo logins (password `demo1234`): `A001` admin, `A003` manager, `A004` agent.

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
