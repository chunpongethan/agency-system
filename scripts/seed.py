"""Seed a demo agency: 4-level hierarchy, products, override rules, sales."""
from __future__ import annotations

import sys, os
from decimal import Decimal
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.models import (
    Base, Agent, AgentLevel, Client, Product, ProductType,
    OverrideRule, Transaction, TxnStatus, Role,
    CommissionSchedule, TrailFrequency,
)
from app.services import commission_engine
from app.security import hash_password

DEMO_PASSWORD = "demo1234"

engine = create_engine("sqlite:///./backend/agency.db")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
db = Session()

# Wipe for a clean reseed.
for tbl in reversed(Base.metadata.sorted_tables):
    db.execute(tbl.delete())
db.commit()

# Hierarchy: L1 -> L2 -> L3 -> L4. Roles: admin at top, managers mid, agent frontline.
md = Agent(code="A001", name="Grace Chan", email="grace@agency.hk", level=AgentLevel.L1,
           role=Role.ADMIN, password_hash=hash_password(DEMO_PASSWORD))
db.add(md); db.flush()
sm = Agent(code="A002", name="Leo Wong", email="leo@agency.hk", level=AgentLevel.L2, upline_id=md.id,
           role=Role.MANAGER, password_hash=hash_password(DEMO_PASSWORD))
db.add(sm); db.flush()
mgr = Agent(code="A003", name="Priya Shah", email="priya@agency.hk", level=AgentLevel.L3, upline_id=sm.id,
            role=Role.MANAGER, password_hash=hash_password(DEMO_PASSWORD))
db.add(mgr); db.flush()
agent = Agent(code="A004", name="Tom Ng", email="tom@agency.hk", level=AgentLevel.L4, upline_id=mgr.id,
              role=Role.AGENT, password_hash=hash_password(DEMO_PASSWORD))
db.add(agent); db.flush()

# A second line under the same L1 to exercise scoping isolation (L2 -> L3 -> L4).
sm2 = Agent(code="A005", name="Nadia Rahman", email="nadia@agency.hk", level=AgentLevel.L2, upline_id=md.id,
            role=Role.MANAGER, password_hash=hash_password(DEMO_PASSWORD))
db.add(sm2); db.flush()
mgr2 = Agent(code="A006", name="Ken Ito", email="ken@agency.hk", level=AgentLevel.L3, upline_id=sm2.id,
             role=Role.MANAGER, password_hash=hash_password(DEMO_PASSWORD))
db.add(mgr2); db.flush()
agent2 = Agent(code="A007", name="Sara Lim", email="sara@agency.hk", level=AgentLevel.L4, upline_id=mgr2.id,
               role=Role.AGENT, password_hash=hash_password(DEMO_PASSWORD))
db.add(agent2); db.flush()

# Products
prods = {
    "insurance": Product(code="INS-WL", name="Whole Life Plan", type=ProductType.INSURANCE,
                         provider="Sun Life", base_commission_rate=Decimal("0.0500")),
    "fund": Product(code="FND-GEQ", name="Global Equity Fund", type=ProductType.FUND,
                    provider="BlackRock", base_commission_rate=Decimal("0.0100")),
    "eam": Product(code="EAM-DPM", name="Discretionary EAM Account", type=ProductType.EAM_ACCOUNT,
                   provider="Julius Baer", base_commission_rate=Decimal("0.0075")),
    # A trail product: pays 0.25% of notional per quarter for 4 quarters.
    "trail": Product(code="FND-TRL", name="Managed Income Fund (Trail)", type=ProductType.FUND,
                     provider="PIMCO", base_commission_rate=Decimal("0.0025"),
                     commission_schedule=CommissionSchedule.TRAIL,
                     trail_frequency=TrailFrequency.QUARTERLY, trail_periods=4),
}
for p in prods.values():
    db.add(p)
db.flush()

# Override rules: gap 1/2/3 per product type
rule_map = {
    ProductType.INSURANCE: [Decimal("0.0150"), Decimal("0.0075"), Decimal("0.0025")],
    ProductType.FUND:      [Decimal("0.0030"), Decimal("0.0015"), Decimal("0.0005")],
    ProductType.EAM_ACCOUNT:[Decimal("0.0020"), Decimal("0.0010"), Decimal("0.0005")],
}
for ptype, rates in rule_map.items():
    for gap, rate in enumerate(rates, start=1):
        db.add(OverrideRule(product_type=ptype, level_gap=gap, override_rate=rate))
db.flush()

# Clients (owned by the frontline agents)
c1 = Client(ref="C001", name="Wellington Family Trust", agent_id=agent.id, risk_profile="Balanced")
c2 = Client(ref="C002", name="K. Tanaka", agent_id=agent.id, risk_profile="Growth")
c3 = Client(ref="C003", name="Orchid Holdings", agent_id=agent2.id, risk_profile="Conservative")
db.add_all([c1, c2, c3]); db.flush()

# Transactions
txns = [
    Transaction(ref="T0001", client_id=c1.id, product_id=prods["insurance"].id,
                agent_id=agent.id, notional=Decimal("200000"), trade_date=date.today()),
    Transaction(ref="T0002", client_id=c1.id, product_id=prods["fund"].id,
                agent_id=agent.id, notional=Decimal("500000"), trade_date=date.today()),
    Transaction(ref="T0003", client_id=c2.id, product_id=prods["eam"].id,
                agent_id=agent.id, notional=Decimal("1000000"), trade_date=date.today()),
    Transaction(ref="T0004", client_id=c3.id, product_id=prods["insurance"].id,
                agent_id=agent2.id, notional=Decimal("150000"), trade_date=date.today()),
]
from app.models.models import now_utc
for t in txns:
    t.status = TxnStatus.SETTLED
    t.settled_at = now_utc()
    db.add(t)
db.flush()

for t in txns:
    commission_engine.compute_for_transaction(db, t)
db.commit()

print("Seeded. Commission entries:")
from app.models.models import CommissionEntry
for e in db.query(CommissionEntry).all():
    ag = db.get(Agent, e.agent_id)
    print(f"  txn={e.transaction_id} {ag.name:14} {e.kind.value:8} gap={e.level_gap} "
          f"rate={e.rate} amount={e.amount}")
db.close()
