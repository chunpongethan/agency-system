"""
FastAPI entrypoint. Wires up the DB, JWT auth, role-based row-level scoping,
and the CRUD + reporting endpoints.

Auth: POST /auth/login issues a bearer token; every data endpoint resolves the
principal via get_current_agent and enforces scoping (agent / manager / admin).
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, UploadFile, File, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.exceptions import HTTPException as StarletteHTTPException
import jwt
from sqlalchemy import create_engine, select, or_, func, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker, aliased

from app.models.models import (
    Base, Agent, Client, Product, Transaction, TxnStatus, Role, ProductType,
    CommissionEntry, DealType, Case, PipelineStage, CaseOutcome, Title,
    TitleTarget, TrainingMaterial, TrainingFile, TrainingCategory, OverrideRule,
    ProductRate, now_utc,
)
from app.schemas import schemas
from app.security import (
    verify_password, create_access_token, decode_token, hash_password,
    create_reset_token, verify_reset_token,
)
from app.services import (
    commission_engine, reports, agent_service, scoping,
    periods, payouts, exports, audit, mailer,
)
from app.services.sanitize import sanitize_html

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agency.db")
# Base URL of the web app, used to build password-reset links in emails.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
# Where to send login-notification emails (defaults to the bootstrap admin).
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base.metadata.create_all(engine)


def _ensure_columns() -> None:
    """Add columns introduced after the initial schema to existing tables —
    create_all only creates missing tables, it never alters existing ones. Runs
    on every startup and is idempotent (only adds what's missing). Works on both
    SQLite (dev) and Postgres (prod)."""
    from sqlalchemy import inspect as _sa_inspect, text
    insp = _sa_inspect(engine)

    def cols(table: str) -> set[str]:
        try:
            return {c["name"] for c in insp.get_columns(table)}
        except Exception:
            return set()

    ddl: list[str] = []
    if "last_login_at" not in cols("agents"):
        ddl.append("ALTER TABLE agents ADD COLUMN last_login_at TIMESTAMP")
    # Tenant company column on the agent + the four global config/aggregate tables.
    agents_got_company = "company" not in cols("agents")
    for table in ("agents", "override_rules", "title_targets", "payouts", "periods"):
        if "company" not in cols(table):
            ddl.append(f"ALTER TABLE {table} ADD COLUMN company VARCHAR(20) DEFAULT 'heritree'")
    # Rate-lock snapshot columns on transactions (JSON is native on Postgres, TEXT
    # on SQLite where SQLAlchemy's JSON type serialises to text).
    json_type = "JSON" if engine.dialect.name == "postgresql" else "TEXT"
    if "locked_base_rate" not in cols("transactions"):
        ddl.append("ALTER TABLE transactions ADD COLUMN locked_base_rate NUMERIC(6,4)")
    if "locked_year_commissions" not in cols("transactions"):
        ddl.append(f"ALTER TABLE transactions ADD COLUMN locked_year_commissions {json_type}")
    # Training: per-company visibility + per-file metadata (multi-file support).
    if "companies" not in cols("training_materials"):
        ddl.append(f"ALTER TABLE training_materials ADD COLUMN companies {json_type}")
    if "inline_preview" not in cols("training_materials"):
        # Postgres rejects the integer literal 0 for a boolean default; SQLite is
        # fine with either. Use the SQL boolean literal.
        bool_false = "false" if engine.dialect.name == "postgresql" else "0"
        ddl.append(f"ALTER TABLE training_materials ADD COLUMN inline_preview BOOLEAN DEFAULT {bool_false}")
    tf_cols = cols("training_files")
    if tf_cols and "file_name" not in tf_cols:
        ddl.append("ALTER TABLE training_files ADD COLUMN file_name VARCHAR(255) DEFAULT 'file'")
        ddl.append("ALTER TABLE training_files ADD COLUMN content_type VARCHAR(120) DEFAULT 'application/octet-stream'")
        ddl.append("ALTER TABLE training_files ADD COLUMN file_size INTEGER DEFAULT 0")
        ddl.append("ALTER TABLE training_files ADD COLUMN created_at TIMESTAMP")
    if tf_cols and "preview_content_type" not in tf_cols:
        blob_type = "BYTEA" if engine.dialect.name == "postgresql" else "BLOB"
        ddl.append("ALTER TABLE training_files ADD COLUMN preview_content_type VARCHAR(120)")
        ddl.append(f"ALTER TABLE training_files ADD COLUMN preview_data {blob_type}")
    if ddl:
        with engine.begin() as conn:
            for stmt in ddl:
                conn.execute(text(stmt))
    # Backfill each existing agent's company from its code prefix.
    if agents_got_company:
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE agents SET company = CASE WHEN lower(code) LIKE 'cpm%' "
                "THEN 'cpm' ELSE 'heritree' END"
            ))
    _drop_legacy_title_unique(insp)
    _migrate_training_files(insp)


def _migrate_training_files(insp) -> None:
    """Backfill each training file's name/type/size from its parent material's
    (legacy single-file) columns, and drop the UNIQUE(material_id) constraint so a
    material can hold many files."""
    from sqlalchemy import text
    tf_cols = {c["name"] for c in insp.get_columns("training_files")} if "training_files" in insp.get_table_names() else set()
    if not tf_cols:
        return
    with engine.begin() as conn:
        # Backfill file metadata from the parent material for pre-multi-file rows.
        conn.execute(text(
            "UPDATE training_files SET file_name = COALESCE((SELECT m.file_name "
            "FROM training_materials m WHERE m.id = training_files.material_id), 'file') "
            "WHERE file_name IS NULL OR file_name = 'file'"))
        conn.execute(text(
            "UPDATE training_files SET content_type = COALESCE((SELECT m.content_type "
            "FROM training_materials m WHERE m.id = training_files.material_id), 'application/octet-stream') "
            "WHERE content_type IS NULL OR content_type = 'application/octet-stream'"))
        conn.execute(text(
            "UPDATE training_files SET file_size = COALESCE((SELECT m.file_size "
            "FROM training_materials m WHERE m.id = training_files.material_id), 0) "
            "WHERE file_size IS NULL OR file_size = 0"))
    if engine.dialect.name == "sqlite":
        # SQLite can't drop an inline UNIQUE (auto-index) — rebuild the table if the
        # legacy unique index over [material_id] is present.
        with engine.begin() as conn:
            legacy = False
            for row in conn.execute(text("PRAGMA index_list(training_files)")):
                if row[2] and [r[2] for r in conn.execute(text(f"PRAGMA index_info('{row[1]}')"))] == ["material_id"]:
                    legacy = True
                    break
            if not legacy:
                return
            conn.execute(text("ALTER TABLE training_files RENAME TO _training_files_old"))
        TrainingFile.__table__.create(engine)
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO training_files (id, material_id, file_name, content_type, file_size, created_at, data) "
                "SELECT id, material_id, file_name, content_type, file_size, created_at, data FROM _training_files_old"))
            conn.execute(text("DROP TABLE _training_files_old"))
        return
    # Postgres: drop the unique constraint / index on material_id if present.
    try:
        uniques = [u for u in insp.get_unique_constraints("training_files")
                   if u.get("column_names") == ["material_id"] and u.get("name")]
        uniques += [i for i in insp.get_indexes("training_files")
                    if i.get("unique") and i.get("column_names") == ["material_id"] and i.get("name")]
    except Exception:
        return
    with engine.begin() as conn:
        for u in uniques:
            # The legacy uniqueness may be backed by a UNIQUE CONSTRAINT or a
            # standalone UNIQUE INDEX (the auto index `ix_training_files_material_id`
            # from the old column's index=True, unique=True). `DROP CONSTRAINT IF
            # EXISTS` is a silent no-op for an index name (it does NOT raise), so we
            # can't rely on an exception to fall through — run both, each guarded by
            # IF EXISTS, so whichever kind it is gets removed.
            name = u["name"]
            conn.execute(text(f'ALTER TABLE training_files DROP CONSTRAINT IF EXISTS "{name}"'))
            conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
        # The model declares a NON-unique index on material_id (many files per
        # material); recreate it now that the legacy unique one is gone. Idempotent.
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_training_files_material_id "
            "ON training_files (material_id)"))


def _drop_legacy_title_unique(insp) -> None:
    """The original title_targets had UNIQUE(title); per-company targets need that
    gone (uniqueness is now (company, title))."""
    from sqlalchemy import text
    if engine.dialect.name == "sqlite":
        # SQLAlchemy hides SQLite auto-indexes, so probe PRAGMA directly for a
        # unique index over exactly [title] (the legacy one, not the new composite).
        with engine.begin() as conn:
            legacy = False
            for row in conn.execute(text("PRAGMA index_list(title_targets)")):
                name, unique = row[1], row[2]
                if not unique:
                    continue
                icols = [r[2] for r in conn.execute(text(f"PRAGMA index_info('{name}')"))]
                if icols == ["title"]:
                    legacy = True
                    break
            if not legacy:
                return
            # SQLite can't drop an inline UNIQUE (auto-index) — rebuild the table.
            conn.execute(text("ALTER TABLE title_targets RENAME TO _title_targets_old"))
        TitleTarget.__table__.create(engine)
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO title_targets (id, company, title, target_afyp) "
                "SELECT id, COALESCE(company,'heritree'), title, target_afyp FROM _title_targets_old"
            ))
            conn.execute(text("DROP TABLE _title_targets_old"))
        return
    # Postgres: drop the named single-column unique constraint/index if present.
    try:
        legacy = [u for u in insp.get_unique_constraints("title_targets")
                  if u.get("column_names") == ["title"] and u.get("name")]
        legacy += [i for i in insp.get_indexes("title_targets")
                   if i.get("unique") and i.get("column_names") == ["title"] and i.get("name")]
    except Exception:
        return
    with engine.begin() as conn:
        for u in legacy:
            name = u["name"]
            try:
                conn.execute(text(f'ALTER TABLE title_targets DROP CONSTRAINT IF EXISTS "{name}"'))
            except Exception:
                try:
                    conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
                except Exception:
                    pass


_ensure_columns()


def _seed_cpm_override_rules() -> None:
    """So CPM 代理 commissions compute out-of-the-box, copy Heritree's current
    override-rule set into CPM once, when CPM has none yet."""
    with SessionLocal() as db:
        has_cpm = db.execute(select(OverrideRule).where(OverrideRule.company == "cpm")).first()
        if has_cpm:
            return
        heritree = db.execute(select(OverrideRule).where(OverrideRule.company == "heritree")).scalars().all()
        for r in heritree:
            db.add(OverrideRule(company="cpm", product_type=r.product_type,
                                level_gap=r.level_gap, override_rate=r.override_rate,
                                valid_from=r.valid_from, valid_to=r.valid_to))
        if heritree:
            db.commit()


_seed_cpm_override_rules()


def _seed_product_rates() -> None:
    """Ensure each shared product has a per-company base-rate row for both
    companies, copied from the product's own value. Idempotent; backfills
    products created before per-company rates existed."""
    with SessionLocal() as db:
        products = db.execute(select(Product)).scalars().all()
        made = False
        for p in products:
            for company in ("heritree", "cpm"):
                has = db.execute(select(ProductRate).where(
                    ProductRate.product_id == p.id, ProductRate.company == company)).first()
                if not has:
                    db.add(ProductRate(product_id=p.id, company=company,
                                       base_commission_rate=p.base_commission_rate,
                                       year_commissions=p.year_commissions))
                    made = True
        if made:
            db.commit()


_seed_product_rates()


def _seed_training_categories() -> None:
    """Bootstrap the maintained training types on an empty table so the material
    form always has options; admins can then add/rename/remove them."""
    defaults = ["新人入職", "產品知識", "銷售技巧", "合規法規", "系統操作"]
    with SessionLocal() as db:
        if db.execute(select(TrainingCategory)).first() is None:
            for i, name in enumerate(defaults):
                db.add(TrainingCategory(name=name, sort_order=i))
            db.commit()


_seed_training_categories()

app = FastAPI(title="FOA 家辦代理系統", version="1.0.0")

# CORS_ORIGINS: comma-separated list of allowed web origins, or "*" (dev default).
# In production set it to the web app's origin, e.g. https://app.yourdomain.com.
_cors = os.getenv("CORS_ORIGINS", "*").strip()
_allow_origins = ["*"] if _cors == "*" else [o.strip() for o in _cors.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=_allow_origins, allow_methods=["*"], allow_headers=["*"],
    # Expose the machine-readable error code so the browser client can localize.
    expose_headers=["X-Error-Code"],
)

bearer_scheme = HTTPBearer(auto_error=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Exception mapping -------------------------------------------------------
# Stable, machine-readable error codes returned via the X-Error-Code response
# header so the browser client can localize messages. The `detail` body text is
# left unchanged (English) to preserve the existing API/test contract.
_DETAIL_TO_CODE = {
    "invalid or expired token": "invalid_token",
    "unknown or inactive principal": "unknown_principal",
    "admin role required": "admin_required",
    "invalid credentials": "invalid_credentials",
    "account disabled": "account_disabled",
    "agent not found": "agent_not_found",
    "email already in use": "email_in_use",
    "admins do not own clients": "forbidden",
    "you may only create clients you own": "forbidden",
    "you may only list your own clients": "forbidden",
    "client not found": "client_not_found",
    "product not found": "product_not_found",
    "product or agent not found": "not_found",
    "cannot delete a product with transactions; deactivate it instead": "product_has_transactions",
    "override rule not found": "rule_not_found",
    "transaction not found": "transaction_not_found",
    "cannot delete a transaction with paid commission; cancel it instead": "transaction_has_paid",
}


def err(status: int, code: str, message: str) -> HTTPException:
    """HTTPException that carries a stable machine-readable X-Error-Code header."""
    return HTTPException(status, message, headers={"X-Error-Code": code})


@app.exception_handler(StarletteHTTPException)
def _http_exception_handler(request, exc: StarletteHTTPException):
    headers = dict(exc.headers or {})
    code = _DETAIL_TO_CODE.get(str(exc.detail))
    if code:
        headers["X-Error-Code"] = code
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)


@app.exception_handler(PermissionError)
def _permission_handler(request, exc: PermissionError):
    return JSONResponse(status_code=403, content={"detail": str(exc)},
                        headers={"X-Error-Code": "forbidden"})


@app.exception_handler(agent_service.ValidationError)
def _validation_handler(request, exc: agent_service.ValidationError):
    return JSONResponse(status_code=422, content={"detail": str(exc)},
                        headers={"X-Error-Code": "validation"})


@app.exception_handler(periods.PeriodLockedError)
def _period_locked_handler(request, exc: periods.PeriodLockedError):
    return JSONResponse(status_code=409, content={"detail": str(exc)},
                        headers={"X-Error-Code": "period_locked"})


@app.exception_handler(ValueError)
def _value_error_handler(request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)},
                        headers={"X-Error-Code": "bad_request"})


# --- Auth --------------------------------------------------------------------
def get_current_agent(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Agent:
    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token")
    agent_id = payload.get("sub")
    agent = db.get(Agent, int(agent_id)) if agent_id is not None else None
    if agent is None or not agent.is_active:
        raise HTTPException(401, "unknown or inactive principal")
    return agent


def require_admin(current: Agent = Depends(get_current_agent)) -> Agent:
    if current.role != Role.ADMIN:
        raise HTTPException(403, "admin role required")
    return current


def _guard_company(db: Session, current: Agent, agent_id: int | None) -> None:
    """For a company-scoped admin acting on a specific agent's data: block the op
    if that agent is in a different company. A no-op for same-company / self."""
    if agent_id is None:
        return
    a = db.get(Agent, agent_id)
    if a is not None and a.company != current.company:
        raise err(403, "forbidden", "cross-company access is not allowed")


@app.post("/auth/login", response_model=schemas.TokenOut)
def login(payload: schemas.LoginIn, background: BackgroundTasks,
          db: Session = Depends(get_db)):
    agent = db.execute(
        select(Agent).where(
            or_(Agent.code == payload.username, Agent.email == payload.username)
        )
    ).scalars().first()
    if agent is None or not verify_password(payload.password, agent.password_hash):
        raise HTTPException(401, "invalid credentials")
    if not agent.is_active:
        raise HTTPException(403, "account disabled")
    token = create_access_token(agent.id, {"role": agent.role.value})
    agent.last_login_at = now_utc()
    db.commit()
    # Notify the admin that a user signed in (best-effort, off the request path).
    if ADMIN_EMAIL:
        when = now_utc().strftime("%Y-%m-%d %H:%M:%S")
        background.add_task(mailer.send_login_alert, ADMIN_EMAIL,
                            agent.name, agent.code, agent.role.value, when)
    return schemas.TokenOut(access_token=token)


@app.get("/auth/me", response_model=schemas.MeOut)
def me(current: Agent = Depends(get_current_agent)):
    return current


@app.post("/auth/change-password", status_code=204)
def change_password(payload: schemas.ChangePasswordIn,
                    db: Session = Depends(get_db),
                    current: Agent = Depends(get_current_agent)):
    """The logged-in user changes their own password (needs the current one)."""
    if not verify_password(payload.current_password, current.password_hash):
        raise err(400, "wrong_current_password", "current password is incorrect")
    current.password_hash = hash_password(payload.new_password)
    audit.record(db, current.id, "change-password", "agent", current.id)
    db.commit()
    return Response(status_code=204)


@app.post("/auth/forgot-password", status_code=202)
def forgot_password(payload: schemas.ForgotPasswordIn, db: Session = Depends(get_db)):
    """Email a password-reset link. Always returns 202 (never reveals whether the
    email exists) to avoid account enumeration."""
    agent = db.execute(select(Agent).where(Agent.email == payload.email)).scalars().first()
    if agent is not None and agent.is_active:
        token = create_reset_token(agent.id, agent.password_hash)
        reset_url = f"{FRONTEND_URL.rstrip('/')}/#/reset-password/{token}"
        try:
            mailer.send_password_reset(agent.email, agent.name, reset_url)
        except Exception:  # noqa: BLE001 — don't leak delivery failures to the caller
            pass
    return Response(status_code=202)


@app.post("/auth/reset-password", status_code=204)
def reset_password(payload: schemas.ResetPasswordIn, db: Session = Depends(get_db)):
    """Set a new password using a token from the reset email."""
    try:
        claims = decode_token(payload.token)
    except jwt.PyJWTError:
        raise err(400, "invalid_reset_token", "reset link is invalid or has expired")
    agent = db.get(Agent, int(claims.get("sub"))) if claims.get("sub") else None
    if agent is None or not verify_reset_token(payload.token, agent.password_hash):
        raise err(400, "invalid_reset_token", "reset link is invalid or has expired")
    agent.password_hash = hash_password(payload.new_password)
    audit.record(db, agent.id, "reset-password", "agent", agent.id)
    db.commit()
    return Response(status_code=204)


# --- Agents ------------------------------------------------------------------
@app.post("/agents", response_model=schemas.AgentOut)
def create_agent(payload: schemas.AgentIn, db: Session = Depends(get_db),
                 current: Agent = Depends(require_admin)):
    # A company-scoped admin may only create agents in their own company: the code
    # prefix must resolve to the admin's company, and the upline must match too.
    company = scoping.company_for_code(payload.code)
    if company != current.company:
        raise err(400, "wrong_company_prefix",
                  "agent code prefix must match your company")
    agent_service.validate_agent(db, payload.level, payload.upline_id, company=company)
    # Friendly duplicate checks (code / email are unique) so the client gets a
    # clear 409 instead of an opaque 500 — a 500 skips CORS headers and surfaces
    # in the browser as "Failed to fetch".
    if db.execute(select(Agent).where(Agent.code == payload.code)).scalars().first():
        raise err(409, "code_taken", "agent code already in use")
    if payload.email and db.execute(
        select(Agent).where(Agent.email == payload.email)
    ).scalars().first():
        raise err(409, "email_in_use", "email already in use")
    data = payload.model_dump(exclude={"password"})
    agent = Agent(**data, company=company)
    if payload.password:
        agent.password_hash = hash_password(payload.password)
    try:
        db.add(agent); db.commit(); db.refresh(agent)
    except IntegrityError:
        db.rollback()
        raise err(409, "duplicate", "agent violates a uniqueness constraint")
    return agent


@app.get("/agents", response_model=list[schemas.AgentOut])
def list_agents(db: Session = Depends(get_db),
                current: Agent = Depends(get_current_agent)):
    ids = scoping.visible_agent_ids(db, current)
    return db.execute(select(Agent).where(Agent.id.in_(ids))).scalars().all()


@app.get("/agents/directory")
def agents_directory(db: Session = Depends(get_db),
                     current: Agent = Depends(get_current_agent)):
    """Minimal roster of active, non-admin agents for assignment selectors (e.g.
    picking the Lead / SDR / Closer on a case). Any authenticated user may read
    it — GET /agents is scoped to self for a plain agent, so it can't populate
    cross-agent pickers."""
    rows = db.execute(
        select(Agent).where(Agent.is_active.is_(True), Agent.role != Role.ADMIN,
                            Agent.company == current.company)
        .order_by(Agent.level, Agent.code)
    ).scalars().all()
    return [{"id": a.id, "code": a.code, "name": a.name,
             "level": a.level, "unit_code": a.unit_code} for a in rows]


@app.patch("/agents/{agent_id}", response_model=schemas.AgentOut)
def update_agent(agent_id: int, payload: schemas.AgentUpdate,
                 db: Session = Depends(get_db),
                 current: Agent = Depends(require_admin)):
    """Admin assigns a title / role / active flag to an existing agent."""
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    if agent.company != current.company:
        raise err(403, "forbidden", "cross-company access is not allowed")
    before = {"name": agent.name, "email": agent.email,
              "title": agent.title.value if agent.title else None,
              "role": agent.role.value, "is_active": agent.is_active}
    data = payload.model_dump(exclude_unset=True)
    if "email" in data and data["email"] != agent.email:
        clash = db.execute(
            select(Agent).where(Agent.email == data["email"], Agent.id != agent_id)
        ).scalars().first()
        if clash is not None:
            raise err(409, "email_in_use", "email already in use")
    # Admin manual password reset: hash it, and never echo the raw value.
    new_password = data.pop("password", None)
    if new_password:
        agent.password_hash = hash_password(new_password)
    for k, v in data.items():
        setattr(agent, k, v)
    db.flush()
    audit.record(db, current.id, "update", "agent", agent.id,
                 before=before, after=data)
    db.commit(); db.refresh(agent)
    return agent


@app.get("/agents/{agent_id}/downlines", response_model=list[schemas.AgentOut])
def downlines(agent_id: int, db: Session = Depends(get_db),
              current: Agent = Depends(get_current_agent)):
    scoping.assert_visible(db, current, agent_id)
    return db.execute(select(Agent).where(Agent.upline_id == agent_id)).scalars().all()


# --- Clients (owner-only) ----------------------------------------------------
# Client details and their transactions are strictly owner-only. Admins are not
# sellers and cannot own or read clients.
def _next_client_ref(db: Session) -> str:
    """Auto client code: C<YY><NNN> — 'C' + 2-digit year + a per-year, zero-padded
    (min 3-digit) sequence, e.g. C26001 for the first 2026 client."""
    prefix = f"C{date.today().year % 100:02d}"
    existing = db.execute(
        select(Client.ref).where(Client.ref.like(prefix + "%"))
    ).scalars().all()
    max_seq = 0
    for r in existing:
        tail = (r or "")[len(prefix):]
        if tail.isdigit():
            max_seq = max(max_seq, int(tail))
    return f"{prefix}{max_seq + 1:03d}"


@app.get("/clients/next-ref", response_model=schemas.NextRefOut)
def next_client_ref(db: Session = Depends(get_db),
                    current: Agent = Depends(get_current_agent)):
    """Preview the next auto-generated client code (C<YY><NNN>)."""
    return schemas.NextRefOut(ref=_next_client_ref(db))


@app.post("/clients", response_model=schemas.ClientOut)
def create_client(payload: schemas.ClientIn, db: Session = Depends(get_db),
                  current: Agent = Depends(get_current_agent)):
    if scoping.is_admin(current):
        # Admins operate transactions on behalf of agents and may create a client
        # owned by any agent in their company (e.g. the Lead agent on a new deal).
        if db.get(Agent, payload.agent_id) is None:
            raise HTTPException(404, "agent not found")
        _guard_company(db, current, payload.agent_id)
    elif payload.agent_id != current.id:
        raise HTTPException(403, "you may only create clients you own")
    data = payload.model_dump()
    if not (data.get("ref") or "").strip():
        data["ref"] = _next_client_ref(db)   # auto-assign C<YY><NNN>
    client = Client(**data)
    db.add(client); db.commit(); db.refresh(client)
    return client


@app.get("/clients", response_model=list[schemas.ClientOut])
def list_clients(db: Session = Depends(get_db),
                 current: Agent = Depends(get_current_agent)):
    # Agents see their own clients; a company admin sees all clients in its company.
    q = select(Client)
    if scoping.is_admin(current):
        q = q.join(Agent, Client.agent_id == Agent.id).where(Agent.company == current.company)
    else:
        q = q.where(Client.agent_id == current.id)
    return db.execute(q).scalars().all()


@app.get("/clients/{client_id}", response_model=schemas.ClientOut)
def get_client(client_id: int, db: Session = Depends(get_db),
               current: Agent = Depends(get_current_agent)):
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(404, "client not found")
    scoping.assert_can_read_client(current, client)
    if scoping.is_admin(current):
        _guard_company(db, current, client.agent_id)
    return client


@app.patch("/clients/{client_id}", response_model=schemas.ClientOut)
def update_client(client_id: int, payload: schemas.ClientUpdate,
                  db: Session = Depends(get_db),
                  current: Agent = Depends(get_current_agent)):
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(404, "client not found")
    scoping.assert_owns_client(current, client)
    if scoping.is_admin(current):
        _guard_company(db, current, client.agent_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(client, k, v)
    db.commit(); db.refresh(client)
    return client


@app.get("/agents/{agent_id}/clients", response_model=list[schemas.ClientOut])
def agent_clients(agent_id: int, db: Session = Depends(get_db),
                  current: Agent = Depends(get_current_agent)):
    # An agent lists their own clients; an admin may list any same-company agent's.
    if not scoping.is_admin(current) and agent_id != current.id:
        raise HTTPException(403, "you may only list your own clients")
    _guard_company(db, current, agent_id)
    return db.execute(select(Client).where(Client.agent_id == agent_id)).scalars().all()


@app.get("/agents/{agent_id}/transactions")
def agent_transactions(agent_id: int, db: Session = Depends(get_db),
                       current: Agent = Depends(get_current_agent)):
    """An agent's own (closing) transactions, enriched with client/product names
    for a read-only review list (includes the locked commission rate). Own
    transactions, or any same-company agent's if admin."""
    scoping.assert_can_access_txn(current, agent_id)
    _guard_company(db, current, agent_id)
    rows = db.execute(
        select(Transaction, Client.name, Client.ref, Product.name, Product.type)
        .join(Client, Transaction.client_id == Client.id)
        .join(Product, Transaction.product_id == Product.id)
        .where(Transaction.agent_id == agent_id)
        .order_by(Transaction.trade_date.desc(), Transaction.id.desc())
    ).all()
    out = []
    for txn, cname, cref, pname, ptype in rows:
        out.append({
            "id": txn.id, "ref": txn.ref, "trade_date": txn.trade_date,
            "status": txn.status.value,
            "deal_type": (txn.deal_type.value if txn.deal_type else "agent"),
            "notional": txn.notional, "currency": txn.currency,
            "policy_no": txn.policy_no,
            "client_id": txn.client_id, "client_name": cname, "client_ref": cref,
            "product_id": txn.product_id, "product_name": pname,
            "product_type": ptype.value,
            "agent_id": txn.agent_id,
            "lead_agent_id": txn.lead_agent_id,
            "sales_dev_agent_id": txn.sales_dev_agent_id,
            "lead_pct": txn.lead_pct, "sales_dev_pct": txn.sales_dev_pct,
            "closing_pct": txn.closing_pct,
            "locked_base_rate": txn.locked_base_rate,
            "locked_year_commissions": txn.locked_year_commissions,
        })
    return out


# --- Products ----------------------------------------------------------------
def _encode_year_commissions(data: dict) -> None:
    """Store the Yr1..Yr10 schedule as exact decimal strings (JSON-safe)."""
    if data.get("year_commissions") is not None:
        data["year_commissions"] = [str(x) for x in data["year_commissions"]]


def _sync_insurance_base_rate(data: dict) -> None:
    """For insurance products the base (upfront) rate is the Yr1 commission."""
    yc = data.get("year_commissions")
    if yc:
        data["base_commission_rate"] = Decimal(str(yc[0]))


def _get_product_rate(db: Session, product_id: int, company: str) -> ProductRate | None:
    return db.execute(select(ProductRate).where(
        ProductRate.product_id == product_id, ProductRate.company == company)).scalars().first()


def _product_out(db: Session, product: Product, company: str) -> schemas.ProductOut:
    """Serialise a product with its base_commission_rate + year_commissions
    resolved to the caller's company (each company sets its own 基本比率)."""
    out = schemas.ProductOut.model_validate(product)
    pr = _get_product_rate(db, product.id, company)
    if pr is not None:
        out.base_commission_rate = pr.base_commission_rate
        out.year_commissions = [str(x) for x in pr.year_commissions] if pr.year_commissions else None
    return out


@app.post("/products", response_model=schemas.ProductOut)
def create_product(payload: schemas.ProductIn, db: Session = Depends(get_db),
                   current: Agent = Depends(require_admin)):
    data = payload.model_dump()
    _encode_year_commissions(data)
    if data.get("type") == ProductType.INSURANCE.value:
        _sync_insurance_base_rate(data)
    product = Product(**data)
    db.add(product); db.flush()
    # Seed both companies' base rate from the provided values; each may diverge later.
    for company in ("heritree", "cpm"):
        db.add(ProductRate(product_id=product.id, company=company,
                           base_commission_rate=product.base_commission_rate,
                           year_commissions=product.year_commissions))
    audit.record(db, current.id, "create", "product", product.id, after=data)
    db.commit(); db.refresh(product)
    return _product_out(db, product, current.company)


@app.patch("/products/{product_id}", response_model=schemas.ProductOut)
def update_product(product_id: int, payload: schemas.ProductUpdate,
                   db: Session = Depends(get_db),
                   current: Agent = Depends(require_admin)):
    """Admins maintain product details. The commission rate (base_commission_rate
    and, for insurance, the Yr1..Yr10 schedule) is per-company — it edits the
    caller's company's ProductRate; all other fields are shared."""
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "product not found")
    data = payload.model_dump(exclude_unset=True)
    _encode_year_commissions(data)
    # Route the per-company rate config out of the shared product update.
    rate_base = data.pop("base_commission_rate", None)
    rate_years = data.pop("year_commissions", None)
    if product.type == ProductType.INSURANCE and rate_years:
        rate_base = Decimal(str(rate_years[0]))
    if rate_base is not None or rate_years is not None:
        pr = _get_product_rate(db, product.id, current.company)
        if pr is None:
            pr = ProductRate(product_id=product.id, company=current.company,
                             base_commission_rate=product.base_commission_rate,
                             year_commissions=product.year_commissions)
            db.add(pr)
        if rate_base is not None:
            pr.base_commission_rate = rate_base
        if rate_years is not None:
            pr.year_commissions = rate_years
    for k, v in data.items():
        setattr(product, k, v)
    db.flush()
    audit.record(db, current.id, "update", "product", product.id, after=data)
    db.commit(); db.refresh(product)
    return _product_out(db, product, current.company)


