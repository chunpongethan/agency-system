# Agency Management System — Build Plan (Claude Code, end-to-end)

This is an executable build plan. You (Claude Code) are to build the **entire system**
from the starter in this repo to a running, tested, dockerised full-stack application —
without waiting for further input. Where a decision is needed, this plan states the
default to use. Only stop if a phase gate fails and you cannot resolve it.

## How to run this build

Work through the phases in order. Each phase has an explicit **Definition of done** and a
**gate command** that must pass before moving on. After each phase: run the gate, fix any
failures, commit with the stated message, then continue. Do not skip phases and do not
ask for confirmation between phases — this document is the authorisation.

```
Phase 0  Orient & verify starter
Phase 1  Harden the commission core
Phase 2  Auth, roles & row-level scoping
Phase 3  Reporting, exports & payout runs
Phase 4  Frontend (React + Vite)
Phase 5  Production: Postgres, Alembic, Docker, seed/import
Phase 6  Final acceptance
```

Target stack: Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2, Alembic, PostgreSQL
(SQLite for tests), React 18 + Vite + TypeScript, TanStack Query + Table, Docker Compose.

---

## What the system does

Manage a **4-level hierarchy of relationship managers (agents)** who sell **insurance
plans, funds, EAM accounts, and other services** to clients. Each product carries a
**pre-set commission** for the closing agent; **uplines earn overrides** on downline
sales. The system **calculates commissions and overrides, generates reports**, and lets
agents **manage their clients' profiles and transaction history**.

## Resolved design decisions (build to these — do not deviate)

1. **Override base:** overrides are computed on the **transaction notional** (same base as
   the direct commission), keyed by `OverrideRule(product_type, level_gap)`. This is the
   implemented model — keep it.
2. **Trailing commissions:** support **both upfront and periodic trail**. In Phase 1 add a
   `commission_schedule` to `Product` (`upfront` | `trail`) with a `trail_frequency`
   (monthly/quarterly/annual) and `trail_periods`. Upfront products behave exactly as
   today; trail products accrue on a schedule (see Phase 1).
3. **Multi-currency:** store the transaction `currency`; compute and report commissions in
   the **transaction currency** (no FX conversion in v1). Add a `base_currency` column and
   a nullable `fx_rate` for a later conversion pass, but do not convert yet.
4. **Split deals:** single closing agent per transaction in v1. Leave a `# SPLIT:` note in
   the model where a join table would go, but do not build splits.
5. **Clawback:** cancellation writes **negative reversal entries** rather than deleting, so
   statements show the adjustment (Phase 1).

Anything not covered here: choose the simplest option consistent with the above, leave a
short `# DECISION:` comment explaining the choice, and continue.

## Architecture

```
Frontend (React+Vite+TS)  --REST/JSON, JWT bearer-->  FastAPI backend  <-->  Postgres
                                                            |                (SQLite in tests)
                                                     Commission engine
                                                     (core business logic)
```

## Data model (starter — already implemented)

| Entity | Purpose | Key fields |
|---|---|---|
| `Agent` | Hierarchy node | `level` (L1–L4), `upline_id` (self-FK) |
| `Client` | Owned by one agent | `agent_id`, profile fields |
| `Product` | Sellable item | `type`, `base_commission_rate` |
| `OverrideRule` | Upline override rates | `product_type`, `level_gap`, `override_rate` |
| `Transaction` | A sale | `notional`, `status`, `agent_id` (closer) |
| `CommissionEntry` | Ledger row | `kind` (direct/override), `amount`, `level_gap` |

**Invariants to preserve across all phases:**
- Overrides are keyed by **level gap** (1 = direct upline … 3 = top), not absolute level.
- The `CommissionEntry` ledger is **derived** — never hand-edit it; always regenerate.
- All money uses `Decimal`, quantised to 2dp at the boundary. Never use float for money.

---

## Phase 0 — Orient & verify starter

**Do:**
1. Read `README.md`, `backend/app/models/models.py`, and
   `backend/app/services/commission_engine.py` to load the domain model.
2. Create and activate a virtualenv; `pip install -r backend/requirements.txt`.
3. Initialise git if not present; commit the starter as the baseline.

**Definition of done:** the existing suite passes and the seed runs.

**Gate:**
```bash
cd backend && pytest -q && cd .. && python scripts/seed.py
```
**Commit:** `chore: baseline starter verified`

---

## Phase 1 — Harden the commission core `[backend]`

