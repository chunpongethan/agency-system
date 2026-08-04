# Agency Management System — Handoff

A full-stack system for a 4-level agency of relationship managers who sell insurance,
funds, EAM accounts and other services. It calculates commissions and upline overrides,
manages clients and transactions, produces statements/exports, locks periods, and runs
payouts — behind JWT auth with role-based row-level scoping.

Built end-to-end per [`docs/BUILD_PLAN.md`](BUILD_PLAN.md), phase by phase.

---

## What was built

| Area | Highlights |
|---|---|
| **Commission engine** | Direct + upline overrides keyed by level gap; effective-dated override rules selected on `trade_date`; upfront **and** trailing (periodic) commissions with `run_accruals`; clawbacks as negative reversal entries; deterministic, paid-aware regeneration. |
| **Auth & scoping** | JWT bearer auth (`passlib[bcrypt]` + `pyjwt`); roles `admin` / `manager` / `agent`; `visible_agent_ids` (single recursive CTE for a manager's subtree); every read/write scoped; out-of-scope access returns **403**, not an empty list. |
| **Reporting & payouts** | Agent statements + agency summary; CSV/PDF exports (reportlab) from a single `render_statement`; period locking with snapshot + 409 on locked-period trades (admin adjustment routing); idempotent payout runs snapshotting unpaid entries into immutable batches. |
| **Frontend** | React 18 + Vite + TypeScript; TanStack Query (server state) + TanStack Table (grids); React Router; typed API client. Screens: login, dashboard, clients (list/detail/edit), new transaction with **live commission preview**, hierarchy tree with rolled-up production, reports with CSV/PDF, admin (products, override rules, period lock/unlock, payouts). Role-gated UI. |
| **Production** | `DATABASE_URL`-parametrised (Postgres in Docker, SQLite in tests); Alembic baseline migration; Docker Compose (`db` + `api` + `web`); audit log on every commission-affecting change; CSV/XLSX bulk import with hierarchy validation and dry-run. |

**Test suite: 40 passing** (`backend/tests/`), including the scripted end-to-end scenario.
**Frontend: builds and type-checks clean.**

---

## How to run

### Local (dev)

Backend:
```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate    # (Windows Git Bash)
pip install -r requirements.txt
python ../scripts/seed.py            # demo data + prints the ledger
uvicorn app.main:app --reload        # http://localhost:8000/docs
pytest -q                            # 40 tests
```

Frontend:
```bash
cd frontend
npm install
npm run dev                          # http://localhost:5173
npm run build && npm run typecheck
```

**Demo logins** (password `demo1234`): `A001` admin (Grace), `A003` manager (Priya),
`A004` agent (Tom), `A007` agent in a sibling line (Sara).

### Docker (full stack)

```bash
docker compose up -d --build
# API  -> http://localhost:8000/docs
# Web  -> http://localhost:5173
docker compose down
```

`api` waits for Postgres, runs `alembic upgrade head`, seeds on first run, then serves
uvicorn. `web` is the built frontend behind nginx. Config is env-based (`POSTGRES_*`,
`SECRET_KEY`, `DATABASE_URL`, `VITE_API_URL`) — override the dev defaults in production.

> **Note on the Docker gate:** the compose file, Dockerfiles, nginx config and entrypoint
> are complete and `docker compose config` validates cleanly, but the `docker compose up`
> gate could **not be executed in the build environment**: Docker Desktop's Linux engine
> distro (`docker-desktop` in WSL2) is not installed on this machine — only
> `docker-desktop-data` exists — so the daemon never starts. Bring Docker Desktop up on a
> machine with a working engine and the stack should come up as described. Every component
> the stack depends on is independently verified: Alembic applies cleanly from empty, the
> API runs against `DATABASE_URL`, and the frontend build is produced identically.

### Bulk import

```bash
python scripts/bulk_import.py --agents scripts/sample_data/agents.csv \
    --clients scripts/sample_data/clients.csv          # dry-run (validates)
python scripts/bulk_import.py --agents ... --clients ... --commit   # writes
```
Accepts CSV or XLSX (sheets `agents` / `clients`), validates the hierarchy (levels,
upline one level above, no cycles), and only writes when clean.

---

## Resolved design decisions (as built)

1. **Override base** — overrides computed on the transaction notional, keyed by
   `OverrideRule(product_type, level_gap)`; effective-dated via `valid_from`/`valid_to`.
2. **Trailing commissions** — `Product.commission_schedule` (`upfront` | `trail`) with
   `trail_frequency` + `trail_periods`. Trail products accrue the rate per period;
   `run_accruals(as_of)` generates periods as they come due. Upfront = period 0 only.
3. **Multi-currency** — store transaction `currency`; compute/report in that currency.
   `base_currency` + nullable `fx_rate` columns exist for a later conversion pass (no FX
   conversion in v1).
4. **Split deals** — single closing agent per transaction in v1; a `# SPLIT:` note marks
   where a `transaction_splits` join table would go.
5. **Clawback** — cancelling a settled transaction writes negative reversal
   `CommissionEntry` rows (tagged `is_reversal`) so statements net to zero while showing
   the adjustment. Re-settling regenerates without them. Paid entries are immutable: a
   post-payout cancellation books the reversal as an unpaid negative that the next payout
   run picks up as an adjustment.

### `# DECISION:` notes left in code

- **Auth on `Agent`** (not a separate `User` table) — one login per agent keeps the
  principal ↔ hierarchy mapping trivial for scoping. (`models.py`)
- **Trail rate per period** — the base/override rate applies to the notional once per
  period for `trail_periods` periods. (`models.py`)
- **Baseline migration via `create_all`** — the initial Alembic revision builds the full
  schema from SQLAlchemy metadata (exact model match, clean on Postgres and SQLite, no
  duplicate native-enum creation). Later changes should use autogenerate.
  (`alembic/versions/0001_initial_schema.py`)

---

## Invariants preserved throughout

- Overrides keyed by **level gap** (1 = direct upline … 3 = top), not absolute level.
- The `CommissionEntry` ledger is **derived** — always regenerated, never hand-edited
  (paid entries are treated as immutable and preserved on regeneration).
- All money uses `Decimal`, quantised to 2dp at the boundary; never float.

---

## Layout

```
backend/
  app/
    models/models.py          entities + enums
    services/
      commission_engine.py    core: compute, preview, accruals, recompute
      agent_service.py         hierarchy validation
      scoping.py               visible_agent_ids / assert_visible
      reports.py               statements + agency summary
      periods.py               period locking + snapshots
      payouts.py               idempotent payout runs
      exports.py               CSV/PDF (shared render_statement)
      audit.py                 audit log
    security.py                hashing + JWT
    schemas/schemas.py         Pydantic I/O
    main.py                    FastAPI app, auth deps, all endpoints
  alembic/                     migrations (baseline 0001)
  tests/                       40 tests incl. e2e scenario
  Dockerfile, entrypoint.sh
frontend/
  src/
    api/         typed client + types
    auth/        AuthContext (JWT)
    components/   Layout, DataTable (TanStack Table), StatusBadge
    pages/        Login, Dashboard, Clients, ClientDetail, NewTransaction,
                  Hierarchy, Reports, Admin
  Dockerfile, nginx.conf
scripts/
  seed.py, bulk_import.py, db_ready.py, needs_seed.py, sample_data/
docker-compose.yml
```

## API surface (added on top of the starter)

```
POST /auth/login            GET  /auth/me
GET  /clients               GET/PATCH /clients/{id}      GET /clients/{id}/transactions
GET  /agents/{id}/transactions
POST /transactions/preview  POST /transactions/{id}/cancel
GET  /override-rules        POST /override-rules
POST /accruals/run          POST /reports/recompute
GET  /reports/agent/{id}/export   GET /reports/agency/export         (?format=csv|pdf)
GET  /periods/{ym}          POST /periods/{ym}/lock      POST /periods/{ym}/unlock
POST /payouts/run?period=YYYY-MM   GET /payouts/{ym}
GET  /audit
```