@app.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db),
                   current: Agent = Depends(require_admin)):
    """Delete a product. Refused (409) if any transactions reference it."""
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "product not found")
    used = db.execute(
        select(func.count()).select_from(Transaction)
        .where(Transaction.product_id == product_id)
    ).scalar()
    if used:
        raise HTTPException(409, "cannot delete a product with transactions; deactivate it instead")
    audit.record(db, current.id, "delete", "product", product_id,
                 before={"code": product.code, "name": product.name})
    # Remove the per-company rate rows too — they have no FK cascade, so a bare
    # product delete would orphan them (and a later product reusing this id would
    # collide / inherit stale rates).
    db.execute(delete(ProductRate).where(ProductRate.product_id == product_id))
    db.delete(product); db.commit()
    return {"deleted": product_id}


@app.get("/products", response_model=list[schemas.ProductOut])
def list_products(db: Session = Depends(get_db),
                  current: Agent = Depends(get_current_agent)):
    products = db.execute(select(Product)).scalars().all()
    return [_product_out(db, p, current.company) for p in products]


# --- Override rules (admin) --------------------------------------------------
@app.get("/override-rules", response_model=list[schemas.OverrideRuleOut])
def list_override_rules(db: Session = Depends(get_db),
                        current: Agent = Depends(get_current_agent)):
    return db.execute(
        select(OverrideRule).where(OverrideRule.company == current.company)
    ).scalars().all()


