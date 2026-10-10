"""
Seed the 香港分紅險101 course assessments — one quiz PER CHAPTER (4 quizzes, 5
questions each), each linked to that chapter's 商學院課程 material.

Idempotent: upserts each chapter quiz by title, and removes the old combined
20-question quiz (and its attempts) if present. Content is stored Traditional
(OpenCC s2hk) to match the rest of the app.

Run INSIDE the api container, with DATABASE_URL present (it defaults to a throwaway
SQLite file otherwise — then the rows never reach Postgres):

  sudo docker compose -f docker-compose.prod.images.yml --env-file .env \
      exec api sh -c 'echo "$DATABASE_URL"; python /app/scripts/seed_quiz_fengxiong101.py'

Each chapter's course material is matched by title (contains 分紅險101 + 第N章); a
chapter can be pinned with QUIZ_MATERIAL_ID_1 .. QUIZ_MATERIAL_ID_4 if the match
is ambiguous.
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

COURSE_KW = "分红险101"          # matched against each material title (Simplified or Traditional)
OLD_COMBINED_TITLE = "香港分红险101 · 课后测验"   # the single-quiz seed to remove
PASS_PCT = 80                    # 4 / 5

# (question, [options...], correct letter, explanation) — Simplified source.
RAW = [
    # --- 第1章 · 产品与运作 ---
    ("利益说明书上的“退保发还总额”中，哪一项是合约保证的？",
     ["保证现金价值", "复归红利", "终期分红", "以上三项全部保证"], "A",
     "退保发还总额 = 保证现金价值 + 复归红利 + 终期分红，只有第一项是合约保证"),
    ("关于复归红利和终期分红，以下哪项正确？",
     ["两者一经派发都成为保证", "复归红利要到退保时才兑现",
      "复归红利一经派发即成为保证；终期分红在退保、提取或理赔时才兑现",
      "终期分红每年派发，并由合约保证"], "C",
     "复归红利派发后成为保证；终期分红在退保、提取或理赔时才兑现"),
    ("保险公司的“平滑机制”是指：",
     ["保证每年派发相同的红利",
      "在投资好的年份留存部分盈余，在差的年份拿出来补贴，减少红利波动",
      "把投资盈余全部拨入股东账户", "完全消除非保证红利的风险"], "B",
     "好年份留存盈余、差年份补贴，减少波动但不能消除波动"),
    ("客户把红利转入“稳健资产户口”，该户口的资产配置是：",
     ["股票类 50–75%", "股票类 60–85%", "股债各半", "100% 固定收益证券"], "D",
     "稳健资产户口 100% 投资固定收益；50–75% 是产品目标组合的股票比例，60–85% 是财富跃进选项"),
    ("视频中周大福人寿的偿付能力充足率为 314%，以下理解哪项正确？",
     ["它是保单的年化回报率",
      "它等于实际资本除以最低资本要求，约为监管最低要求 150% 的两倍；展示前须核对最新数据",
      "它是公司的分红实现率", "它一经公布就固定不变，可以长期引用"], "B",
     "偿付能力充足率 = 实际资本 ÷ 最低资本要求；314% 约为 150% 的两倍；数字会变动，展示前须核对"),
    # --- 第2章 · 回报与实现率 ---
    ("从 2025 年 7 月 1 日起，美元保单的“6.5%”应该怎样向客户描述？",
     ["保险公司保证每年 6.5% 回报", "保单的预定保证利率",
      "保监局设定的利益演示上限，不是保证，也不是承诺", "过去十年的平均分红实现率"], "C",
     "6.5%（港元保单 6%）是保监局设定的演示上限，不是保证也不是承诺"),
    ("关于演示上限，监管限制的是什么？",
     ["只限制销售时利益演示的内部回报率，不限制实际派发的红利",
      "限制保险公司每年实际派发的红利", "同时限制演示和实际派发", "限制保单的保证现金价值"], "A",
     "监管只限制演示，实际派发可以高于也可以低于演示"),
    ("视频案例中，不提取的情况下，第 10 年的内部回报率约为：",
     ["0.3%", "4.2%", "5.3%", "6.5%"], "B",
     "不提取：第 5 年 0.3%、第 10 年约 4.2%、第 15 年约 5.3%"),
    ("某产品终期分红的分红实现率为 105%，这表示：",
     ["客户每年回报为 5%", "保证现金价值增加了 5%", "公司偿付能力高于监管要求 5%",
      "实际派发的非保证利益是投保时演示的 105%"], "D",
     "分红实现率 = 实际派发非保证利益 ÷ 演示非保证利益"),
    ("客户拿来某家公司某一年 120% 的实现率，顾问最合适的解读方式是：",
     ["单年最高的公司就是最好的选择", "只需要看复归红利的实现率",
      "看长期是否稳定在 100% 左右，分开看两种红利，并与同类产品、同一签发年份比较",
      "实现率超过 100% 代表公司财务有风险"], "C",
     "四个问题：看长期、分开两种红利、同类同年比较、连到提取方案"),
    # --- 第3章 · 独有功能 ---
    ("“无限次转换受保人”最早从什么时候开始可以申请？",
     ["第 3 个保单周年日", "第 6 个保单周年日", "第 5 个保单年度终结后", "第 15 个保单周年日"], "B",
     "第 6 个保单周年日起；第 3 个周年日是货币转换，第 5 年度终结后是保单分拆，第 15 个周年日是财富增值调配"),
    ("关于新受保人的条件，以下哪项不正确？",
     ["新受保人须在 0 至 65 岁之间", "如比原受保人年长，不能年长 10 岁或以上",
      "年缴保费超过 80 万美元，新受保人要回答一条健康问题", "新受保人不需要与保单持有人有可保权益"], "D",
     "新受保人必须与保单持有人有可保权益（祖父母、父母、配偶、子女或公司员工等）"),
    ("关于“类信托安排”，以下哪项正确？",
     ["可预先指定最多两位让保单延续，并自选身故赔偿支付方式；但它不是法律意义上的信托",
      "它就是法律意义上的信托，可以替代专业受托人", "身故赔偿只能一笔过支付",
      "支付方式由受益人在理赔时自行决定"], "A",
     "最多指定两位；支付方式由保单持有人在受保人在世时决定；只是“类似”信托的效果"),
    ("客户想把美元保单转换成人民币保单，以下哪项正确？",
     ["保单货币一经选定不能更改", "须重新核保，且要到第 15 个保单周年日",
      "第 3 个保单周年日起，不需要核保就可以转换", "只能在美元和港元之间转换"], "C",
     "第 3 个保单周年日起无需核保；可选美元、港元、人民币及另外五种货币"),
    ("富先生的财富增值调配例子中，以下哪项正确？",
     ["第 20 年三个方案的总值相同",
      "“保守”方案第 20 年金额最低，但稳健资产户口的钱派发后即成为保证，并可随时申请提取",
      "“增进”方案的流动性最高", "调配选项从第 5 个保单周年日起即可使用"], "B",
     "第 20 年增进约 78 万、均衡约 67 万、保守约 56 万；保守方案流动性最高；调配从第 15 个周年日起"),
    # --- 第4章 · 复利与提取 ---
    ("提取密码“5-6-7”，每年保费 2 万美元，代表什么？",
     ["缴 5 年，第 7 年起每年提取 6%，即 6,000 美元", "缴 6 年，第 5 年起每年提取 7%",
      "缴 5 年，第 6 年起每年提取年缴保费的 7%，即 1,400 美元",
      "缴 5 年，从第 6 个保单周年日起，每年提取总保费的 7%，即 7,000 美元"], "D",
     "X-Y-Z = 缴费年期 – 开始提取年份 – 每年提取总保费的百分比；总保费 10 万 × 7% = 7,000 美元"),
    ("案例一 VIP 小姐（每年 20 万美元、缴 2 年，第 2 年起每年提取 2 万），按演示到第 21 年时：",
     ["累计提取 40 万美元，等于取回全部本金，户口仍有约 40 万美元",
      "累计提取 40 万美元，户口已经归零", "累计提取 20 万美元，户口约 60 万美元",
      "累计提取 80 万美元，户口约 81 万美元"], "A",
     "第 21 年累计提取 40 万、户口约 40 万；累计 80 万、户口约 81 万是第 41 年"),
    ("案例一中，第 101 年的户口总额里，保证现金价值大约占多少？",
     ["44%", "9%", "约 0.2%", "34%"], "C",
     "保证占比：第 5 年 44%、第 21 年 34%、第 41 年约 9%、第 101 年约 0.2%"),
    ("案例二爷孙传承（爷爷每年 50 万美元、缴 2 年），到孙儿 30 岁累计提取刚好 100 万美元时，按演示户口仍有约：",
     ["100 万美元", "425 万美元", "2,980 万美元", "4,400 万美元"], "B",
     "30 岁时累计提取 100 万、户口约 425 万（本金的 4.2 倍）；2,980 万是第 75 个保单年度"),
    ("客户问“第 101 年 4,400 万美元是不是一定有”，哪个回答最恰当？",
     ["是的，这是合约保证的金额", "只要客户不提取，就一定能达到",
      "只要保险公司不倒闭，就一定能达到",
      "这是演示数字，保证部分占比很低，实际结果取决于保险公司未来能否维持分红实现率"], "D",
     "长线数字是演示，依赖非保证红利；不能说“一定有”或“保证”"),
]

CHAPTERS = [
    (1, "產品與運作", RAW[0:5]),
    (2, "回報與實現率", RAW[5:10]),
    (3, "獨有功能", RAW[10:15]),
    (4, "複利與提取", RAW[15:20]),
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


def find_chapter_material(db, ch: int):
    override = os.getenv(f"QUIZ_MATERIAL_ID_{ch}")
    if override and override.isdigit():
        m = db.get(TrainingMaterial, int(override))
        if m is None:
            sys.exit(f"seed_quiz: no training material with id {override} for chapter {ch}")
        return m
    kw_trad = _t(COURSE_KW)
    marker = f"第{ch}章"
    mats = db.execute(select(TrainingMaterial)).scalars().all()
    hits = [m for m in mats
            if (COURSE_KW in (m.title or "") or kw_trad in _t(m.title or ""))
            and marker in _t(m.title or "")]
    if len(hits) == 1:
        return hits[0]
    listing = "\n".join(f"  [{m.id}] {m.title}" for m in mats)
    if not hits:
        sys.exit(f"seed_quiz: no course matched {COURSE_KW!r} + {marker!r} for chapter {ch}. "
                 f"Re-run with QUIZ_MATERIAL_ID_{ch}=<id>. Courses:\n{listing}")
    multi = "\n".join(f"  [{m.id}] {m.title}" for m in hits)
    sys.exit(f"seed_quiz: chapter {ch} matched several courses — set QUIZ_MATERIAL_ID_{ch}=<id>:\n{multi}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///./backend/agency.db"))
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        # Remove the old combined 20-question quiz (and its attempts), if present.
        old = db.execute(select(Quiz).where(Quiz.title == _t(OLD_COMBINED_TITLE))).scalars().all()
        for q in old:
            db.execute(delete(QuizAttempt).where(QuizAttempt.quiz_id == q.id))
            db.delete(q)
            print(f"seed_quiz: removed old combined quiz id={q.id} {q.title!r}")

        nxt = (db.execute(select(Quiz.sort_order).order_by(Quiz.sort_order.desc()))
               .scalars().first() or 0)
        for ch, name, raw in CHAPTERS:
            material = find_chapter_material(db, ch)
            title = _t(f"香港分红险101 · 第{ch}章 {name} 课后测验")
            quiz = db.execute(select(Quiz).where(Quiz.title == title)).scalars().first()
            verb = "updated" if quiz else "created"
            if quiz is None:
                nxt += 1
                quiz = Quiz(title=title, sort_order=nxt)
                db.add(quiz)
            quiz.material_id = material.id
            quiz.description = _t(f"香港分红险101 第{ch}章 · {name} 课后测验：5 题单项选择，及格 {PASS_PCT}%。")
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
