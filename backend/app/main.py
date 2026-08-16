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

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, UploadFile, File
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
    TitleTarget, TrainingMaterial, TrainingFile, TrainingCategory, now_utc,
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

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agency.db")
# Base URL of the web app, used to build password-reset links in emails.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
# Where to send login-notification emails (defaults to the bootstrap admin).
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base.metadata.create_all(engine)


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

app = FastAPI(title="承瑞家辦代理系統", version="1.0.0")

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
    agent_service.validate_agent(db, payload.level, payload.upline_id)
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
    agent = Agent(**data)
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
        select(Agent).where(Agent.is_active.is_(True), Agent.role != Role.ADMIN)
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
@app.post("/clients", response_model=schemas.ClientOut)
def create_client(payload: schemas.ClientIn, db: Session = Depends(get_db),
                  current: Agent = Depends(get_current_agent)):
    if scoping.is_admin(current):
        # Admins operate transactions on behalf of agents and may create a client
        # owned by any agent (e.g. the Lead agent when booking a new-client deal).
        if db.get(Agent, payload.agent_id) is None:
            raise HTTPException(404, "agent not found")
    elif payload.agent_id != current.id:
        raise HTTPException(403, "you may only create clients you own")
    client = Client(**payload.model_dump())
    db.add(client); db.commit(); db.refresh(client)
    return client


@app.get("/clients", response_model=list[schemas.ClientOut])
def list_clients(db: Session = Depends(get_db),
                 current: Agent = Depends(get_current_agent)):
    # Agents see their own clients; admins (the transaction operators) see all.
    q = select(Client)
    if not scoping.is_admin(current):
        q = q.where(Client.agent_id == current.id)
    return db.execute(q).scalars().all()


@app.get("/clients/{client_id}", response_model=schemas.ClientOut)
def get_client(client_id: int, db: Session = Depends(get_db),
               current: Agent = Depends(get_current_agent)):
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(404, "client not found")
    scoping.assert_can_read_client(current, client)
    return client


@app.patch("/clients/{client_id}", response_model=schemas.ClientOut)
def update_client(client_id: int, payload: schemas.ClientUpdate,
                  db: Session = Depends(get_db),
                  current: Agent = Depends(get_current_agent)):
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(404, "client not found")
    scoping.assert_owns_client(current, client)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(client, k, v)
    db.commit(); db.refresh(client)
    return client


@app.get("/agents/{agent_id}/clients", response_model=list[schemas.ClientOut])
def agent_clients(agent_id: int, db: Session = Depends(get_db),
                  current: Agent = Depends(get_current_agent)):
    # An agent lists their own clients; an admin may list any agent's clients.
    if not scoping.is_admin(current) and agent_id != current.id:
        raise HTTPException(403, "you may only list your own clients")
    return db.execute(select(Client).where(Client.agent_id == agent_id)).scalars().all()


@app.get("/agents/{agent_id}/transactions", response_model=list[schemas.TransactionOut])
def agent_transactions(agent_id: int, db: Session = Depends(get_db),
                       current: Agent = Depends(get_current_agent)):
    # Own transactions, or any if admin (admins have transaction authority).
    scoping.assert_can_access_txn(current, agent_id)
    return db.execute(
        select(Transaction).where(Transaction.agent_id == agent_id)
        .order_by(Transaction.trade_date.desc(), Transaction.id.desc())
    ).scalars().all()


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


@app.post("/products", response_model=schemas.ProductOut)
def create_product(payload: schemas.ProductIn, db: Session = Depends(get_db),
                   current: Agent = Depends(require_admin)):
    data = payload.model_dump()
    _encode_year_commissions(data)
    if data.get("type") == ProductType.INSURANCE.value:
        _sync_insurance_base_rate(data)
    product = Product(**data)
    db.add(product); db.flush()
    audit.record(db, current.id, "create", "product", product.id, after=data)
    db.commit(); db.refresh(product)
    return product


@app.patch("/products/{product_id}", response_model=schemas.ProductOut)
def update_product(product_id: int, payload: schemas.ProductUpdate,
                   db: Session = Depends(get_db),
                   current: Agent = Depends(require_admin)):
    """Admins maintain product details (including insurance product details)."""
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "product not found")
    data = payload.model_dump(exclude_unset=True)
    _encode_year_commissions(data)
    if product.type == ProductType.INSURANCE and data.get("year_commissions"):
        _sync_insurance_base_rate(data)
    for k, v in data.items():
        setattr(product, k, v)
    db.flush()
    audit.record(db, current.id, "update", "product", product.id, after=data)
    db.commit(); db.refresh(product)
    return product


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
    db.delete(product); db.commit()
    return {"deleted": product_id}