@app.post("/override-rules", response_model=schemas.OverrideRuleOut)
def create_override_rule(payload: schemas.OverrideRuleIn, db: Session = Depends(get_db),
                         current: Agent = Depends(require_admin)):
    data = payload.model_dump()
    if data.get("valid_from") is None:
        data.pop("valid_from", None)  # let the column default apply
    rule = OverrideRule(**data, company=current.company)
    db.add(rule); db.flush()
    audit.record(db, current.id, "create", "override_rule", rule.id,
                 after=payload.model_dump())
    db.commit(); db.refresh(rule)
    return rule


@app.patch("/override-rules/{rule_id}", response_model=schemas.OverrideRuleOut)
def update_override_rule(rule_id: int, payload: schemas.OverrideRuleUpdate,
                         db: Session = Depends(get_db),
                         current: Agent = Depends(require_admin)):
    rule = db.get(OverrideRule, rule_id)
    if rule is None or rule.company != current.company:
        raise HTTPException(404, "override rule not found")
    data = payload.model_dump(exclude_unset=True)
    if "valid_from" in data and data["valid_from"] is None:
        data.pop("valid_from")  # never null a non-nullable column
    for k, v in data.items():
        setattr(rule, k, v)
    db.flush()
    audit.record(db, current.id, "update", "override_rule", rule.id, after=data)
    db.commit(); db.refresh(rule)
    return rule


