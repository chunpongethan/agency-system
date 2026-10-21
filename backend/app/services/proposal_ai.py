"""
AI analysis of a 建議書 (insurance proposal) PDF.

Sends the PDF itself to Claude as a document block (so tables and charts are read
as laid out), falling back to the extracted text if the document call fails. Uses
the shared kb_ai.complete() client/config (ANTHROPIC_API_KEY / ANTHROPIC_MODEL).
"""
from __future__ import annotations

import base64
import logging

from app.services import kb_ai

log = logging.getLogger(__name__)

_MAX_TOKENS = 4096
_MAX_TEXT_CHARS = 60_000   # cap for the text fallback

_SYSTEM = """你是 FOA 家辦代理系統的保險建議書分析助手，對象是持牌保險顧問。
只根據提供的建議書內容作答，不要編造任何數字；建議書沒有的資料就寫「建議書未列明」。
以繁體中文輸出 Markdown，嚴格使用以下三個二級標題，順序不變：

## 計劃摘要
用淺白語言說明：計劃類型、受保人資料（年齡/性別）、貨幣、每年保費、繳費年期、總保費、主要保障與用途。

## 保證 vs 非保證
用表格列出關鍵保單年度（例如第 5、10、15、20、30 年及最後一個列出的年度）的：
保證現金價值、非保證部分（復歸紅利/終期分紅）、預期退保總額。
並寫出：保證現金價值何時回本（收支平衡年度）、預期退保總額何時回本、建議書列明的內部回報率（如有）。
每個非保證數字都要清楚標示「非保證」。

## 顧問話術
3–5 個向客戶介紹的重點，以及 3 個客戶可能提出的疑問及建議回應。

規則：絕不說「保證回報」或把非保證利益說成保證；不要提供個人化的投資、稅務或醫療建議；
需要時提醒非保證利益取決於保險公司的分紅實現率。"""


def analyze(pdf_bytes: bytes, extracted_text: str, inputs: dict) -> dict:
    """Return {"text": markdown, "usage": {...}}; raises kb_ai.KbAiError."""
    brief = (f"受保人：{inputs.get('age')} 歲 {'男' if inputs.get('gender') == 'M' else '女'}；"
             f"產品：{inputs.get('product')}；保費：{inputs.get('currency')} {inputs.get('premium')}；"
             f"繳費年期：{inputs.get('term_years')} 年。")
    instruction = f"以下是一份保險建議書。申請資料：{brief}\n請按系統指示的三個部分分析。"

    if pdf_bytes:
        doc_msg = [{"role": "user", "content": [
            {"type": "document", "source": {
                "type": "base64", "media_type": "application/pdf",
                "data": base64.standard_b64encode(pdf_bytes).decode()}},
            {"type": "text", "text": instruction},
        ]}]
        try:
            return kb_ai.complete(_SYSTEM, doc_msg, max_tokens=_MAX_TOKENS)
        except kb_ai.KbAiError as e:
            if not extracted_text:
                raise
            log.warning("PDF document analysis failed, falling back to text: %s", e)

    if not extracted_text:
        raise kb_ai.KbAiError("proposal has no readable content")
    text_msg = [{"role": "user", "content":
                 f"{instruction}\n\n建議書文字內容：\n{extracted_text[:_MAX_TEXT_CHARS]}"}]
    return kb_ai.complete(_SYSTEM, text_msg, max_tokens=_MAX_TOKENS)
