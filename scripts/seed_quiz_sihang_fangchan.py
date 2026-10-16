"""
Seed the 私行房产收益方案 course assessments — one quiz PER VIDEO (集): 6 quizzes,
5 questions each, each linked to that episode's 商學院課程 video material.

Idempotent: upserts each episode quiz by title, and removes a prior combined
30-question quiz (and its attempts) if present. Content is stored Traditional
(OpenCC s2hk) to match the rest of the app; quizzes are visible to all companies.

Run INSIDE the api container, with DATABASE_URL present — this script FAILS FAST
if it is unset (it will not silently write to a throwaway SQLite file):

  sudo docker compose -f docker-compose.prod.images.yml --env-file .env \
      exec api sh -c 'echo "$DATABASE_URL"; python /app/scripts/seed_quiz_sihang_fangchan.py'

Each episode's video is matched by title (a 私行房产 keyword + 第N集). Pin a specific
material with QUIZ_MATERIAL_ID_1 .. QUIZ_MATERIAL_ID_6 if a match is missing/ambiguous.
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

# Keywords (either Simplified or Traditional) that mark a 私行房产 video title.
COURSE_KWS = ["私行", "房产", "房產", "闲置", "閒置", "收益方案"]
OLD_COMBINED_TITLE = "私行房产收益方案 · 课后测验"   # a combined quiz to remove, if any
PASS_PCT = 80   # 4 / 5

# (question, [options...], correct letter, explanation) — Simplified source.
RAW = [
    # --- 第1集 · 客户故事 ---
    ("故事中的北京客户，房产二十年前的买入价和今天的市值分别约是多少？",
     ["100 万 / 1,000 万", "200 万 / 2,000 万", "200 万 / 1,800 万", "500 万 / 2,000 万"], "B",
     "20 年前 200 万买入，今天市值 2,000 万，升值十倍。"),
    ("客户为什么不愿意卖房？",
     ["卖房税费太高", "房子已经出租", "家人反对", "地段好，怕卖了就再也买不回来"], "D",
     "客户认为地段好，怕卖了就再也买不回来。"),
    ("“账面财富不等于现金流”最准确的意思是？",
     ["只要房子不卖，升值就和每年要付的学费没有关系", "房产的价值被高估了",
      "银行存款不够安全", "房价已经不会再升"], "A",
     "房子不卖，1,800 万升值就变不成每年要付的学费。"),
    ("视频对“房产方案”的一句话定义是？",
     ["卖出房产，把现金拿去投资", "动用客户存款配置收息债券",
      "利用闲置资产，通过活化和配置，产生每年的现金流", "用房产抵押买入股票"], "C",
     "利用闲置资产，通过活化和配置，产生每年的现金流。"),
    ("以下哪一项不是房产方案的三个重点之一？",
     ["只用闲置房产，房子继续持有，日后升值仍归客户", "保证本金不会有任何损失",
      "不动用客户手上的任何资金", "每年产生额外的现金流"], "B",
     "三个重点是只用闲置房产、不动用客户资金、每年产生现金流；方案从不承诺保本。"),
    # --- 第2集 · 三步方案 ---
    ("第一步“闲置房产活化”中，北京客户贷出多少？抵押类经营贷年利率约是多少？",
     ["500 万，约 4%", "2,000 万，约 2.5%", "1,000 万（约房产市值一半），约 2.5%", "1,000 万，约 4.9%"], "C",
     "贷出 1,000 万，约市值一半；2026 年抵押类经营贷约 2.5%，部分银行低至 2.2%。"),
    ("第二步用贷出的资金配置什么？",
     ["银行二级资本债（Tier 2），优先选择发钞银行等高评级发行人", "票息 10%–12% 的低评级高息债",
      "股票型基金", "内地银行理财产品"], "A",
     "配置银行 Tier 2 债券，优先发钞银行等高评级发行人。"),
    ("汇丰 8.113% Tier 2 债券减去经营贷成本 2.5%，1,000 万每年净收益约是多少？",
     ["25 万", "48.8 万", "81 万", "56 万"], "D",
     "8.1% − 2.5% = 5.6%，1,000 万 × 5.6% ≈ 56 万。"),
    ("第三步以债券作抵押向私人银行申请美元授信，视频里的利率是？",
     ["SOFR 加 3 厘，约 6.9%", "SOFR 加 1 厘，约 4.9%", "固定 2.5%", "HIBOR 加 1 厘，约 3.9%"], "B",
     "美元授信为 SOFR 加 1 厘，按 SOFR 约 3.88% 计约 4.9%。"),
    ("三步完成后（美元授信），按 2026 年 10 月利率估算，相对 1,000 万融资的收益率约是？",
     ["5.6%", "6.3%", "8.8%", "12.7%"], "C",
     "162 万债券收益 − 25 万经营贷 − 48.8 万授信 ≈ 88 万，约 8.8%（估算，非保证）。"),
    # --- 第3集 · 债券基础 ---
    ("同样想要更高收益，视频中我们方案选择的是哪一条路？",
     ["直接买票息 10%–12% 的高息债", "买入高股息股票", "把资金存作定期",
      "只买投资级债券（票息约 6%–8%），再用两层配置放大收益"], "D",
     "只买投资级债券，违约率低很多，再用两层配置放大收益。"),
    ("客户买入债券后，他的身份是？",
     ["债主，不是股东", "公司股东", "债券保证人", "债券发行人"], "A",
     "买债券就是把钱借给发行人：你是债主，不是股东。"),
    ("银行倒闭时，清偿次序（由先到后）哪一项正确？",
     ["普通股 → AT1 → Tier 2 → 高级债 → 存款", "存款 → Tier 2 → 高级债 → AT1 → 普通股",
      "存款 → 高级债 → Tier 2 → AT1 → 普通股", "高级债 → 存款 → AT1 → Tier 2 → 普通股"], "C",
     "存款 → 高级债 → Tier 2 → AT1 → 普通股；Tier 2 收益较高，正因为排在存款和高级债之后。"),
    ("债券买入价高于面值 100 时，以下哪一项正确？",
     ["实际孳息率会高于票面息率", "实际孳息率会低于票面息率", "票面息率会随之上调", "对回报没有影响"], "B",
     "票面息率不等于回报；买入价高于 100，实际孳息率低于票息。"),
    ("评级 AAA 至 BBB+ 的债券，私人银行通常可借几成？",
     ["五成", "两成半", "六成", "八成"], "D",
     "AAA 至 BBB+ 通常可借八成；BBB/BBB− 六成；BB 五成；B+ 两成半。"),
    # --- 第4集 · 选发行人与价格 ---
    ("D-SIB 是指什么？",
     ["全球系统重要性保险公司", "负责发行港元纸币的银行",
      "本地系统重要性银行，俗称“大到不能倒”的银行", "香港金融管理局"], "C",
     "D-SIB = Domestic Systemically Important Bank，本地系统重要性银行。"),
    ("按金管局 2025 年底检讨，以下哪一家不在五家 D-SIB 名单内？",
     ["东亚银行", "恒生银行", "工银亚洲", "渣打香港"], "A",
     "五家为汇丰、中银香港、渣打香港、恒生、工银亚洲；东亚银行自 2022 年起不在名单内。"),
    ("D-SIB 要额外持有的资本缓冲（HLA），占普通股权一级资本的比例是？",
     ["0.5%–1%", "1%–3.5%", "5%–8%", "10%"], "B",
     "HLA 占普通股权一级资本的 1% 至 3.5%。"),
    ("汇丰 8.113% 2033 债券，2025 年 8 月以约 117 买入并持有至 2032 年赎回，年回报约是多少？",
     ["8.1%", "6.3%", "10%", "5.2%"], "D",
     "价格升到约 117 时买入，持有至 2032 年赎回，年回报只有约 5.2%。"),
    ("债券价格中途会上落，在什么前提下，波动不影响取回面值？",
     ["持有到期，而且发行人不违约", "价格始终高于买入价", "市场利率下降", "只要是 D-SIB 发行的债券"], "A",
     "持有到期、发行人不违约，到期回到面值 100；中途卖出或触发追加保证金则可能亏钱。"),
    # --- 第5集 · 融资工具 ---
    ("私人银行多币种循环短期贷款的特点，不包括以下哪一项？",
     ["循环：额度内可提取、偿还、再重复使用", "固定利率，十年不变",
      "多币种：可用港元、美元或瑞士法郎等提款", "短期：每笔提款一般六个月或十二个月，到期续借"], "B",
     "利率是同业拆息加固定利差，属浮动利率，每期重定。"),
    ("视频说瑞郎授信便宜，原因是什么？",
     ["瑞士银行提供补贴", "瑞郎长期贬值", "有保单作抵押",
      "瑞士央行维持零利率，瑞郎基准利率 SARON 约为零"], "D",
     "瑞士央行维持零利率，SARON 约为零，瑞郎授信成本约 1%。"),
    ("2023 年底到 2024 年中利率高峰期间，汇丰 8.113% 债券与美元授信成本的利差最窄约是多少？",
     ["+1.8%，仍是正数", "−0.5%，转为负数", "+3.4%", "+7.1%"], "A",
     "高峰期借钱成本 6.34%，利差最窄约 1.8%，但仍是正数。"),
    ("2022 年 11 月至今，瑞郎兑美元升值约 16%。对瑞郎授信的客户来说，这代表什么？",
     ["债券票息随之提高", "资产增值约 16%", "负债以美元计加重约一成六", "对客户没有影响"], "C",
     "瑞郎升值约 16%，负债以美元计加重约一成六：瑞郎授信的风险在汇率。"),
    ("方案中贷款人抵押保险的作用，不包括以下哪一项？",
     ["风险对冲：受保人身故时，赔偿可用来清偿贷款", "保证债券发行人不会违约",
      "提升授信：现金价值是优质抵押品", "长期增值：现金价值增长可部分抵消瑞郎升值的压力"], "B",
     "抵押保险的作用是风险对冲、提升授信、长期增值；它不能保证债券不违约。"),
    # --- 第6集 · 实证与风险 ---
    ("视频列出的“五大风险”不包括以下哪一项？",
     ["利率风险", "汇率风险", "通胀风险", "流动性风险"], "C",
     "五大风险：利率、追加保证金、发行人、汇率、流动性。"),
    ("“追加保证金”风险是指什么？",
     ["债券价格下跌或被降级，银行可借额减少，客户要补钱，甚至被迫卖出", "保险公司加收保费",
      "银行提高存款利率", "发行人提前赎回债券"], "A",
     "价格下跌或降级 → 可借额减少 → 客户补钱或被迫卖出。"),
    ("以下哪一项不是视频给出的风险管理建议？",
     ["持有组合 5 年以上", "借额限制在 1 : 1", "保留至少一年利息的现金储备", "把可借额用尽，以提高收益"], "D",
     "建议是持有 5 年以上、借额限制在 1 : 1、保留一年利息现金储备；用尽可借额会加大追加保证金风险。"),
    ("以下哪一类客户不适合这个方案？",
     ["持有已升值的房产，有明确的每年现金流需要", "收入不稳定、没有现金储备，完全不能接受本金波动",
      "理解并接受利率和追加保证金的风险", "想建立自己的退休现金流"], "B",
     "收入不稳定、没有现金储备、完全不能接受本金波动的客户不适合。"),
    ("向客户介绍方案时，哪一种说法最恰当？",
     ["“这个方案保本保息，没有风险。”", "“收益率 8.8% 是保证的。”",
      "“只要持有到期、发行人不违约，就可以取回本金；但方案有五大风险，落地前要先做风险承受能力评估和适合性分析。”",
      "“银行不会要求追加保证金。”"], "C",
     "永不对客户说“保本”或保证收益；要讲清五大风险，并先完成风险承受能力评估和适合性分析。"),
]

EPISODES = [
    (1, "客户故事", RAW[0:5]),
    (2, "三步方案", RAW[5:10]),
    (3, "债券基础", RAW[10:15]),
    (4, "选发行人与价格", RAW[15:20]),
    (5, "融资工具", RAW[20:25]),
    (6, "实证与风险", RAW[25:30]),
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
        sys.exit(f"seed_quiz: no 私行房产 course matched {marker!r} for episode {n}. "
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
                 "`exec api sh -c 'echo \"$DATABASE_URL\"; python /app/scripts/seed_quiz_sihang_fangchan.py'`")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        # Remove a prior combined 30-question quiz (and its attempts), if present.
        for q in db.execute(select(Quiz).where(Quiz.title == _t(OLD_COMBINED_TITLE))).scalars().all():
            db.execute(delete(QuizAttempt).where(QuizAttempt.quiz_id == q.id))
            db.delete(q)
            print(f"seed_quiz: removed old combined quiz id={q.id} {q.title!r}")

        nxt = (db.execute(select(Quiz.sort_order).order_by(Quiz.sort_order.desc()))
               .scalars().first() or 0)
        for n, name, raw in EPISODES:
            material = find_episode_material(db, n)
            title = _t(f"私行房产收益方案 · 第{n}集 {name} 课后测验")
            quiz = db.execute(select(Quiz).where(Quiz.title == title)).scalars().first()
            verb = "updated" if quiz else "created"
            if quiz is None:
                nxt += 1
                quiz = Quiz(title=title, sort_order=nxt)
                db.add(quiz)
            quiz.material_id = material.id
            quiz.description = _t(f"私行房产收益方案 第{n}集 · {name} 课后测验：5 题单项选择，及格 {PASS_PCT}%。")
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