@app.delete("/override-rules/{rule_id}")
def delete_override_rule(rule_id: int, db: Session = Depends(get_db),
                         current: Agent = Depends(require_admin)):
    rule = db.get(OverrideRule, rule_id)
    if rule is None or rule.company != current.company:
        raise HTTPException(404, "override rule not found")
    audit.record(db, current.id, "delete", "override_rule", rule_id,
                 before={"product_type": rule.product_type.value,
                         "level_gap": rule.level_gap, "override_rate": rule.override_rate})
    db.delete(rule); db.commit()
    return {"deleted": rule_id}


# --- Transactions ------------------------------------------------------------
def _next_ref(db: Session, trade_date: date) -> str:
    """Auto transaction code: YYYY-MM-<case no> (per year-month, zero-padded)."""
    prefix = f"{trade_date.year:04d}-{trade_date.month:02d}-"
    existing = db.execute(
        select(Transaction.ref).where(Transaction.ref.like(prefix + "%"))
    ).scalars().all()
    max_seq = 0
    for r in existing:
        try:
            max_seq = max(max_seq, int(r.rsplit("-", 1)[1]))
        except (ValueError, IndexError):
            continue
    return f"{prefix}{max_seq + 1:03d}"


@app.get("/transactions/next-ref", response_model=schemas.NextRefOut)
def next_transaction_ref(period: str | None = None, db: Session = Depends(get_db),
                         current: Agent = Depends(get_current_agent)):
    """Preview the next auto-generated transaction code for a period (default: now)."""
    if period:
        year, month = periods.parse_ym(period)
        d = date(year, month, 1)
    else:
        d = date.today()
    return schemas.NextRefOut(ref=_next_ref(db, d))


def _agents_by_id(db: Session, company: str) -> dict[int, tuple[str, str]]:
    """{agent_id: (name, code)} for one company — used to resolve the Lead/SDR/
    Closing role agents on a transaction row."""
    return {r[0]: (r[1], r[2]) for r in db.execute(
        select(Agent.id, Agent.name, Agent.code).where(Agent.company == company)).all()}


def _role_fields(txn: Transaction, by_id: dict[int, tuple[str, str]]) -> dict:
    """Lead / SDR / Closing agent names + codes + split percentages. Lead and
    sales-dev fall back to the closing agent when unset (mirrors the engine)."""
    closer = by_id.get(txn.agent_id, ("", ""))
    lead = by_id.get(txn.lead_agent_id or txn.agent_id, closer)
    sdr = by_id.get(txn.sales_dev_agent_id or txn.agent_id, closer)
    return {
        "lead_name": lead[0], "lead_code": lead[1], "lead_pct": txn.lead_pct,
        "sdr_name": sdr[0], "sdr_code": sdr[1], "sales_dev_pct": txn.sales_dev_pct,
        "closing_name": closer[0], "closing_code": closer[1], "closing_pct": txn.closing_pct,
    }


@app.get("/transactions/mine")
def review_transactions(status: str | None = None, db: Session = Depends(get_db),
                        current: Agent = Depends(get_current_agent)):
    """Read-only review list scoped to the caller's visible line: an agent sees
    every deal they take part in (as lead, sales-dev OR closer); a manager sees
    the same across their whole subtree; an admin across the company. Enriched
    with client/product/agent (closer) names + the locked rate."""
    ids = scoping.visible_agent_ids(db, current)
    if not ids:
        return []
    stmt = (
        select(Transaction, Client.name, Client.ref, Product.name, Product.type,
               Agent.name, Agent.code)
        .join(Client, Transaction.client_id == Client.id)
        .join(Product, Transaction.product_id == Product.id)
        .join(Agent, Transaction.agent_id == Agent.id)  # closer, for the Agent column
        .where(or_(Transaction.agent_id.in_(ids),
                   Transaction.lead_agent_id.in_(ids),
                   Transaction.sales_dev_agent_id.in_(ids)))
        .order_by(Transaction.trade_date.desc(), Transaction.id.desc())
    )
    if status:
        try:
            stmt = stmt.where(Transaction.status == TxnStatus(status))
        except ValueError:
            raise err(422, "validation", f"invalid status: {status}")
    by_id = _agents_by_id(db, current.company)
    out = []
    for txn, cname, cref, pname, ptype, aname, acode in db.execute(stmt).all():
        out.append({
            "id": txn.id, "ref": txn.ref, "trade_date": txn.trade_date,
            "status": txn.status.value,
            "deal_type": (txn.deal_type.value if txn.deal_type else "agent"),
            "notional": txn.notional, "currency": txn.currency,
            "policy_no": txn.policy_no,
            "client_id": txn.client_id, "client_name": cname, "client_ref": cref,
            "product_id": txn.product_id, "product_name": pname,
            "product_type": ptype.value,
            "agent_id": txn.agent_id, "agent_name": aname, "agent_code": acode,
            "locked_base_rate": txn.locked_base_rate,
            "locked_year_commissions": txn.locked_year_commissions,
            **_role_fields(txn, by_id),
        })
    return out


@app.get("/transactions")
def list_transactions(status: str | None = None, agent_id: int | None = None,
                      q: str | None = None, db: Session = Depends(get_db),
                      current: Agent = Depends(require_admin)):
    """Admin transaction-maintenance list, enriched with client/product/agent names.

    Optional filters: `status` (pending/approved/cancelled), `agent_id`, and a
    free-text `q` matched against ref, client, product, policy no. and agent.
    """
    stmt = (
        select(Transaction, Client.name, Client.ref, Product.name, Product.type,
               Agent.name, Agent.code, Product.commission_schedule)
        .join(Client, Transaction.client_id == Client.id)
        .join(Product, Transaction.product_id == Product.id)
        .join(Agent, Transaction.agent_id == Agent.id)
        .where(Agent.company == current.company)   # company-scoped admin
        .order_by(Transaction.trade_date.desc(), Transaction.id.desc())
    )
    if status:
        try:
            stmt = stmt.where(Transaction.status == TxnStatus(status))
        except ValueError:
            raise err(422, "validation", f"invalid status: {status}")
    if agent_id:
        stmt = stmt.where(Transaction.agent_id == agent_id)
    needle = (q or "").strip().lower()
    by_id = _agents_by_id(db, current.company)
    out = []
    for txn, cname, cref, pname, ptype, aname, acode, psched in db.execute(stmt).all():
        if needle:
            hay = " ".join(str(x or "") for x in
                           (txn.ref, cname, pname, txn.policy_no, aname, acode)).lower()
            if needle not in hay:
                continue
        out.append({
            "id": txn.id, "ref": txn.ref, "trade_date": txn.trade_date,
            "status": txn.status.value,
            "deal_type": (txn.deal_type.value if txn.deal_type else "agent"),
            "direct_overrides": txn.direct_overrides,
            "notional": txn.notional, "currency": txn.currency,
            "policy_no": txn.policy_no,
            "client_id": txn.client_id, "client_name": cname, "client_ref": cref,
            "product_id": txn.product_id, "product_name": pname,
            "product_type": ptype.value,
            "agent_id": txn.agent_id, "agent_name": aname, "agent_code": acode,
            "lead_agent_id": txn.lead_agent_id,
            "sales_dev_agent_id": txn.sales_dev_agent_id,
            "commission_schedule": (psched.value if psched else "upfront"),
            "locked_base_rate": txn.locked_base_rate,
            "locked_year_commissions": txn.locked_year_commissions,
            **_role_fields(txn, by_id),
        })
    return out