@app.get("/products", response_model=list[schemas.ProductOut])
def list_products(db: Session = Depends(get_db),
                  current: Agent = Depends(get_current_agent)):
    return db.execute(select(Product)).scalars().all()


# --- Override rules (admin) --------------------------------------------------
@app.get("/override-rules", response_model=list[schemas.OverrideRuleOut])
def list_override_rules(db: Session = Depends(get_db),
                        current: Agent = Depends(get_current_agent)):
    from app.models.models import OverrideRule
    return db.execute(select(OverrideRule)).scalars().all()


@app.post("/override-rules", response_model=schemas.OverrideRuleOut)
def create_override_rule(payload: schemas.OverrideRuleIn, db: Session = Depends(get_db),
                         current: Agent = Depends(require_admin)):
    from app.models.models import OverrideRule
    data = payload.model_dump()
    if data.get("valid_from") is None:
        data.pop("valid_from", None)  # let the column default apply
    rule = OverrideRule(**data)
    db.add(rule); db.flush()
    audit.record(db, current.id, "create", "override_rule", rule.id,
                 after=payload.model_dump())
    db.commit(); db.refresh(rule)
    return rule


@app.patch("/override-rules/{rule_id}", response_model=schemas.OverrideRuleOut)
def update_override_rule(rule_id: int, payload: schemas.OverrideRuleUpdate,
                         db: Session = Depends(get_db),
                         current: Agent = Depends(require_admin)):
    from app.models.models import OverrideRule
    rule = db.get(OverrideRule, rule_id)
    if rule is None:
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
    from app.models.models import OverrideRule
    rule = db.get(OverrideRule, rule_id)
    if rule is None:
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
               Agent.name, Agent.code)
        .join(Client, Transaction.client_id == Client.id)
        .join(Product, Transaction.product_id == Product.id)
        .join(Agent, Transaction.agent_id == Agent.id)
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
    out = []
    for txn, cname, cref, pname, ptype, aname, acode in db.execute(stmt).all():
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
            "lead_pct": txn.lead_pct, "sales_dev_pct": txn.sales_dev_pct,
            "closing_pct": txn.closing_pct,
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
    product = db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(404, "product not found")
    for aid in (payload.agent_id, payload.lead_agent_id, payload.sales_dev_agent_id):
        if aid is not None and db.get(Agent, aid) is None:
            raise HTTPException(404, "agent not found")

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
        if data["deal_type"] == DealType.DIRECT_CLIENT and not ag.direct_client:
            raise err(400, "not_direct_client", "selected agent is not 直客-eligible")
        norm.append({"agent_id": row["agent_id"], "pct": float(row["pct"])})
    data["direct_overrides"] = norm or None

    trade_date = data.get("trade_date") or date.today()
    # Admin may route a sale dated into a locked period to the next open period.
    data["trade_date"] = periods.assert_open_for_trade(db, trade_date, allow_adjust=adjust)

    # Auto-generate the transaction code when not supplied.
    if not data.get("ref"):
        data["ref"] = _next_ref(db, data["trade_date"])

    txn = Transaction(**data)
    db.add(txn); db.flush()
    audit.record(db, current.id, "create", "transaction", txn.id,
                 after={"ref": txn.ref, "notional": txn.notional, "agent_id": txn.agent_id,
                        "product_id": txn.product_id, "trade_date": txn.trade_date})
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
def approve_transaction(txn_id: int, db: Session = Depends(get_db),
                        current: Agent = Depends(require_admin)):
    """Admin approves a transaction -> it becomes commissionable."""
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise err(404, "not_found", "transaction not found")
    before = {"status": txn.status.value}
    txn.status = TxnStatus.APPROVED
    txn.settled_at = now_utc()
    db.flush()
    commission_engine.compute_for_transaction(db, txn)
    audit.record(db, current.id, "approve", "transaction", txn.id,
                 before=before, after={"status": txn.status.value})
    db.commit()
    return txn


