"""
Backend-side localization for exports (CSV/PDF). The web UI carries its own
translation catalogue; this module only covers the labels the backend itself
renders into downloadable files. Traditional Chinese (zh-Hant) is the default.
"""
from __future__ import annotations

DEFAULT_LANG = "zh-Hant"


# Static labels used across export headers, titles and totals.
_LABELS: dict[str, dict[str, str]] = {
    "zh-Hant": {
        "agent": "代理人",
        "level": "層級",
        "period": "期間",
        "kind": "類別",
        "product_type": "產品類型",
        "count": "數量",
        "amount": "金額",
        "ref": "交易編號",
        "product": "產品",
        "notional": "名義金額",
        "direct_total": "直接佣金合計",
        "override_total": "越級佣金合計",
        "grand_total": "總計",
        "subtotal": "小計",
        "agent_id": "代理編號",
        "code": "編號",
        "name": "姓名",
        "total": "合計",
        "statement_title": "代理佣金結算表",
        "summary_title": "代理處佣金總覽",
        "statement_doc": "代理結算表",
        "summary_doc": "代理處總覽",
    },
    "en": {
        "agent": "Agent",
        "level": "Level",
        "period": "Period",
        "kind": "Kind",
        "product_type": "Product type",
        "count": "Count",
        "amount": "Amount",
        "ref": "Ref",
        "product": "Product",
        "notional": "Notional",
        "direct_total": "Direct total",
        "override_total": "Override total",
        "grand_total": "Grand total",
        "subtotal": "subtotal",
        "agent_id": "Agent ID",
        "code": "Code",
        "name": "Name",
        "total": "Total",
        "statement_title": "Agent Commission Statement",
        "summary_title": "Agency Commission Summary",
        "statement_doc": "Agent Statement",
        "summary_doc": "Agency Summary",
    },
}

# Enum values rendered inside export cells.
_ENUMS: dict[str, dict[str, dict[str, str]]] = {
    "kind": {
        "zh-Hant": {"direct": "直接佣金", "override": "越級佣金"},
        "en": {"direct": "direct", "override": "override"},
    },
    "product_type": {
        "zh-Hant": {"insurance": "保險", "fund": "基金", "eam_account": "全權委託帳戶", "other": "其他"},
        "en": {"insurance": "insurance", "fund": "fund", "eam_account": "eam_account", "other": "other"},
    },
}


def _norm(lang: str | None) -> str:
    return lang if lang in _LABELS else DEFAULT_LANG


def label(key: str, lang: str | None = None) -> str:
    return _LABELS[_norm(lang)].get(key, key)


def enum_label(kind: str, value: str, lang: str | None = None) -> str:
    table = _ENUMS.get(kind, {}).get(_norm(lang), {})
    return table.get(value, value)