# Adding, editing and deleting transactions is admin-only (agents are view-only).
@app.post("/transactions", response_model=schemas.TransactionOut)
def create_transaction(payload: schemas.TransactionIn, adjust: bool = False,
                       db: Session = Depends(get_db),
                       current: Agent = Depends(require_admin)):
    client = db.get(Client, payload.client_id)
    if client is None:
        raise HTTPException(404, "client not found")
    _guard_company(db, current, client.agent_id)
    product = db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(404, "product not found")
    for aid in (payload.agent_id, payload.lead_agent_id, payload.sales_dev_agent_id):
        if aid is not None and db.get(Agent, aid) is None:
            raise HTTPException(404, "agent not found")
        _guard_company(db, current, aid)   # all role agents must be same company

    data = payload.model_dump()
    # Normalise deal type + override levels (JSON-serialisable). Manual override
    # levels are honoured for both deal types; 直客 additionally requires each
    # override agent to be 直客-eligible. A 代理 deal with no manual levels stores
    # None and lets the engine derive overrides from the hierarchy.
    data["deal_type"] = DealType(data.get("deal_type") or "agent")
    overrides = data.pop("direct_overrides", None)
    norm = []
    for row in (overrides or []):
        ag = db.get(Agent, row["agent_id"])
        if ag is None:
            raise HTTPException(404, "agent not found")
        _guard_company(db, current, row["agent_id"])
        if data["deal_type"] == DealType.DIRECT_CLIENT and not ag.direct_client:
            raise err(400, "not_direct_client", "selected agent is not 直客-eligible")
        norm.append({"agent_id": row["agent_id"], "pct": float(row["pct"])})
    data["direct_overrides"] = norm or None

    trade_date = data.get("trade_date") or date.today()
    # Admin may route a sale dated into a locked period to the next open period.
    data["trade_date"] = periods.assert_open_for_trade(
        db, trade_date, allow_adjust=adjust, company=current.company)

    # Auto-generate the transaction code when not supplied.
    if not data.get("ref"):
        data["ref"] = _next_ref(db, data["trade_date"])

    txn = Transaction(**data)
    db.add(txn); db.flush()
    # Lock the effective rate at creation so a later product-rate edit does not move
    # this booked deal. Per-year trail (insurance) snapshots the whole Yr1..YrN
    # schedule; everything else snapshots the flat base rate.
    closer = db.get(Agent, txn.agent_id)
    company = closer.company if closer else current.company
    year_rates = commission_engine.year_rates_for(db, product, company)
    if year_rates:
        txn.locked_year_commissions = [str(x) for x in year_rates]
        txn.locked_base_rate = year_rates[0]
    else:
        txn.locked_base_rate = commission_engine.base_rate_for(db, product, company)
        txn.locked_year_commissions = None
    db.flush()
    audit.record(db, current.id, "create", "transaction", txn.id,
                 after={"ref": txn.ref, "notional": txn.notional, "agent_id": txn.agent_id,
                        "product_id": txn.product_id, "trade_date": txn.trade_date,
                        "locked_base_rate": str(txn.locked_base_rate),
                        "locked_year_commissions": txn.locked_year_commissions})
    db.commit(); db.refresh(txn)
    return txn


@app.post("/transactions/preview", response_model=schemas.CommissionPreviewOut)
def preview_transaction(payload: schemas.TransactionPreviewIn,
                        db: Session = Depends(get_db),
                        current: Agent = Depends(require_admin)):
    product = db.get(Product, payload.product_id)
    if product is None or db.get(Agent, payload.agent_id) is None:
        raise HTTPException(404, "product or agent not found")
    closing_id = payload.agent_id
    lead_id = payload.lead_agent_id or closing_id
    sales_dev_id = payload.sales_dev_agent_id or closing_id
    overrides = [{"agent_id": r.agent_id, "pct": float(r.pct)} for r in (payload.direct_overrides or [])]
    lines = commission_engine.preview(
        db, product, payload.notional, payload.trade_date or date.today(),
        lead_id, sales_dev_id, closing_id,
        payload.lead_pct, payload.sales_dev_pct, payload.closing_pct,
        deal_type=payload.deal_type, direct_overrides=overrides,
    )
    total = sum((line["amount"] for line in lines), start=Decimal("0"))
    return schemas.CommissionPreviewOut(lines=lines, total=total)


@app.get("/transactions/override-defaults")
def override_defaults(lead_agent_id: int, product_id: int,
                      trade_date: date | None = None,
                      db: Session = Depends(get_db),
                      current: Agent = Depends(require_admin)):
    """Default 代理 override levels for a lead agent + product: the lead's upline
    chain with the rule rate per gap, used to pre-fill the editable editor."""
    product = db.get(Product, product_id)
    if product is None:
        raise err(404, "product_not_found", "product not found")
    rows = commission_engine.hierarchy_overrides(
        db, lead_agent_id, product.type, trade_date or date.today())
    out = []
    for r in rows:
        ag = db.get(Agent, r["agent_id"])
        out.append({"agent_id": r["agent_id"], "level_gap": r["level_gap"],
                    "pct": r["pct"],
                    "agent_name": ag.name if ag else None,
                    "agent_code": ag.code if ag else None})
    return out


@app.patch("/transactions/{txn_id}", response_model=schemas.TransactionOut)
def update_transaction(txn_id: int, payload: schemas.TransactionUpdate,
                       db: Session = Depends(get_db),
                       current: Agent = Depends(require_admin)):
    """Admin edits a transaction's fields; settled entries are recomputed."""
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "transaction not found")
    _guard_company(db, current, txn.agent_id)
    data = payload.model_dump(exclude_unset=True)
    if "client_id" in data and db.get(Client, data["client_id"]) is None:
        raise HTTPException(404, "client not found")
    if "product_id" in data and db.get(Product, data["product_id"]) is None:
        raise HTTPException(404, "product not found")
    if "agent_id" in data and db.get(Agent, data["agent_id"]) is None:
        raise HTTPException(404, "agent not found")
    before = {"notional": txn.notional, "agent_id": txn.agent_id,
              "product_id": txn.product_id, "trade_date": txn.trade_date}
    if "deal_type" in data:
        data["deal_type"] = DealType(data["deal_type"] or "agent")
    if "direct_overrides" in data:
        rows = data["direct_overrides"] or []
        data["direct_overrides"] = [
            {"agent_id": r["agent_id"], "pct": float(r["pct"])} for r in rows
        ] or None
    for k, v in data.items():
        setattr(txn, k, v)
    db.flush()
    # Keep the derived ledger in step with the edited transaction.
    commission_engine.compute_for_transaction(db, txn)
    audit.record(db, current.id, "update", "transaction", txn.id, before=before, after=data)
    db.commit(); db.refresh(txn)
    return txn


@app.delete("/transactions/{txn_id}")
def delete_transaction(txn_id: int, db: Session = Depends(get_db),
                       current: Agent = Depends(require_admin)):
    """Delete a transaction and its (unpaid) ledger entries. 409 if any are paid."""
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "transaction not found")
    _guard_company(db, current, txn.agent_id)
    paid = db.execute(
        select(func.count()).select_from(CommissionEntry)
        .where(CommissionEntry.transaction_id == txn_id, CommissionEntry.paid.is_(True))
    ).scalar()
    if paid:
        raise HTTPException(409, "cannot delete a transaction with paid commission; cancel it instead")
    db.execute(delete(CommissionEntry).where(CommissionEntry.transaction_id == txn_id))
    audit.record(db, current.id, "delete", "transaction", txn_id,
                 before={"ref": txn.ref, "notional": txn.notional})
    db.delete(txn); db.commit()
    return {"deleted": txn_id}


@app.post("/transactions/{txn_id}/approve", response_model=schemas.TransactionOut)
def approve_transaction(txn_id: int, payload: schemas.ApproveIn | None = Body(default=None),
                        db: Session = Depends(get_db),
                        current: Agent = Depends(require_admin)):
    """Admin approves a transaction -> it becomes commissionable. Optionally
    overrides the locked rate at this point (the 'final rate'): pass
    year_commissions for a per-year product, or base_commission_rate for a flat
    one. The override is stored on the transaction so recompute/accruals keep it."""
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise err(404, "not_found", "transaction not found")
    _guard_company(db, current, txn.agent_id)
    before = {"status": txn.status.value, "locked_base_rate": str(txn.locked_base_rate),
              "locked_year_commissions": txn.locked_year_commissions}
    if payload is not None:
        if payload.year_commissions is not None:
            txn.locked_year_commissions = [str(x) for x in payload.year_commissions]
            if payload.year_commissions:
                txn.locked_base_rate = payload.year_commissions[0]
        if payload.base_commission_rate is not None:
            txn.locked_base_rate = payload.base_commission_rate
    txn.status = TxnStatus.APPROVED
    txn.settled_at = now_utc()
    db.flush()
    commission_engine.compute_for_transaction(db, txn)
    audit.record(db, current.id, "approve", "transaction", txn.id,
                 before=before, after={"status": txn.status.value,
                                       "locked_base_rate": str(txn.locked_base_rate),
                                       "locked_year_commissions": txn.locked_year_commissions})
    db.commit()
    return txn


@app.post("/transactions/{txn_id}/cancel", response_model=schemas.TransactionOut)
def cancel_transaction(txn_id: int, db: Session = Depends(get_db),
                       current: Agent = Depends(require_admin)):
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "transaction not found")
    _guard_company(db, current, txn.agent_id)
    before = {"status": txn.status.value}
    txn.status = TxnStatus.CANCELLED
    db.flush()
    # Clawback: writes negative reversal entries (decision 5).
    commission_engine.compute_for_transaction(db, txn)
    audit.record(db, current.id, "cancel", "transaction", txn.id,
                 before=before, after={"status": txn.status.value})
    db.commit()
    return txn


@app.get("/clients/{client_id}/transactions", response_model=list[schemas.TransactionOut])
def client_transactions(client_id: int, db: Session = Depends(get_db),
                        current: Agent = Depends(get_current_agent)):
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(404, "client not found")
    # The owning agent, or a same-company admin, may read these.
    scoping.assert_can_access_txn(current, client.agent_id)
    if scoping.is_admin(current):
        _guard_company(db, current, client.agent_id)
    return db.execute(
        select(Transaction).where(Transaction.client_id == client_id)
    ).scalars().all()


# --- Cases (sales pipeline; agents self-serve, managers view downlines) ------
def _next_case_ref(db: Session) -> str:
    """Auto case code: L-YYYYMM-<seq> per year-month."""
    now = now_utc()
    prefix = f"L-{now.year:04d}{now.month:02d}-"
    existing = db.execute(select(Case.ref).where(Case.ref.like(prefix + "%"))).scalars().all()
    max_seq = 0
    for r in existing:
        try:
            max_seq = max(max_seq, int(r.rsplit("-", 1)[1]))
        except (ValueError, IndexError):
            continue
    return f"{prefix}{max_seq + 1:03d}"


def _validate_case_refs(db: Session, agent_ids, client_id) -> None:
    for aid in agent_ids:
        if aid is not None and db.get(Agent, aid) is None:
            raise HTTPException(404, "agent not found")
    if client_id is not None and db.get(Client, client_id) is None:
        raise HTTPException(404, "client not found")


