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

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from sqlalchemy import create_engine, select, or_
from sqlalchemy.orm import Session, sessionmaker

from app.models.models import (
    Base, Agent, Client, Product, Transaction, TxnStatus, Role, now_utc,
)
from app.schemas import schemas
from app.security import verify_password, create_access_token, decode_token, hash_password
from app.services import (
    commission_engine, reports, agent_service, scoping,
    periods, payouts, exports,
)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agency.db")
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base.metadata.create_all(engine)

app = FastAPI(title="Agency Management System", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

bearer_scheme = HTTPBearer(auto_error=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Exception mapping -------------------------------------------------------
@app.exception_handler(PermissionError)
def _permission_handler(request, exc: PermissionError):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(agent_service.ValidationError)
def _validation_handler(request, exc: agent_service.ValidationError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(periods.PeriodLockedError)
def _period_locked_handler(request, exc: periods.PeriodLockedError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ValueError)
def _value_error_handler(request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


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
def login(payload: schemas.LoginIn, db: Session = Depends(get_db)):
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
    return schemas.TokenOut(access_token=token)


@app.get("/auth/me", response_model=schemas.MeOut)
def me(current: Agent = Depends(get_current_agent)):
    return current


# --- Agents ------------------------------------------------------------------
@app.post("/agents", response_model=schemas.AgentOut)
def create_agent(payload: schemas.AgentIn, db: Session = Depends(get_db),
                 current: Agent = Depends(require_admin)):
    agent_service.validate_agent(db, payload.level, payload.upline_id)
    data = payload.model_dump(exclude={"password"})
    agent = Agent(**data)
    if payload.password:
        agent.password_hash = hash_password(payload.password)
    db.add(agent); db.commit(); db.refresh(agent)
    return agent


@app.get("/agents", response_model=list[schemas.AgentOut])
def list_agents(db: Session = Depends(get_db),
                current: Agent = Depends(get_current_agent)):
    ids = scoping.visible_agent_ids(db, current)
    return db.execute(select(Agent).where(Agent.id.in_(ids))).scalars().all()


@app.get("/agents/{agent_id}/downlines", response_model=list[schemas.AgentOut])
def downlines(agent_id: int, db: Session = Depends(get_db),
              current: Agent = Depends(get_current_agent)):
    scoping.assert_visible(db, current, agent_id)
    return db.execute(select(Agent).where(Agent.upline_id == agent_id)).scalars().all()


# --- Clients -----------------------------------------------------------------
@app.post("/clients", response_model=schemas.ClientOut)
def create_client(payload: schemas.ClientIn, db: Session = Depends(get_db),
                  current: Agent = Depends(get_current_agent)):
    scoping.assert_visible(db, current, payload.agent_id)
    client = Client(**payload.model_dump())
    db.add(client); db.commit(); db.refresh(client)
    return client


@app.get("/clients/{client_id}", response_model=schemas.ClientOut)
def get_client(client_id: int, db: Session = Depends(get_db),
               current: Agent = Depends(get_current_agent)):
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(404, "client not found")
    scoping.assert_visible(db, current, client.agent_id)
    return client


@app.patch("/clients/{client_id}", response_model=schemas.ClientOut)
def update_client(client_id: int, payload: schemas.ClientUpdate,
                  db: Session = Depends(get_db),
                  current: Agent = Depends(get_current_agent)):
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(404, "client not found")
    scoping.assert_visible(db, current, client.agent_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(client, k, v)
    db.commit(); db.refresh(client)
    return client


@app.get("/agents/{agent_id}/clients", response_model=list[schemas.ClientOut])
def agent_clients(agent_id: int, db: Session = Depends(get_db),
                  current: Agent = Depends(get_current_agent)):
    scoping.assert_visible(db, current, agent_id)
    return db.execute(select(Client).where(Client.agent_id == agent_id)).scalars().all()


# --- Products ----------------------------------------------------------------
@app.post("/products", response_model=schemas.ProductOut)
def create_product(payload: schemas.ProductIn, db: Session = Depends(get_db),
                   current: Agent = Depends(require_admin)):
    product = Product(**payload.model_dump())
    db.add(product); db.commit(); db.refresh(product)
    return product


@app.get("/products", response_model=list[schemas.ProductOut])
def list_products(db: Session = Depends(get_db),
                  current: Agent = Depends(get_current_agent)):
    return db.execute(select(Product)).scalars().all()


# --- Transactions ------------------------------------------------------------
@app.post("/transactions", response_model=schemas.TransactionOut)
def create_transaction(payload: schemas.TransactionIn, adjust: bool = False,
                       db: Session = Depends(get_db),
                       current: Agent = Depends(get_current_agent)):
    scoping.assert_visible(db, current, payload.agent_id)
    client = db.get(Client, payload.client_id)
    if client is None:
        raise HTTPException(404, "client not found")
    scoping.assert_visible(db, current, client.agent_id)
    data = payload.model_dump()
    trade_date = data.get("trade_date") or date.today()
    # Period locking: reject into a locked period unless an admin routes it as an
    # adjustment into the next open period.
    allow_adjust = adjust and current.role == Role.ADMIN
    data["trade_date"] = periods.assert_open_for_trade(db, trade_date, allow_adjust)
    txn = Transaction(**data)
    db.add(txn); db.commit(); db.refresh(txn)
    return txn


@app.post("/transactions/preview", response_model=schemas.CommissionPreviewOut)
def preview_transaction(payload: schemas.TransactionPreviewIn,
                        db: Session = Depends(get_db),
                        current: Agent = Depends(get_current_agent)):
    scoping.assert_visible(db, current, payload.agent_id)
    product = db.get(Product, payload.product_id)
    closer = db.get(Agent, payload.agent_id)
    if product is None or closer is None:
        raise HTTPException(404, "product or agent not found")
    lines = commission_engine.preview(
        db, product, closer, payload.notional, payload.trade_date or date.today()
    )
    total = sum((line["amount"] for line in lines), start=Decimal("0"))
    return schemas.CommissionPreviewOut(lines=lines, total=total)


@app.post("/transactions/{txn_id}/settle", response_model=schemas.TransactionOut)
def settle_transaction(txn_id: int, db: Session = Depends(get_db),
                       current: Agent = Depends(get_current_agent)):
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "transaction not found")
    scoping.assert_visible(db, current, txn.agent_id)
    txn.status = TxnStatus.SETTLED
    txn.settled_at = now_utc()
    db.commit()
    commission_engine.compute_for_transaction(db, txn)
    db.commit()
    return txn


@app.post("/transactions/{txn_id}/cancel", response_model=schemas.TransactionOut)
def cancel_transaction(txn_id: int, db: Session = Depends(get_db),
                       current: Agent = Depends(get_current_agent)):
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "transaction not found")
    scoping.assert_visible(db, current, txn.agent_id)
    txn.status = TxnStatus.CANCELLED
    db.commit()
    # Clawback: writes negative reversal entries (decision 5).
    commission_engine.compute_for_transaction(db, txn)
    db.commit()
    return txn


@app.get("/clients/{client_id}/transactions", response_model=list[schemas.TransactionOut])
def client_transactions(client_id: int, db: Session = Depends(get_db),
                        current: Agent = Depends(get_current_agent)):
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(404, "client not found")
    scoping.assert_visible(db, current, client.agent_id)
    return db.execute(
        select(Transaction).where(Transaction.client_id == client_id)
    ).scalars().all()


# --- Reports -----------------------------------------------------------------
@app.get("/reports/agent/{agent_id}")
def report_agent(agent_id: int, start: date | None = None,
                 end: date | None = None, db: Session = Depends(get_db),
                 current: Agent = Depends(get_current_agent)):
    scoping.assert_visible(db, current, agent_id)
    return reports.agent_statement(db, agent_id, start, end)


@app.get("/reports/agency")
def report_agency(start: date | None = None, end: date | None = None,
                  db: Session = Depends(get_db),
                  current: Agent = Depends(get_current_agent)):
    ids = scoping.visible_agent_ids(db, current)
    return reports.agency_summary(db, start, end, agent_ids=ids)


@app.post("/reports/recompute")
def recompute(db: Session = Depends(get_db),
              current: Agent = Depends(require_admin)):
    return {"entries": commission_engine.recompute_all(db)}


# --- Exports -----------------------------------------------------------------
def _export_response(content, fmt: str, filename: str):
    if fmt == "pdf":
        return Response(content, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'})
    return Response(content, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'})


@app.get("/reports/agent/{agent_id}/export")
def export_agent_statement(agent_id: int, format: str = "csv",
                           start: date | None = None, end: date | None = None,
                           db: Session = Depends(get_db),
                           current: Agent = Depends(get_current_agent)):
    scoping.assert_visible(db, current, agent_id)
    statement = reports.agent_statement(db, agent_id, start, end)
    if format == "pdf":
        return _export_response(exports.statement_to_pdf(statement), "pdf",
                                f"statement_agent_{agent_id}")
    return _export_response(exports.statement_to_csv(statement), "csv",
                            f"statement_agent_{agent_id}")


@app.get("/reports/agency/export")
def export_agency_summary(format: str = "csv",
                          start: date | None = None, end: date | None = None,
                          db: Session = Depends(get_db),
                          current: Agent = Depends(get_current_agent)):
    ids = scoping.visible_agent_ids(db, current)
    summary = reports.agency_summary(db, start, end, agent_ids=ids)
    if format == "pdf":
        return _export_response(exports.agency_summary_to_pdf(summary), "pdf",
                                "agency_summary")
    return _export_response(exports.agency_summary_to_csv(summary), "csv",
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
    return {"period": ym, "is_locked": period.is_locked,
            "locked_at": period.locked_at.isoformat() if period.locked_at else None}


@app.post("/periods/{ym}/unlock")
def unlock_period(ym: str, db: Session = Depends(get_db),
                  current: Agent = Depends(require_admin)):
    year, month = periods.parse_ym(ym)
    periods.unlock_period(db, year, month)
    return {"period": ym, "is_locked": False}


# --- Payouts -----------------------------------------------------------------
@app.post("/payouts/run")
def run_payout(period: str, db: Session = Depends(get_db),
               current: Agent = Depends(require_admin)):
    year, month = periods.parse_ym(period)
    return payouts.run_payout(db, year, month)


@app.get("/payouts/{ym}")
def get_payout(ym: str, db: Session = Depends(get_db),
               current: Agent = Depends(require_admin)):
    year, month = periods.parse_ym(ym)
    return payouts.payout_summary(db, year, month)
