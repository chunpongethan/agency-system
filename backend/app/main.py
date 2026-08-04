"""
FastAPI entrypoint. Wires up the DB, exposes CRUD + reporting endpoints.
Auth is intentionally stubbed (get_current_agent) — see the build plan for
where to slot in real JWT/role auth.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.models import (
    Base, Agent, Client, Product, Transaction, TxnStatus, now_utc,
)
from app.schemas import schemas
from app.services import commission_engine, reports, agent_service

DATABASE_URL = "sqlite:///./agency.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base.metadata.create_all(engine)

app = FastAPI(title="Agency Management System", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Agents -----------------------------------------------------------------
@app.post("/agents", response_model=schemas.AgentOut)
def create_agent(payload: schemas.AgentIn, db: Session = Depends(get_db)):
    try:
        agent_service.validate_agent(db, payload.level, payload.upline_id)
    except agent_service.ValidationError as exc:
        raise HTTPException(422, str(exc))
    agent = Agent(**payload.model_dump())
    db.add(agent); db.commit(); db.refresh(agent)
    return agent


@app.get("/agents", response_model=list[schemas.AgentOut])
def list_agents(db: Session = Depends(get_db)):
    return db.execute(select(Agent)).scalars().all()


@app.get("/agents/{agent_id}/downlines", response_model=list[schemas.AgentOut])
def downlines(agent_id: int, db: Session = Depends(get_db)):
    return db.execute(select(Agent).where(Agent.upline_id == agent_id)).scalars().all()


# --- Clients ----------------------------------------------------------------
@app.post("/clients", response_model=schemas.ClientOut)
def create_client(payload: schemas.ClientIn, db: Session = Depends(get_db)):
    client = Client(**payload.model_dump())
    db.add(client); db.commit(); db.refresh(client)
    return client


@app.get("/agents/{agent_id}/clients", response_model=list[schemas.ClientOut])
def agent_clients(agent_id: int, db: Session = Depends(get_db)):
    return db.execute(select(Client).where(Client.agent_id == agent_id)).scalars().all()


# --- Products ---------------------------------------------------------------
@app.post("/products", response_model=schemas.ProductOut)
def create_product(payload: schemas.ProductIn, db: Session = Depends(get_db)):
    product = Product(**payload.model_dump())
    db.add(product); db.commit(); db.refresh(product)
    return product


@app.get("/products", response_model=list[schemas.ProductOut])
def list_products(db: Session = Depends(get_db)):
    return db.execute(select(Product)).scalars().all()


# --- Transactions -----------------------------------------------------------
@app.post("/transactions", response_model=schemas.TransactionOut)
def create_transaction(payload: schemas.TransactionIn, db: Session = Depends(get_db)):
    data = payload.model_dump()
    data["trade_date"] = data.get("trade_date") or date.today()
    txn = Transaction(**data)
    db.add(txn); db.commit(); db.refresh(txn)
    return txn


@app.post("/transactions/{txn_id}/settle", response_model=schemas.TransactionOut)
def settle_transaction(txn_id: int, db: Session = Depends(get_db)):
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "transaction not found")
    txn.status = TxnStatus.SETTLED
    txn.settled_at = now_utc()
    db.commit()
    commission_engine.compute_for_transaction(db, txn)
    db.commit()
    return txn


@app.post("/transactions/{txn_id}/cancel", response_model=schemas.TransactionOut)
def cancel_transaction(txn_id: int, db: Session = Depends(get_db)):
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "transaction not found")
    txn.status = TxnStatus.CANCELLED
    db.commit()
    # Clawback: writes negative reversal entries (decision 5).
    commission_engine.compute_for_transaction(db, txn)
    db.commit()
    return txn


@app.get("/clients/{client_id}/transactions", response_model=list[schemas.TransactionOut])
def client_transactions(client_id: int, db: Session = Depends(get_db)):
    return db.execute(
        select(Transaction).where(Transaction.client_id == client_id)
    ).scalars().all()


# --- Reports ----------------------------------------------------------------
@app.get("/reports/agent/{agent_id}")
def report_agent(agent_id: int, start: date | None = None,
                 end: date | None = None, db: Session = Depends(get_db)):
    return reports.agent_statement(db, agent_id, start, end)


@app.get("/reports/agency")
def report_agency(start: date | None = None, end: date | None = None,
                  db: Session = Depends(get_db)):
    return reports.agency_summary(db, start, end)


@app.post("/reports/recompute")
def recompute(db: Session = Depends(get_db)):
    return {"entries": commission_engine.recompute_all(db)}