@app.get("/cases")
def list_cases(stage: str | None = None, outcome: str | None = None,
               agent_id: int | None = None, q: str | None = None,
               db: Session = Depends(get_db),
               current: Agent = Depends(get_current_agent)):
    """Cases visible to the caller: an agent sees cases they're assigned to; a
    manager sees their whole downline's; an admin sees all. Enriched with agent +
    client names for the board."""
    visible = scoping.visible_agent_ids(db, current)
    Lead = aliased(Agent); Sdr = aliased(Agent); Closer = aliased(Agent)
    stmt = (
        select(Case, Lead.name, Lead.code, Sdr.name, Sdr.code,
               Closer.name, Closer.code, Client.name)
        .join(Lead, Case.lead_agent_id == Lead.id)
        .join(Sdr, Case.sdr_agent_id == Sdr.id, isouter=True)
        .join(Closer, Case.closer_agent_id == Closer.id, isouter=True)
        .join(Client, Case.client_id == Client.id, isouter=True)
        .where(or_(Case.lead_agent_id.in_(visible),
                   Case.sdr_agent_id.in_(visible),
                   Case.closer_agent_id.in_(visible)))
        .order_by(Case.updated_at.desc(), Case.id.desc())
    )
    if stage:
        try:
            stmt = stmt.where(Case.stage == PipelineStage(stage))
        except ValueError:
            raise err(422, "validation", f"invalid stage: {stage}")
    if outcome:
        try:
            stmt = stmt.where(Case.outcome == CaseOutcome(outcome))
        except ValueError:
            raise err(422, "validation", f"invalid outcome: {outcome}")
    if agent_id:
        stmt = stmt.where(or_(Case.lead_agent_id == agent_id,
                              Case.sdr_agent_id == agent_id,
                              Case.closer_agent_id == agent_id))
    needle = (q or "").strip().lower()
    out = []
    for (c, lead_name, lead_code, sdr_name, sdr_code,
         closer_name, closer_code, client_name) in db.execute(stmt).all():
        if needle:
            hay = " ".join(str(x or "") for x in
                           (c.ref, c.prospect_name, c.email, c.phone, lead_name,
                            lead_code, sdr_name, sdr_code, closer_name,
                            closer_code, client_name)).lower()
            if needle not in hay:
                continue
        out.append({
            "id": c.id, "ref": c.ref, "prospect_name": c.prospect_name,
            "email": c.email, "phone": c.phone, "notes": c.notes,
            "follow_up": c.follow_up, "case_types": c.case_types or [],
            "expected_afyp": float(c.expected_afyp) if c.expected_afyp is not None else None,
            "stage": c.stage.value, "outcome": c.outcome.value,
            "client_id": c.client_id, "client_name": client_name,
            "lead_agent_id": c.lead_agent_id, "lead_name": lead_name, "lead_code": lead_code,
            "sdr_agent_id": c.sdr_agent_id, "sdr_name": sdr_name, "sdr_code": sdr_code,
            "closer_agent_id": c.closer_agent_id, "closer_name": closer_name, "closer_code": closer_code,
            "created_at": c.created_at, "closed_at": c.closed_at,
        })
    return out


@app.post("/cases", response_model=schemas.CaseOut)
def create_case(payload: schemas.CaseIn, db: Session = Depends(get_db),
                current: Agent = Depends(get_current_agent)):
    _validate_case_refs(
        db, (payload.lead_agent_id, payload.sdr_agent_id, payload.closer_agent_id),
        payload.client_id)
    assigned = {payload.lead_agent_id, payload.sdr_agent_id, payload.closer_agent_id}
    if not scoping.is_admin(current) and current.id not in assigned:
        raise err(403, "forbidden", "you may only create cases you are assigned to")
    try:
        stage = PipelineStage(payload.stage or "lead")
    except ValueError:
        raise err(422, "validation", f"invalid stage: {payload.stage}")
    case = Case(
        ref=_next_case_ref(db), prospect_name=payload.prospect_name,
        email=payload.email, phone=payload.phone, notes=payload.notes,
        follow_up=payload.follow_up, case_types=payload.case_types or None,
        expected_afyp=payload.expected_afyp,
        client_id=payload.client_id, lead_agent_id=payload.lead_agent_id,
        sdr_agent_id=payload.sdr_agent_id, closer_agent_id=payload.closer_agent_id,
        stage=stage,
    )
    db.add(case); db.flush()
    audit.record(db, current.id, "create", "case", case.id,
                 after={"ref": case.ref, "prospect": case.prospect_name, "stage": stage.value})
    db.commit(); db.refresh(case)
    return case


@app.get("/cases/import-template")
def cases_import_template(current: Agent = Depends(get_current_agent)):
    """Download a ready-to-fill .xlsx template for batch lead import."""
    from app.services import lead_import
    return Response(
        lead_import.build_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="lead_import_template.xlsx"'},
    )


@app.post("/cases/import")
async def cases_import(file: UploadFile = File(...), db: Session = Depends(get_db),
                       current: Agent = Depends(get_current_agent)):
    """Batch-create leads (cases) from an uploaded Excel workbook. Agents are
    referenced by code and must be within the caller's visible scope. Each row is
    validated independently; the response reports how many were created and the
    per-row errors for those that were skipped."""
    from decimal import Decimal, InvalidOperation
    from app.services import lead_import

    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise err(400, "file_too_large", "the file exceeds the 5 MB limit")
    try:
        parsed = lead_import.parse_rows(data)
    except ValueError as e:
        raise err(422, "invalid_file", f"could not read the spreadsheet: {e}")
    if len(parsed) > 2000:
        raise err(422, "too_many_rows", "at most 2000 rows per import")

    # Resolve agent codes to ids, restricted to who the caller may assign.
    visible = list(scoping.visible_agent_ids(db, current))
    code_lookup = {code.casefold(): aid for aid, code in db.execute(
        select(Agent.id, Agent.code).where(Agent.id.in_(visible))).all()}

    def resolve(field: str, values: dict, required: bool) -> int | None:
        code = str(values.get(field) or "").strip()
        if not code:
            if required:
                raise ValueError(f"{field} 為必填 / required")
            return None
        aid = code_lookup.get(code.casefold())
        if aid is None:
            raise ValueError(f"代理編號無效或不在可見範圍 ({field}): {code}")
        return aid

    created = 0
    errors: list[dict] = []
    for item in parsed:
        rn = item["row"]
        v = item["values"]
        try:
            # A per-row SAVEPOINT so one bad row doesn't abort the whole batch.
            with db.begin_nested():
                name = str(v.get("prospect_name") or "").strip()
                if not name:
                    raise ValueError("客戶姓名為必填 / prospect_name required")
                lead_id = resolve("lead_agent_code", v, required=True)
                sdr_id = resolve("sdr_agent_code", v, required=False)
                closer_id = resolve("closer_agent_code", v, required=False)
                stage_raw = str(v.get("stage") or "").strip().lower() or "lead"
                if stage_raw not in lead_import.STAGES:
                    raise ValueError(f"階段無效 stage: {stage_raw} (有效: {', '.join(lead_import.STAGES)})")
                keys, unknown = lead_import.normalize_case_types(v.get("case_types"))
                if unknown:
                    raise ValueError(f"個案類別無效 case_types: {', '.join(unknown)}")
                afyp = None
                afyp_raw = v.get("expected_afyp")
                if afyp_raw is not None and str(afyp_raw).strip() != "":
                    try:
                        afyp = Decimal(str(afyp_raw).replace(",", "").strip())
                    except (InvalidOperation, ValueError):
                        raise ValueError(f"預計AFYP不是有效數字 expected_afyp: {afyp_raw}")

                def clean(field: str) -> str | None:
                    val = v.get(field)
                    s = str(val).strip() if val is not None else ""
                    return s or None

                case = Case(
                    ref=_next_case_ref(db), prospect_name=name,
                    email=clean("email"), phone=clean("phone"),
                    follow_up=clean("follow_up"), notes=clean("notes"),
                    case_types=keys or None, expected_afyp=afyp,
                    lead_agent_id=lead_id, sdr_agent_id=sdr_id, closer_agent_id=closer_id,
                    stage=PipelineStage(stage_raw),
                )
                db.add(case)
                db.flush()
            created += 1
        except Exception as e:  # noqa: BLE001 - reported per row
            errors.append({"row": rn, "error": str(e)})

    if created:
        audit.record(db, current.id, "import", "case", None,
                     after={"created": created, "failed": len(errors)})
    db.commit()
    return {"created": created, "failed": len(errors), "total": len(parsed),
            "errors": errors[:200]}


@app.patch("/cases/{case_id}", response_model=schemas.CaseOut)
def update_case(case_id: int, payload: schemas.CaseUpdate,
                db: Session = Depends(get_db),
                current: Agent = Depends(get_current_agent)):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    scoping.assert_can_edit_case(db, current, case)
    data = payload.model_dump(exclude_unset=True)
    _validate_case_refs(
        db, (data.get("lead_agent_id"), data.get("sdr_agent_id"), data.get("closer_agent_id")),
        data.get("client_id"))
    if data.get("stage") is not None:
        try:
            data["stage"] = PipelineStage(data["stage"])
        except ValueError:
            raise err(422, "validation", f"invalid stage: {data['stage']}")
    if data.get("outcome") is not None:
        try:
            outcome = CaseOutcome(data["outcome"])
        except ValueError:
            raise err(422, "validation", f"invalid outcome: {data['outcome']}")
        data["outcome"] = outcome
        case.closed_at = now_utc() if outcome != CaseOutcome.OPEN else None
    before = {"stage": case.stage.value, "outcome": case.outcome.value}
    for k, v in data.items():
        setattr(case, k, v)
    db.flush()
    audit.record(db, current.id, "update", "case", case.id, before=before,
                 after={k: (v.value if hasattr(v, "value") else v) for k, v in data.items()})
    db.commit(); db.refresh(case)
    return case


@app.delete("/cases/{case_id}")
def delete_case(case_id: int, db: Session = Depends(get_db),
                current: Agent = Depends(get_current_agent)):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    scoping.assert_can_edit_case(db, current, case)
    audit.record(db, current.id, "delete", "case", case_id,
                 before={"ref": case.ref, "prospect": case.prospect_name})
    db.delete(case); db.commit()
    return {"deleted": case_id}


# --- Title targets (業績目標設定; admin sets, everyone reads their own) --------
@app.get("/title-targets")
def list_title_targets(db: Session = Depends(get_db),
                       current: Agent = Depends(get_current_agent)):
    """Annual AFYP target per 職級 (0 when unset). Readable by any authenticated
    user so the dashboard can show an agent their own target progress."""
    existing = {t.title.value: t.target_afyp
                for t in db.execute(
                    select(TitleTarget).where(TitleTarget.company == current.company)
                ).scalars()}
    return [{"title": tv.value, "target_afyp": float(existing.get(tv.value, 0))}
            for tv in Title]


