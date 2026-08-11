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
    OverrideRule, Transaction, TxnStatus, Role, Title,
    CommissionSchedule, TrailFrequency,
)
from app.services import commission_engine
from app.security import hash_password

DEMO_PASSWORD = "demo1234"

import os
engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///./backend/agency.db"))
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
db = Session()

# Wipe for a clean reseed.
for tbl in reversed(Base.metadata.sorted_tables):
    db.execute(tbl.delete())
db.commit()

# Admin is NOT part of the selling hierarchy: no upline, no clients, earns no
# overrides. It only administers products, agents, rules, and transactions.
admin = Agent(code="A000", name="系統管理員", email="admin@agency.hk", level=1,
              role=Role.ADMIN, password_hash=hash_password(DEMO_PASSWORD))
db.add(admin); db.flush()

# Selling hierarchy by tree depth (level 1 = top). Roles drive production
# visibility; titles are the assigned business rank. The A-line runs 5 deep to
# exercise the gap-4 override and unlimited depth. The top is a MANAGER, not admin.
md = Agent(code="A001", name="陳嘉欣", email="grace@agency.hk", level=AgentLevel.L1,
           role=Role.MANAGER, title=Title.PRINCIPAL_PARTNER, unit_code="HQ",
           password_hash=hash_password(DEMO_PASSWORD))
db.add(md); db.flush()
sm = Agent(code="A002", name="黃樂天", email="leo@agency.hk", level=AgentLevel.L2, upline_id=md.id,
           role=Role.MANAGER, title=Title.DISTRICT_DIRECTOR, unit_code="U-LEO",
           password_hash=hash_password(DEMO_PASSWORD))
db.add(sm); db.flush()
mgr = Agent(code="A003", name="施雅麗", email="priya@agency.hk", level=AgentLevel.L3, upline_id=sm.id,
            role=Role.MANAGER, title=Title.DISTRICT_MANAGER, unit_code="U-PRIYA",
            password_hash=hash_password(DEMO_PASSWORD))
db.add(mgr); db.flush()
agent = Agent(code="A004", name="吳浩民", email="tom@agency.hk", level=AgentLevel.L4, upline_id=mgr.id,
              role=Role.AGENT, title=Title.BUSINESS_MANAGER, password_hash=hash_password(DEMO_PASSWORD))
db.add(agent); db.flush()
# A 5th level under Tom — sales here pay overrides up gaps 1..4 (Priya, Leo... wait Tom too).
sub = Agent(code="A008", name="譚艾薇", email="ivy@agency.hk", level=5, upline_id=agent.id,
            role=Role.AGENT, title=Title.BUSINESS_MANAGER, password_hash=hash_password(DEMO_PASSWORD))
db.add(sub); db.flush()

# A second line under the same L1 to exercise scoping isolation.
sm2 = Agent(code="A005", name="劉家寶", email="nadia@agency.hk", level=AgentLevel.L2, upline_id=md.id,
            role=Role.MANAGER, title=Title.DISTRICT_DIRECTOR, unit_code="U-NADIA",
            password_hash=hash_password(DEMO_PASSWORD))
db.add(sm2); db.flush()
mgr2 = Agent(code="A006", name="伊藤健", email="ken@agency.hk", level=AgentLevel.L3, upline_id=sm2.id,
             role=Role.MANAGER, title=Title.DISTRICT_MANAGER, unit_code="U-KEN",
             password_hash=hash_password(DEMO_PASSWORD))
db.add(mgr2); db.flush()
agent2 = Agent(code="A007", name="林曉琳", email="sara@agency.hk", level=AgentLevel.L4, upline_id=mgr2.id,
               role=Role.AGENT, title=Title.BUSINESS_MANAGER, password_hash=hash_password(DEMO_PASSWORD))
db.add(agent2); db.flush()

# Products
prods = {
    # Base (upfront) rate = Yr1 commission (0.05) for insurance products.
    # afyp_conversion: AFYP = notional × this rate.
    "insurance": Product(code="INS-WL", name="終身壽險計劃", type=ProductType.INSURANCE,
                         provider="永明金融", base_commission_rate=Decimal("0.0500"),
                         afyp_conversion=Decimal("1.0000"),
                         payment_tenor=10, professional_investor=False, age_min=0, age_max=70,
                         year_commissions=["0.05", "0.03", "0.02", "0.02", "0.01",
                                           "0.01", "0.01", "0.005", "0.005", "0.005"]),
    "fund": Product(code="FND-GEQ", name="環球股票基金", type=ProductType.FUND,
                    provider="貝萊德", base_commission_rate=Decimal("0.0100"),
                    afyp_conversion=Decimal("0.1000")),
    "eam": Product(code="EAM-DPM", name="全權委託資產管理帳戶", type=ProductType.EAM_ACCOUNT,
                   provider="寶盛", base_commission_rate=Decimal("0.0075"),
                   afyp_conversion=Decimal("0.1000")),
    # A trail product: pays 0.25% of notional per quarter for 4 quarters.
    "trail": Product(code="FND-TRL", name="管理收益基金（分期）", type=ProductType.FUND,
                     provider="品浩", base_commission_rate=Decimal("0.0025"),
                     afyp_conversion=Decimal("0.1000"),
                     commission_schedule=CommissionSchedule.TRAIL,
                     trail_frequency=TrailFrequency.QUARTERLY, trail_periods=4),
}
for p in prods.values():
    db.add(p)
db.flush()

# Override rules: an upline earns a percentage of the closing agent's commission.
# gap 1 = 25%, gap 2 = 20%, gap 3 = 4%, gap 4 = 1%; gap 5+ earns nothing.
# Uniform across product types (admins can edit per product type in the UI).
OVERRIDE_SCHEDULE = [Decimal("0.25"), Decimal("0.20"), Decimal("0.04"), Decimal("0.01")]
for ptype in ProductType:
    for gap, rate in enumerate(OVERRIDE_SCHEDULE, start=1):
        db.add(OverrideRule(product_type=ptype, level_gap=gap, override_rate=rate))
db.flush()

# Clients (owned by the frontline agents)
# Risk profiles stay as canonical English values so the UI can localize them
# both ways; client names are Chinese demo data (shown as entered).
c1 = Client(ref="C001", name="威靈頓家族信託", agent_id=agent.id, risk_profile="Balanced")
c2 = Client(ref="C002", name="田中先生", agent_id=agent.id, risk_profile="Growth")
c3 = Client(ref="C003", name="蘭花控股", agent_id=agent2.id, risk_profile="Conservative")
c4 = Client(ref="C004", name="蓮花創投", agent_id=sub.id, risk_profile="Growth")
db.add_all([c1, c2, c3, c4]); db.flush()

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
    # Ivy (level 5) closes: overrides flow up gaps 1..4 (Tom, Priya, Leo, Grace).
    Transaction(ref="T0005", client_id=c4.id, product_id=prods["insurance"].id,
                agent_id=sub.id, notional=Decimal("200000"), trade_date=date.today()),
]
from app.models.models import now_utc
for t in txns:
    t.status = TxnStatus.APPROVED
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