**Do:**
1. Replace every `datetime.utcnow()` with `datetime.now(UTC)`.
2. **Validation** on agent creation: `level` in 1..4; if `upline_id` set, the upline's
   level must be exactly one above (`upline.level == agent.level - 1`); reject cycles
   (an agent cannot be its own ancestor). Return HTTP 422 with a clear message.
3. **Effective-dated override rules:** add `valid_from: date` and `valid_to: date | None`
   to `OverrideRule`. The engine selects the rule in force on the transaction's
   `trade_date`. Keep a single active rule per `(product_type, level_gap)` at any date.
4. **Trail schedule (decision 2):** add to `Product`: `commission_schedule`
   (`upfront` default | `trail`), `trail_frequency` (nullable), `trail_periods` (int,
   nullable). For `trail` products, settling generates the *first* period's direct+override
   entries and records remaining scheduled accrual dates; add `run_accruals(as_of: date)`
   that generates due entries up to `as_of`. Upfront products stay as today (period 0 only).
5. **Clawback (decision 5):** cancelling a settled transaction writes negative-amount
   reversal `CommissionEntry` rows (one per original entry), tagged so reports net them
   out. Re-settling reverses the reversal.
6. Extend `recompute_all` to rebuild upfront + already-due trail entries deterministically.

**Definition of done:** new unit tests cover validation rejects, effective-dated rule
selection, trail accrual over N periods, and clawback netting — all passing alongside the
original four.

**Gate:**
```bash
cd backend && pytest -q
```
**Commit:** `feat: harden commission core (validation, trail, clawback, dated rules)`

---

## Phase 2 — Auth, roles & row-level scoping `[backend]`

Highest-risk phase. Build the scoping helper first, test it in isolation, then apply it
everywhere.

**Do:**
1. **Auth:** JWT bearer auth. Add `password_hash` to `Agent` (or a separate `User` linked
   to `Agent` — your call; document it). Endpoints: `POST /auth/login` → access token;
   `GET /auth/me`. Use `passlib[bcrypt]` and `pyjwt` (or `python-jose`). Principal carries
   a `role`: `admin` | `manager` | `agent`.
2. **Scoping helper** — `visible_agent_ids(current) -> set[int]`:
   - `agent`: just their own id.
   - `manager`: their id plus their entire downline subtree (one recursive CTE walking
     `upline_id` downward — not N queries).
   - `admin`: all agents.
   Unit-test against a 4-level tree before wiring into endpoints.
3. **Apply scoping to every read** (clients, transactions, commission entries, reports).
   An explicit request for an out-of-scope id returns 403, not an empty list.
4. **Apply scoping to writes**: an agent may only create clients/transactions under an
   agent id within their scope.
5. Replace the stubbed `get_current_agent` in `main.py` with the real dependency.

**Definition of done:** scoping tests prove agent-isolation, manager-subtree visibility,
and admin-all; every data endpoint enforces it; login issues a working token.

**Gate:**
```bash
cd backend && pytest -q -k "scope or auth"
```
**Commit:** `feat: JWT auth, roles, and row-level scoping`

---

## Phase 3 — Reporting, exports & payout runs `[backend]`

**Do:**
1. **Period locking:** a `Period` (year+month) is `open` or `locked`. Locking freezes its
   statements; transactions dated into a locked period raise 409 unless an admin override
   routes them to the next open period as an adjustment. Locked periods read a snapshot.
2. **Exports:** CSV and PDF for agent statements and the agency summary. Use `reportlab`
   or `weasyprint`; a single `render_statement()` feeds both API and exporters.
3. **Payout runs:** `POST /payouts/run?period=YYYY-MM` snapshots all unpaid, non-reversed
   entries for the period into a `Payout` batch, marks them `paid`, returns a per-agent
   payable summary. Payouts are immutable; a later reversal becomes a negative adjustment
   in the next run. Idempotent per period.

**Definition of done:** tests cover locking, an idempotent payout run marking entries paid,
and CSV/PDF generating without error for the seed data.

**Gate:**
```bash
cd backend && pytest -q -k "report or payout or period"
```
**Commit:** `feat: period locking, exports, and payout runs`

---

## Phase 4 — Frontend `[frontend]`

Scaffold Vite + React + TypeScript in `frontend/`. TanStack Query for server state,
TanStack Table for ledger grids, React Router for routing, a typed API client against the
FastAPI schema. Clean, minimal styling (Tailwind or CSS modules) — internal tool, clarity
over flourish.