@app.put("/title-targets/{title}")
def set_title_target(title: str, payload: schemas.TitleTargetIn,
                     db: Session = Depends(get_db),
                     current: Agent = Depends(require_admin)):
    try:
        t_enum = Title(title)
    except ValueError:
        raise err(422, "validation", f"invalid title: {title}")
    row = db.execute(select(TitleTarget).where(
        TitleTarget.title == t_enum, TitleTarget.company == current.company
    )).scalars().first()
    if row is None:
        row = TitleTarget(title=t_enum, target_afyp=payload.target_afyp, company=current.company)
        db.add(row)
    else:
        row.target_afyp = payload.target_afyp
    audit.record(db, current.id, "update", "title_target", title,
                 after={"target_afyp": float(payload.target_afyp)})
    db.commit()
    return {"title": title, "target_afyp": float(payload.target_afyp)}


# --- Training materials (培訓資料; admin maintains, every agent browses) --------
TRAINING_MAX_UPLOAD_MB = int(os.getenv("TRAINING_MAX_UPLOAD_MB", "25"))


TRAINING_COMPANIES = ("heritree", "cpm")
# Types safe to render inline in the browser for on-screen preview. SVG/HTML are
# deliberately excluded (they can execute script from the app origin).
_PREVIEW_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/jpg",
                  "image/gif", "image/webp", "text/plain",
                  "video/mp4", "video/webm", "video/ogg", "video/quicktime"}

# Office document types that LibreOffice can render to a PDF for on-screen
# preview (browsers have no native viewer for these).
_CONVERTIBLE_TO_PDF = {
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # pptx
    "application/vnd.ms-powerpoint",                                              # ppt
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",    # docx
    "application/msword",                                                         # doc
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",          # xlsx
    "application/vnd.ms-excel",                                                   # xls
}


def _soffice_exe() -> str | None:
    import shutil
    return shutil.which("soffice") or shutil.which("libreoffice")


def _office_to_pdf(data: bytes, filename: str) -> bytes | None:
    """Render an Office doc to PDF via headless LibreOffice. Best-effort: returns
    None if LibreOffice is absent (e.g. dev) or the conversion fails, in which
    case the file simply has no on-screen preview and is downloaded instead."""
    exe = _soffice_exe()
    if not exe:
        return None
    import os, tempfile, subprocess
    safe = os.path.basename(filename) or "file"
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, safe)
        with open(src, "wb") as fh:
            fh.write(data)
        # A unique user-profile dir avoids the single-instance lock under load.
        prof = "file://" + os.path.join(tmp, "profile").replace("\\", "/")
        try:
            subprocess.run([exe, "--headless", f"-env:UserInstallation={prof}",
                            "--convert-to", "pdf", "--outdir", tmp, src],
                           check=True, timeout=120, capture_output=True)
        except Exception:
            return None
        out = os.path.join(tmp, os.path.splitext(safe)[0] + ".pdf")
        if os.path.exists(out):
            with open(out, "rb") as fh:
                return fh.read()
    return None


def _training_out(db: Session, m: TrainingMaterial) -> dict:
    """Serialise a material for the API (file bytes never included)."""
    files = db.execute(
        select(TrainingFile).where(TrainingFile.material_id == m.id)
        .order_by(TrainingFile.id)
    ).scalars().all()
    return {
        "id": m.id, "title": m.title, "category": m.category,
        "description": m.description, "link_url": m.link_url,
        "companies": m.companies or None,
        "inline_preview": bool(m.inline_preview),
        "files": [{"id": f.id, "file_name": f.file_name,
                   "content_type": f.content_type, "file_size": f.file_size,
                   "preview_content_type": f.preview_content_type}
                  for f in files],
        "has_file": len(files) > 0,
        "created_at": m.created_at, "updated_at": m.updated_at,
    }


def _visible_to_company(m: TrainingMaterial, company: str) -> bool:
    """A material with no companies set is visible to all; otherwise only to the
    companies it lists."""
    return not m.companies or company in m.companies


@app.get("/training-materials", response_model=list[schemas.TrainingMaterialOut])
def list_training_materials(category: str | None = None, q: str | None = None,
                            db: Session = Depends(get_db),
                            current: Agent = Depends(get_current_agent)):
    """Training materials (newest first). Admins see all (to manage per-company
    visibility); agents/managers see only those shown to their company."""
    stmt = select(TrainingMaterial)
    if category:
        stmt = stmt.where(TrainingMaterial.category == category)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(TrainingMaterial.title.ilike(like),
                              TrainingMaterial.description.ilike(like)))
    stmt = stmt.order_by(TrainingMaterial.created_at.desc())
    rows = db.execute(stmt).scalars().all()
    if not scoping.is_admin(current):
        rows = [m for m in rows if _visible_to_company(m, current.company)]
    return [_training_out(db, m) for m in rows]


def _clean_companies(companies: list[str] | None) -> list[str] | None:
    """Keep only known company keys; None/empty -> None (visible to all)."""
    if not companies:
        return None
    out = [c for c in companies if c in TRAINING_COMPANIES]
    return out or None


@app.post("/training-materials", response_model=schemas.TrainingMaterialOut)
def create_training_material(payload: schemas.TrainingMaterialIn,
                             db: Session = Depends(get_db),
                             current: Agent = Depends(require_admin)):
    m = TrainingMaterial(
        title=payload.title, category=payload.category,
        description=sanitize_html(payload.description), link_url=payload.link_url,
        companies=_clean_companies(payload.companies),
        inline_preview=payload.inline_preview, created_by=current.id,
    )
    db.add(m); db.flush()
    audit.record(db, current.id, "create", "training_material", m.id,
                 after={"title": m.title, "category": m.category})
    db.commit(); db.refresh(m)
    return _training_out(db, m)


@app.patch("/training-materials/{material_id}", response_model=schemas.TrainingMaterialOut)
def update_training_material(material_id: int, payload: schemas.TrainingMaterialUpdate,
                             db: Session = Depends(get_db),
                             current: Agent = Depends(require_admin)):
    m = db.get(TrainingMaterial, material_id)
    if m is None:
        raise HTTPException(404, "training material not found")
    data = payload.model_dump(exclude_unset=True)
    if "companies" in data:
        data["companies"] = _clean_companies(data["companies"])
    if "description" in data:
        data["description"] = sanitize_html(data["description"])
    before = {"title": m.title, "category": m.category, "link_url": m.link_url}
    for k, v in data.items():
        setattr(m, k, v)
    db.flush()
    audit.record(db, current.id, "update", "training_material", m.id,
                 before=before, after=data)
    db.commit(); db.refresh(m)
    return _training_out(db, m)


@app.delete("/training-materials/{material_id}")
def delete_training_material(material_id: int, db: Session = Depends(get_db),
                             current: Agent = Depends(require_admin)):
    m = db.get(TrainingMaterial, material_id)
    if m is None:
        raise HTTPException(404, "training material not found")
    db.execute(delete(TrainingFile).where(TrainingFile.material_id == material_id))
    audit.record(db, current.id, "delete", "training_material", material_id,
                 before={"title": m.title, "category": m.category})
    db.delete(m); db.commit()
    return {"deleted": material_id}


@app.post("/training-materials/{material_id}/files", response_model=schemas.TrainingMaterialOut)
async def upload_training_files(material_id: int, files: list[UploadFile] = File(...),
                                db: Session = Depends(get_db),
                                current: Agent = Depends(require_admin)):
    """Append one or more files to a material (multi-file upload)."""
    m = db.get(TrainingMaterial, material_id)
    if m is None:
        raise HTTPException(404, "training material not found")
    added = []
    for file in files:
        data = await file.read()
        if len(data) > TRAINING_MAX_UPLOAD_MB * 1024 * 1024:
            raise err(400, "file_too_large",
                      f"{file.filename or 'file'} exceeds the {TRAINING_MAX_UPLOAD_MB} MB limit")
        if not data:
            continue
        ctype = file.content_type or "application/octet-stream"
        tf = TrainingFile(
            material_id=material_id, data=data,
            file_name=file.filename or "file", content_type=ctype, file_size=len(data))
        # Render Office docs to a PDF so they can preview on screen (best-effort).
        if ctype in _CONVERTIBLE_TO_PDF:
            pdf = _office_to_pdf(data, tf.file_name)
            if pdf:
                tf.preview_data = pdf
                tf.preview_content_type = "application/pdf"
        db.add(tf)
        added.append(file.filename or "file")
    if not added:
        raise err(400, "empty_file", "no non-empty file uploaded")
    m.updated_at = now_utc()
    db.flush()
    audit.record(db, current.id, "update", "training_material", m.id,
                 after={"files_added": added})
    db.commit(); db.refresh(m)
    return _training_out(db, m)


@app.get("/training-materials/{material_id}/files/{file_id}")
def get_training_file(material_id: int, file_id: int, download: bool = False,
                      db: Session = Depends(get_db),
                      current: Agent = Depends(get_current_agent)):
    """Serve one file. Safe types render inline for on-screen preview (add
    ?download=1 to force a download); other types always download."""
    m = db.get(TrainingMaterial, material_id)
    if m is None or (not scoping.is_admin(current) and not _visible_to_company(m, current.company)):
        raise HTTPException(404, "file not found")
    row = db.get(TrainingFile, file_id)
    if row is None or row.material_id != material_id:
        raise HTTPException(404, "file not found")
    ctype = row.content_type or "application/octet-stream"
    name = (row.file_name or "file").replace('"', "")
    content, media = row.data, ctype
    if not download and ctype.lower() in _PREVIEW_TYPES:
        inline = True                                    # natively viewable
    elif not download and row.preview_data is not None:
        inline = True                                    # serve the rendered preview
        content, media = row.preview_data, row.preview_content_type or "application/pdf"
        name = os.path.splitext(name)[0] + ".pdf"
    else:
        inline = False                                   # download the original
    from urllib.parse import quote
    ascii_fallback = name.encode("ascii", "ignore").decode().strip() or "file"
    disposition = (f"{'inline' if inline else 'attachment'}; "
                   f"filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(name)}")
    return Response(
        content=content, media_type=media,
        headers={"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff"},
    )


@app.delete("/training-materials/{material_id}/files/{file_id}", response_model=schemas.TrainingMaterialOut)
def delete_training_file(material_id: int, file_id: int, db: Session = Depends(get_db),
                         current: Agent = Depends(require_admin)):
    m = db.get(TrainingMaterial, material_id)
    if m is None:
        raise HTTPException(404, "training material not found")
    row = db.get(TrainingFile, file_id)
    if row is None or row.material_id != material_id:
        raise HTTPException(404, "file not found")
    db.delete(row); m.updated_at = now_utc(); db.flush()
    audit.record(db, current.id, "delete", "training_material", m.id,
                 before={"file_removed": row.file_name})
    db.commit(); db.refresh(m)
    return _training_out(db, m)


