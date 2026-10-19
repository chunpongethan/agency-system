"""
Seed the 保費融資 course assessments — one quiz PER VIDEO (集): 3 quizzes, 5
questions each, each linked to that episode's 商學院課程 video material.

Idempotent: upserts each episode quiz by title, and removes a prior combined
quiz (and its attempts) if present. Content is stored Traditional (OpenCC s2hk);
quizzes are visible to all companies.

Run INSIDE the api container, with DATABASE_URL present — this script FAILS FAST
if it is unset (it will not silently write to a throwaway SQLite file):

  sudo docker compose -f docker-compose.prod.images.yml --env-file .env \
      exec api sh -c 'echo "$DATABASE_URL"; python /app/scripts/seed_quiz_baofei_rongzi.py'

Each episode's video is matched by title (保費融資 keyword + 第N集). Pin a specific
material with QUIZ_MATERIAL_ID_1 .. QUIZ_MATERIAL_ID_3 if a match is missing/ambiguous.
"""
from __future__ import annotations

import os
import sys

for _p in ("/app/backend", os.path.abspath("backend"), os.path.abspath(".")):
    if os.path.isdir(os.path.join(_p, "app")):
        sys.path.insert(0, _p)
        break

from sqlalchemy import create_engine, select, delete
from sqlalchemy.orm import sessionmaker

from app.models.models import Base, Quiz, QuizAttempt, TrainingMaterial
from app.services.zh_convert import to_traditional

# Specific keywords (Simplified or Traditional) for a 保費融資 video — NOT bare 融資,
# which would also match the 私行 "融資工具" episode.
COURSE_KWS = ["保费融资", "保費融資"]
OLD_COMBINED_TITLE = "保费融资 · 课后测验"
PASS_PCT = 80   # 4 / 5

# (question, [options...], correct letter, explanation) — Simplified source.
RAW = [
    # --- 第1集 · 概念与条款 ---
    ("以下哪一项最贴切地描述保费融资？",
     ["像信用卡分期付款", "像为保单做按揭", "像把存款转为定期", "像把物业出租收租"], "B",
     "客户付一小部分，其余由银行借出，就像买楼付首期、做按揭。"),
    ("在保费融资中，银行贷款的抵押品是什么？",
     ["客户名下的物业", "客户的银行存款", "这张保单本身", "不需要任何抵押"], "C",
     "抵押品就是这张保单本身，保单生效后转让给银行作抵押。"),
    ("一张基本金额 100 万美元、有 7% 折扣的保单（实付 93 万），做保费融资时客户第一天约需支付多少（包括自付部分和手续费）？",
     ["约 93 万美元", "约 80.6 万美元", "约 3 万美元", "约 13.56 万美元"], "D",
     "银行借约 80.6 万，客户自付约 12.3 万，加手续费约 1.2 万，合共约 13.56 万美元。"),
    ("本例按 P 计息的方案是「P 减 1.5 厘」。以 P 为 5.25% 计，贷款利率是多少？",
     ["3.75%", "3.15%", "3.91%", "5.25%"], "A",
     "5.25% − 1.5% = 3.75%，每年利息约 3 万美元。"),
    ("另一方案按「H 加 1.2 厘」计息，并以「P 减 2.1 厘」封顶，两者取较低者。若一个月 HIBOR 为 2.71%、P 为 5.25%，实际利率是多少？",
     ["3.91%", "3.75%", "3.15%", "2.71%"], "C",
     "H + 1.2% = 3.91%，封顶 P − 2.1% = 3.15%，取较低者，封顶已生效。"),
    # --- 第2集 · 首日价值与案例 ---
    ("银行决定可以借多少钱，主要看保单的哪一项？",
     ["保单基本金额", "首日退保价值", "第 10 年预期退保价值", "客户的年收入"], "B",
     "银行只认第一天就能取回的钱，即首日退保价值。"),
    ("可借额的计算公式是？",
     ["保单基本金额 × LTV", "实付保费 − 首日退保价值", "首日退保价值 × LTV", "客户流动资产 × LTV"], "C",
     "可借额 = 首日退保价值 × LTV；LTV 越高，可借越多。"),
    ("本例首日退保价值约 85 万美元，LTV 为 95%，银行约可借多少？",
     ["约 80.6 万美元", "约 85 万美元", "约 88.4 万美元", "约 93 万美元"], "A",
     "85 万 × 95% ≈ 80.6 万美元。"),
    ("审批时银行要看客户近一个月的流动资产证明。以下哪一组认可比例正确？",
     ["存款 90% · 固定收益 85% · 股票基金 80%", "存款 100% · 固定收益 100% · 股票基金 50%",
      "存款 100% · 固定收益 85% · 股票基金 90%", "存款 100% · 固定收益 90% · 股票基金 85%"], "D",
     "存款全数认可，固定收益计九成，股票和基金计八成半。"),
    ("如果红利达到预期，第 10 年末退保，扣除贷款和所有利息后，净利润约为多少？",
     ["约 13.6 万美元", "约 22 万美元", "约 41.5 万美元", "约 93 万美元"], "C",
     "预期净利润：第 7 年约 13.6 万、第 8 年约 22 万、第 9 年约 32 万、第 10 年约 41.5 万；持有越久，回报越高，预期红利非保证。"),
    # --- 第3集 · 压力测试、流程与风险 ---
    ("以第 8 年末退保计，贷款利率由 3.75% 升至 4.75%，预期年化收益率约由 20.3% 降至多少？",
     ["约 17.5%", "约 8.4%", "约 14.4%", "约 2.5%"], "C",
     "利率升一厘到 4.75%，净利润约 15.6 万，年化收益率约 14.4%。"),
    ("利率大约升到多少，预期情景就会打和？",
     ["约 5.75%", "约 6.75%", "约 9%", "约 7.2%"], "D",
     "利率升到约 7.2%，预期情景打和；6.75% 时净利润只剩约 2.7 万。"),
    ("按现时利率 3.75%，分红实现率要跌到约多少以下才会亏本？",
     ["约 52%", "约 80%", "约 70%", "约 30%"], "A",
     "按现时利率，实现率跌到约 52% 以下才会亏本；利率升到 5.75% 时，实现率约 80% 就打和。"),
    ("为什么按 H 计息的贷款需要封顶？",
     ["H 一定比 P 高", "H 的波动比 P 大得多", "银行规定所有贷款都要封顶", "封顶可以保证客户赚钱"], "B",
     "按 P 计息利率变化相对温和；按 H 计息波动大得多，所以才需要封顶。"),
    ("关于红利风险，以下哪一句正确？",
     ["预期红利由保险公司保证派发", "做了保费融资，红利就不会变动",
      "只要利率不升，就没有红利风险", "预期红利是非保证的，实现率不及预期，回报会下降"], "D",
     "预期红利非保证，实现率不及预期，回报会下降；利率不变也不能消除这项风险。"),
]