@app.post("/transactions/{txn_id}/cancel", response_model=schemas.TransactionOut)
def cancel_transaction(txn_id: int, db: Session = Depends(get_db),
                       current: Agent = Depends(require_admin)):
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "transaction not found")
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
    # The owning agent, or an admin (transaction authority), may read these.
    scoping.assert_can_access_txn(current, client.agent_id)
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
                for t in db.execute(select(TitleTarget)).scalars()}
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
    row = db.execute(select(TitleTarget).where(TitleTarget.title == t_enum)).scalars().first()
    if row is None:
        row = TitleTarget(title=t_enum, target_afyp=payload.target_afyp)
        db.add(row)
    else:
        row.target_afyp = payload.target_afyp
    audit.record(db, current.id, "update", "title_target", title,
                 after={"target_afyp": float(payload.target_afyp)})
    db.commit()
    return {"title": title, "target_afyp": float(payload.target_afyp)}


# --- Training materials (培訓資料; admin maintains, every agent browses) --------
TRAINING_MAX_UPLOAD_MB = int(os.getenv("TRAINING_MAX_UPLOAD_MB", "25"))


def _training_out(m: TrainingMaterial) -> dict:
    """Serialise a material for the API (file bytes never included)."""
    return {
        "id": m.id, "title": m.title, "category": m.category,
        "description": m.description, "link_url": m.link_url,
        "file_name": m.file_name, "content_type": m.content_type,
        "file_size": m.file_size, "has_file": m.file_name is not None,
        "created_at": m.created_at, "updated_at": m.updated_at,
    }


@app.get("/training-materials", response_model=list[schemas.TrainingMaterialOut])
def list_training_materials(category: str | None = None, q: str | None = None,
                            db: Session = Depends(get_db),
                            current: Agent = Depends(get_current_agent)):
    """All training materials (newest first), browsable by any authenticated
    agent. Optional `category` and free-text `q` filters."""
    stmt = select(TrainingMaterial)
    if category:
        stmt = stmt.where(TrainingMaterial.category == category)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(TrainingMaterial.title.ilike(like),
                              TrainingMaterial.description.ilike(like)))
    stmt = stmt.order_by(TrainingMaterial.created_at.desc())
    return [_training_out(m) for m in db.execute(stmt).scalars()]


@app.post("/training-materials", response_model=schemas.TrainingMaterialOut)
def create_training_material(payload: schemas.TrainingMaterialIn,
                             db: Session = Depends(get_db),
                             current: Agent = Depends(require_admin)):
    m = TrainingMaterial(
        title=payload.title, category=payload.category,
        description=payload.description, link_url=payload.link_url,
        created_by=current.id,
    )
    db.add(m); db.flush()
    audit.record(db, current.id, "create", "training_material", m.id,
                 after={"title": m.title, "category": m.category})
    db.commit(); db.refresh(m)
    return _training_out(m)


@app.patch("/training-materials/{material_id}", response_model=schemas.TrainingMaterialOut)
def update_training_material(material_id: int, payload: schemas.TrainingMaterialUpdate,
                             db: Session = Depends(get_db),
                             current: Agent = Depends(require_admin)):
    m = db.get(TrainingMaterial, material_id)
    if m is None:
        raise HTTPException(404, "training material not found")
    data = payload.model_dump(exclude_unset=True)
    before = {"title": m.title, "category": m.category, "link_url": m.link_url}
    for k, v in data.items():
        setattr(m, k, v)
    db.flush()
    audit.record(db, current.id, "update", "training_material", m.id,
                 before=before, after=data)
    db.commit(); db.refresh(m)
    return _training_out(m)


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


@app.post("/training-materials/{material_id}/file", response_model=schemas.TrainingMaterialOut)
async def upload_training_file(material_id: int, file: UploadFile = File(...),
                               db: Session = Depends(get_db),
                               current: Agent = Depends(require_admin)):
    m = db.get(TrainingMaterial, material_id)
    if m is None:
        raise HTTPException(404, "training material not found")
    data = await file.read()
    if len(data) > TRAINING_MAX_UPLOAD_MB * 1024 * 1024:
        raise err(400, "file_too_large",
                  f"file exceeds the {TRAINING_MAX_UPLOAD_MB} MB limit")
    if not data:
        raise err(400, "empty_file", "uploaded file is empty")
    row = db.execute(
        select(TrainingFile).where(TrainingFile.material_id == material_id)
    ).scalars().first()
    if row is None:
        row = TrainingFile(material_id=material_id, data=data)
        db.add(row)
    else:
        row.data = data
    m.file_name = file.filename or "file"
    m.content_type = file.content_type or "application/octet-stream"
    m.file_size = len(data)
    db.flush()
    audit.record(db, current.id, "update", "training_material", m.id,
                 after={"file_name": m.file_name, "file_size": m.file_size})
    db.commit(); db.refresh(m)
    return _training_out(m)