# --- Training categories (培訓類別; the maintained list of training types) -----
@app.get("/training-categories", response_model=list[schemas.TrainingCategoryOut])
def list_training_categories(db: Session = Depends(get_db),
                             current: Agent = Depends(get_current_agent)):
    """The curated training types, readable by any authenticated agent (populates
    the portal filter and the material form's type picker)."""
    stmt = select(TrainingCategory).order_by(TrainingCategory.sort_order, TrainingCategory.name)
    return db.execute(stmt).scalars().all()


@app.post("/training-categories", response_model=schemas.TrainingCategoryOut)
def create_training_category(payload: schemas.TrainingCategoryIn,
                             db: Session = Depends(get_db),
                             current: Agent = Depends(require_admin)):
    name = payload.name.strip()
    if not name:
        raise err(422, "validation", "name is required")
    if db.execute(select(TrainingCategory).where(TrainingCategory.name == name)).first():
        raise err(409, "duplicate", "a training type with this name already exists")
    cat = TrainingCategory(name=name, sort_order=payload.sort_order)
    db.add(cat); db.flush()
    audit.record(db, current.id, "create", "training_category", cat.id, after={"name": name})
    db.commit(); db.refresh(cat)
    return cat


@app.patch("/training-categories/{category_id}", response_model=schemas.TrainingCategoryOut)
def update_training_category(category_id: int, payload: schemas.TrainingCategoryUpdate,
                             db: Session = Depends(get_db),
                             current: Agent = Depends(require_admin)):
    cat = db.get(TrainingCategory, category_id)
    if cat is None:
        raise HTTPException(404, "training category not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        new_name = (data["name"] or "").strip()
        if not new_name:
            raise err(422, "validation", "name is required")
        clash = db.execute(
            select(TrainingCategory).where(TrainingCategory.name == new_name,
                                           TrainingCategory.id != category_id)
        ).first()
        if clash:
            raise err(409, "duplicate", "a training type with this name already exists")
        data["name"] = new_name
    for k, v in data.items():
        setattr(cat, k, v)
    db.flush()
    audit.record(db, current.id, "update", "training_category", cat.id, after=data)
    db.commit(); db.refresh(cat)
    return cat


@app.delete("/training-categories/{category_id}")
def delete_training_category(category_id: int, db: Session = Depends(get_db),
                             current: Agent = Depends(require_admin)):
    cat = db.get(TrainingCategory, category_id)
    if cat is None:
        raise HTTPException(404, "training category not found")
    # Materials keep their category string; removing a type only drops it from the
    # pick list, so no materials are orphaned.
    audit.record(db, current.id, "delete", "training_category", category_id,
                 before={"name": cat.name})
    db.delete(cat); db.commit()
    return {"deleted": category_id}


# --- Reports -----------------------------------------------------------------
@app.get("/reports/agent/{agent_id}")
def report_agent(agent_id: int, start: date | None = None,
                 end: date | None = None, db: Session = Depends(get_db),
                 current: Agent = Depends(get_current_agent)):
    scoping.assert_visible(db, current, agent_id)
    return reports.agent_statement(db, agent_id, start, end)


def _agency_summary_scoped(db: Session, current: Agent,
                           start: date | None, end: date | None) -> list[dict]:
    """Agency summary that matches the on-screen team tables: every active,
    non-admin agent in the caller's visible scope (self + downlines), including
    those with no production, each carrying its 職級 target for the progress
    column. Shared by the JSON endpoint and the CSV/PDF exports."""
    ids = scoping.visible_agent_ids(db, current)
    roster = db.execute(
        select(Agent).where(Agent.id.in_(ids), Agent.is_active.is_(True),
                            Agent.role != Role.ADMIN)
    ).scalars().all()
    targets = {tt.title.value: float(tt.target_afyp)
               for tt in db.execute(
                   select(TitleTarget).where(TitleTarget.company == current.company)
               ).scalars().all() if tt.title}
    return reports.agency_summary(db, start, end, agent_ids=ids, roster=roster, targets=targets)


@app.get("/reports/agency")
def report_agency(start: date | None = None, end: date | None = None,
                  db: Session = Depends(get_db),
                  current: Agent = Depends(get_current_agent)):
    return _agency_summary_scoped(db, current, start, end)


@app.get("/reports/product-mix")
def report_product_mix(start: date | None = None, end: date | None = None,
                       db: Session = Depends(get_db),
                       current: Agent = Depends(get_current_agent)):
    ids = scoping.visible_agent_ids(db, current)
    return reports.product_mix(db, start, end, agent_ids=ids)


@app.get("/reports/agent/{agent_id}/scorecard")
def report_agent_scorecard(agent_id: int, db: Session = Depends(get_db),
                           current: Agent = Depends(get_current_agent)):
    scoping.assert_visible(db, current, agent_id)
    return reports.agent_scorecard(db, agent_id)


@app.get("/reports/team-scorecards")
def report_team_scorecards(db: Session = Depends(get_db),
                           current: Agent = Depends(get_current_agent)):
    """Scorecards for every agent in the caller's visible line (self + subtree)."""
    ids = scoping.visible_agent_ids(db, current)
    return reports.team_scorecards(db, ids)


@app.post("/reports/recompute")
def recompute(db: Session = Depends(get_db),
              current: Agent = Depends(require_admin)):
    return {"entries": commission_engine.recompute_all(db)}


@app.get("/reports/team-production")
def report_team_production(db: Session = Depends(get_db),
                           current: Agent = Depends(get_current_agent)):
    """Per-agent AFYP + commission for YTD / last month / current month, scoped."""
    ids = scoping.visible_agent_ids(db, current)
    return reports.team_production(db, ids)


@app.post("/accruals/run")
def run_accruals(as_of: date | None = None, db: Session = Depends(get_db),
                 current: Agent = Depends(require_admin)):
    """Generate trail-product commission entries that have come due (admin)."""
    return {"new_entries": commission_engine.run_accruals(db, as_of=as_of)}


# --- Exports -----------------------------------------------------------------
def _export_response(content, fmt: str, filename: str):
    if fmt == "pdf":
        return Response(content, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'})
    return Response(content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'})


@app.get("/reports/agent/{agent_id}/export")
def export_agent_statement(agent_id: int, format: str = "csv", lang: str = "zh-Hant",
                           currency: str = "USD",
                           start: date | None = None, end: date | None = None,
                           db: Session = Depends(get_db),
                           current: Agent = Depends(get_current_agent)):
    scoping.assert_visible(db, current, agent_id)
    statement = reports.agent_statement(db, agent_id, start, end)
    if format == "pdf":
        return _export_response(exports.statement_to_pdf(statement, lang, currency), "pdf",
                                f"statement_agent_{agent_id}")
    return _export_response(exports.statement_to_csv(statement, lang, currency), "csv",
                            f"statement_agent_{agent_id}")


@app.get("/reports/agency/export")
def export_agency_summary(format: str = "csv", lang: str = "zh-Hant", currency: str = "USD",
                          start: date | None = None, end: date | None = None,
                          db: Session = Depends(get_db),
                          current: Agent = Depends(get_current_agent)):
    summary = _agency_summary_scoped(db, current, start, end)
    if format == "pdf":
        return _export_response(exports.agency_summary_to_pdf(summary, lang, currency), "pdf",
                                "agency_summary")
    return _export_response(exports.agency_summary_to_csv(summary, lang, currency), "csv",
                            "agency_summary")


# --- Periods -----------------------------------------------------------------
@app.get("/periods/{ym}")
def get_period(ym: str, db: Session = Depends(get_db),
               current: Agent = Depends(get_current_agent)):
    year, month = periods.parse_ym(ym)
    period = periods.get_period(db, year, month, company=current.company)
    snapshot = periods.period_snapshot(db, year, month, company=current.company)
    return {
        "period": ym,
        "is_locked": bool(period and period.is_locked),
        "locked_at": period.locked_at.isoformat() if period and period.locked_at else None,
        "snapshot": snapshot,
    }


@app.post("/periods/{ym}/lock")
def lock_period(ym: str, db: Session = Depends(get_db),
                current: Agent = Depends(require_admin)):
    year, month = periods.parse_ym(ym)
    period = periods.lock_period(db, year, month, company=current.company)
    audit.record(db, current.id, "lock", "period", ym, after={"is_locked": True})
    db.commit()
    return {"period": ym, "is_locked": period.is_locked,
            "locked_at": period.locked_at.isoformat() if period.locked_at else None}


@app.post("/periods/{ym}/unlock")
def unlock_period(ym: str, db: Session = Depends(get_db),
                  current: Agent = Depends(require_admin)):
    year, month = periods.parse_ym(ym)
    periods.unlock_period(db, year, month, company=current.company)
    audit.record(db, current.id, "unlock", "period", ym, after={"is_locked": False})
    db.commit()
    return {"period": ym, "is_locked": False}


# --- Payouts -----------------------------------------------------------------
@app.post("/payouts/run")
def run_payout(period: str, db: Session = Depends(get_db),
               current: Agent = Depends(require_admin)):
    year, month = periods.parse_ym(period)
    result = payouts.run_payout(db, year, month, company=current.company)
    audit.record(db, current.id, "run", "payout", period,
                 after={"total": result["total"],
                        "new_entries_paid": result["new_entries_paid"]})
    db.commit()
    return result


@app.get("/payouts/{ym}")
def get_payout(ym: str, db: Session = Depends(get_db),
               current: Agent = Depends(require_admin)):
    year, month = periods.parse_ym(ym)
    return payouts.payout_summary(db, year, month, company=current.company)


@app.get("/payouts/{ym}/export")
def export_payout(ym: str, format: str = "csv", lang: str = "zh-Hant", currency: str = "USD",
                  db: Session = Depends(get_db), current: Agent = Depends(require_admin)):
    year, month = periods.parse_ym(ym)
    payout = payouts.payout_summary(db, year, month, company=current.company)
    if format == "pdf":
        return _export_response(exports.payout_to_pdf(payout, lang, currency), "pdf", f"payout_{ym}")
    return _export_response(exports.payout_to_csv(payout, lang, currency), "csv", f"payout_{ym}")


# --- Audit log (admin) -------------------------------------------------------
@app.get("/audit", response_model=list[schemas.AuditOut])
def list_audit(limit: int = 200, db: Session = Depends(get_db),
               current: Agent = Depends(require_admin)):
    from app.models.models import AuditEntry
    return db.execute(
        select(AuditEntry).join(Agent, AuditEntry.actor_agent_id == Agent.id)
        .where(Agent.company == current.company)
        .order_by(AuditEntry.id.desc()).limit(limit)
    ).scalars().all()