EPISODES = [
    (1, "概念与条款", RAW[0:5]),
    (2, "首日价值与案例", RAW[5:10]),
    (3, "压力测试、流程与风险", RAW[10:15]),
]


def _t(s):
    return to_traditional(s)


def build_questions(raw):
    out = []
    for text, options, letter, expl in raw:
        out.append({
            "text": _t(text),
            "options": [_t(o) for o in options],
            "correct_index": "ABCD".index(letter),
            "explanation": _t(expl),
        })
    return out


def find_episode_material(db, n: int):
    override = os.getenv(f"QUIZ_MATERIAL_ID_{n}")
    if override and override.isdigit():
        m = db.get(TrainingMaterial, int(override))
        if m is None:
            sys.exit(f"seed_quiz: no training material with id {override} for episode {n}")
        return m
    marker = f"第{n}集"
    mats = db.execute(select(TrainingMaterial)).scalars().all()

    def is_course(m):
        title = m.title or ""
        trad = _t(title)
        return any(kw in title or kw in trad for kw in COURSE_KWS)

    hits = [m for m in mats if is_course(m) and marker in _t(m.title or "")]
    if len(hits) == 1:
        return hits[0]
    listing = "\n".join(f"  [{m.id}] {m.title}" for m in mats)
    if not hits:
        sys.exit(f"seed_quiz: no 保費融資 course matched {marker!r} for episode {n}. "
                 f"Re-run with QUIZ_MATERIAL_ID_{n}=<id>. Courses:\n{listing}")
    multi = "\n".join(f"  [{m.id}] {m.title}" for m in hits)
    sys.exit(f"seed_quiz: episode {n} matched several courses — set QUIZ_MATERIAL_ID_{n}=<id>:\n{multi}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("seed_quiz: DATABASE_URL is not set — refusing to run (would write to a "
                 "throwaway SQLite file instead of the real database). Pass it explicitly, e.g. "
                 "`exec api sh -c 'echo \"$DATABASE_URL\"; python /app/scripts/seed_quiz_baofei_rongzi.py'`")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        for q in db.execute(select(Quiz).where(Quiz.title == _t(OLD_COMBINED_TITLE))).scalars().all():
            db.execute(delete(QuizAttempt).where(QuizAttempt.quiz_id == q.id))
            db.delete(q)
            print(f"seed_quiz: removed old combined quiz id={q.id} {q.title!r}")

        nxt = (db.execute(select(Quiz.sort_order).order_by(Quiz.sort_order.desc()))
               .scalars().first() or 0)
        for n, name, raw in EPISODES:
            material = find_episode_material(db, n)
            title = _t(f"保费融资 · 第{n}集 {name} 课后测验")
            quiz = db.execute(select(Quiz).where(Quiz.title == title)).scalars().first()
            verb = "updated" if quiz else "created"
            if quiz is None:
                nxt += 1
                quiz = Quiz(title=title, sort_order=nxt)
                db.add(quiz)
            quiz.material_id = material.id
            quiz.description = _t(f"保费融资 第{n}集 · {name} 课后测验：5 题单项选择，及格 {PASS_PCT}%。")
            quiz.pass_pct = PASS_PCT
            quiz.is_active = True
            quiz.companies = None   # all companies
            quiz.questions = build_questions(raw)
            db.commit()
            print(f"seed_quiz: {verb} quiz id={quiz.id} {quiz.title!r} "
                  f"({len(quiz.questions)} questions, pass {quiz.pass_pct}%) "
                  f"-> course [{material.id}] {material.title!r}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