**Screens, in build order:**
1. **Login** → store token, attach as bearer, redirect to dashboard.
2. **Agent dashboard** — my commissions this period (direct vs override split), my clients,
   recent transactions.
3. **Client management** — list + detail; edit profile; per-client transaction history.
4. **New transaction** — client + product + notional, with a **live commission preview**
   (add a `POST /transactions/preview` endpoint that runs the engine without persisting).
5. **Hierarchy view** — org tree with rolled-up production per node (managers + admin).
6. **Reports** — agent statement + agency summary, date filters, CSV/PDF download buttons.
7. **Admin** — CRUD for products and override rules (admin only); period lock/unlock;
   trigger payout runs.

Gate the UI to the principal's role, but rely on the backend as the source of truth — the
frontend gate is convenience, not security.

**Definition of done:** the app builds, type-checks, and runs against the live backend; an
agent can log in, view their dashboard, open a client, create a transaction and see the
live preview match the settled result; an admin can edit an override rule and run a payout.

**Gate:**
```bash
cd frontend && npm run build && npm run typecheck
```
**Commit:** `feat: React frontend (dashboard, clients, transactions, reports, admin)`

---

## Phase 5 — Production readiness

**Do:**
1. **Postgres + Alembic:** parametrise `DATABASE_URL` (Postgres in Docker, SQLite in
   tests). Generate an initial migration for the full schema; run `alembic upgrade head`
   at container startup.
2. **Docker Compose:** services `db` (Postgres), `api` (uvicorn), `web` (built frontend via
   nginx or `vite preview`). `docker compose up` brings the stack up with seed loaded on
   first run. Env-based config; no secrets in code.
3. **Audit log:** an `AuditEntry` on every commission-affecting change (create/settle/
   cancel transaction, edit rule, lock period, run payout) — who, when, what, before/after.
4. **Bulk import:** a script to onboard agents and clients from CSV/XLSX (map columns →
   models, validate hierarchy integrity, dry-run then commit).

**Definition of done:** `docker compose up` yields a working app at the documented ports
with seed data; migrations apply cleanly from empty; audit entries appear for covered
actions.

**Gate:**
```bash
docker compose up -d --build && sleep 15 && \
  curl -fsS http://localhost:8000/docs > /dev/null && \
  curl -fsS http://localhost:5173 > /dev/null && \
  docker compose down
```
**Commit:** `feat: postgres, alembic, docker compose, audit log, bulk import`

---

## Phase 6 — Final acceptance

Run the whole suite and a scripted end-to-end scenario, then write `docs/HANDOFF.md`
summarising what was built, how to run it, the resolved decisions, and any `# DECISION:`
notes left in code.

**End-to-end scenario to script and assert:**
1. Seed a 4-level agency with one upfront and one trail product.
2. Agent logs in, creates a client, books and settles an insurance sale.
3. Assert the ledger: direct to closer + overrides at gaps 1/2/3, amounts matching rates.
4. Book and settle a trail fund; run accruals forward N periods; assert per-period entries.
5. Cancel the insurance sale; assert reversal entries net its statement to zero.
6. Lock the period; run a payout; assert entries marked paid and the payable summary.
7. Manager logs in and sees the whole subtree; a sibling agent cannot see another line's
   clients.

**Gate:**
```bash
cd backend && pytest -q && cd ../frontend && npm run build
```
**Commit:** `chore: final acceptance — full system green`

---

## API surface (starter — extend as phases require)

```
POST /agents                       GET  /agents
GET  /agents/{id}/downlines        GET  /agents/{id}/clients
POST /clients                      POST /products    GET /products
POST /transactions                 POST /transactions/{id}/settle
GET  /clients/{id}/transactions
GET  /reports/agent/{id}?start&end GET  /reports/agency?start&end
POST /reports/recompute
```
New endpoints to add: `/auth/login`, `/auth/me`, `/transactions/preview`,
`/transactions/{id}/cancel`, `/periods/{ym}/lock`, `/payouts/run`, plus export routes.

## Running the starter (before you build)

```bash
cd backend
pip install -r requirements.txt
python ../scripts/seed.py          # demo data + prints the commission ledger
uvicorn app.main:app --reload      # http://localhost:8000/docs
pytest tests/
```

## Guardrails while building

- Keep the four money/ledger invariants (top of this doc) true in every phase.
- Every phase ends green: never move on with a failing gate.
- Prefer many small, tested services over large endpoints with inline logic.
- Commit per phase with the stated message so history reads as the build sequence.