@app.get("/training-materials/{material_id}/file")
def download_training_file(material_id: int, db: Session = Depends(get_db),
                           current: Agent = Depends(get_current_agent)):
    m = db.get(TrainingMaterial, material_id)
    if m is None or m.file_name is None:
        raise HTTPException(404, "file not found")
    row = db.execute(
        select(TrainingFile).where(TrainingFile.material_id == material_id)
    ).scalars().first()
    if row is None:
        raise HTTPException(404, "file not found")
    # Always attachment (never inline) so uploaded content can't execute in-page.
    # Encode the filename per RFC 5987 so non-ASCII names (e.g. Chinese) survive
    # the latin-1-only HTTP header: an ASCII fallback plus a UTF-8 filename*.
    from urllib.parse import quote
    name = m.file_name.replace('"', "")
    ascii_fallback = name.encode("ascii", "ignore").decode().strip() or "file"
    disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(name)}"
    return Response(
        content=row.data,
        media_type=m.content_type or "application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


@app.delete("/training-materials/{material_id}/file", response_model=schemas.TrainingMaterialOut)
def delete_training_file(material_id: int, db: Session = Depends(get_db),
                         current: Agent = Depends(require_admin)):
    m = db.get(TrainingMaterial, material_id)
    if m is None:
        raise HTTPException(404, "training material not found")
    db.execute(delete(TrainingFile).where(TrainingFile.material_id == material_id))
    m.file_name = None; m.content_type = None; m.file_size = None
    db.flush()
    audit.record(db, current.id, "delete", "training_material", m.id,
                 before={"file": "removed"})
    db.commit(); db.refresh(m)
    return _training_out(m)


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
               for tt in db.execute(select(TitleTarget)).scalars().all() if tt.title}
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
    period = periods.get_period(db, year, month)
    snapshot = periods.period_snapshot(db, year, month)
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
    period = periods.lock_period(db, year, month)
    audit.record(db, current.id, "lock", "period", ym, after={"is_locked": True})
    db.commit()
    return {"period": ym, "is_locked": period.is_locked,
            "locked_at": period.locked_at.isoformat() if period.locked_at else None}


@app.post("/periods/{ym}/unlock")
def unlock_period(ym: str, db: Session = Depends(get_db),
                  current: Agent = Depends(require_admin)):
    year, month = periods.parse_ym(ym)
    periods.unlock_period(db, year, month)
    audit.record(db, current.id, "unlock", "period", ym, after={"is_locked": False})
    db.commit()
    return {"period": ym, "is_locked": False}


# --- Payouts -----------------------------------------------------------------
@app.post("/payouts/run")
def run_payout(period: str, db: Session = Depends(get_db),
               current: Agent = Depends(require_admin)):
    year, month = periods.parse_ym(period)
    result = payouts.run_payout(db, year, month)
    audit.record(db, current.id, "run", "payout", period,
                 after={"total": result["total"],
                        "new_entries_paid": result["new_entries_paid"]})
    db.commit()
    return result


@app.get("/payouts/{ym}")
def get_payout(ym: str, db: Session = Depends(get_db),
               current: Agent = Depends(require_admin)):
    year, month = periods.parse_ym(ym)
    return payouts.payout_summary(db, year, month)


@app.get("/payouts/{ym}/export")
def export_payout(ym: str, format: str = "csv", lang: str = "zh-Hant", currency: str = "USD",
                  db: Session = Depends(get_db), current: Agent = Depends(require_admin)):
    year, month = periods.parse_ym(ym)
    payout = payouts.payout_summary(db, year, month)
    if format == "pdf":
        return _export_response(exports.payout_to_pdf(payout, lang, currency), "pdf", f"payout_{ym}")
    return _export_response(exports.payout_to_csv(payout, lang, currency), "csv", f"payout_{ym}")


# --- Audit log (admin) -------------------------------------------------------
@app.get("/audit", response_model=list[schemas.AuditOut])
def list_audit(limit: int = 200, db: Session = Depends(get_db),
               current: Agent = Depends(require_admin)):
    from app.models.models import AuditEntry
    return db.execute(
        select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)
    ).scalars().all()
