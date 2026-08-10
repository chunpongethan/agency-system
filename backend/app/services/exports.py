"""
Exports: CSV and PDF for agent statements and the agency summary.

`render_statement()` produces the neutral row structure that feeds both the API
JSON, the CSV writer, and the PDF renderer, so all three stay in lockstep.

Localization: every function accepts a `lang` ("zh-Hant" default, or "en"). Labels
and enum values come from services.i18n. PDFs register a CJK font so Traditional
Chinese names render; CSVs are written with a UTF-8 BOM so Excel on Windows shows
Chinese correctly.
"""
from __future__ import annotations

import csv
import io
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
)

from app.services import i18n

# We embed a real TrueType CJK font (subset) so Traditional Chinese renders in
# ANY PDF viewer. The non-embedded Adobe CID font "STSong-Light" only renders
# where the viewer ships Asian fonts, so it is a last resort. Candidates are
# tried in order; the first that exists and loads wins. A CJK_FONT_PATH env var
# (optionally "path:index" for a .ttc) overrides the search — set it in Docker
# to a bundled TrueType font such as Noto Sans CJK TC.
_CJK_FONT = "AgencyCJK"
_CJK_FALLBACK = "STSong-Light"
_FONT_CANDIDATES: list[tuple[str, int]] = [
    (r"C:\Windows\Fonts\msjh.ttc", 0),     # Microsoft JhengHei (Traditional)
    (r"C:\Windows\Fonts\mingliu.ttc", 0),  # MingLiU (Traditional)
    (r"C:\Windows\Fonts\kaiu.ttf", 0),     # DFKai-SB
    (r"C:\Windows\Fonts\msyh.ttc", 0),     # Microsoft YaHei
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
    ("/usr/share/fonts/truetype/arphic/uming.ttc", 0),
]
_registered_font: str | None = None


def _ensure_cjk_font() -> str:
    """Register (once) and return an embeddable CJK font name."""
    global _registered_font
    if _registered_font:
        return _registered_font

    candidates = list(_FONT_CANDIDATES)
    env = os.getenv("CJK_FONT_PATH")
    if env:
        path, _, idx = env.partition(":")
        candidates.insert(0, (path, int(idx) if idx else 0))

    for path, idx in candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(_CJK_FONT, path, subfontIndex=idx))
                _registered_font = _CJK_FONT
                return _registered_font
            except Exception:
                continue

    # Last resort: non-embedded Adobe CID font (viewer must supply Asian glyphs).
    pdfmetrics.registerFont(UnicodeCIDFont(_CJK_FALLBACK))
    _registered_font = _CJK_FALLBACK
    return _registered_font


# Stable display order for income kinds; unknown kinds sort last.
_KIND_ORDER = {"direct": 0, "override": 1}

# Column index of the product cell (wrapped as a Paragraph in the PDF).
_PRODUCT_COL = 4


def _pct(rate_str) -> str:
    return f'{float(rate_str) * 100:.2f}%'


# Fixed demo FX rates (per 1 USD) and symbols, mirroring the web client. Ledger
# figures are in USD; exports convert to the requested display currency.
_FX = {"USD": 1.0, "HKD": 7.8, "EUR": 0.92, "GBP": 0.79}
_SYMBOL = {"USD": "US$", "HKD": "HK$", "EUR": "€", "GBP": "£"}


def _money(amount_usd: float, currency: str | None) -> str:
    cur = currency if currency in _FX else "USD"
    return f'{_SYMBOL[cur]}{amount_usd * _FX[cur]:,.2f}'


def render_statement(statement: dict, lang: str | None = None, currency: str | None = None) -> dict:
    """
    Normalise an agent_statement dict into a header + rows + totals structure
    shared by every output format, with localized labels and enum values. The
    rows are the per-transaction commission breakdown grouped by income kind
    (direct / override) with a subtotal row per kind. Each row carries the trade
    date, client, product (with details), notional, commission rate, override
    rate, and amount. Money is shown in the requested display currency.
    """
    header = [
        [i18n.label("agent", lang), f'{statement["agent"]["name"]} ({statement["agent"]["code"]})'],
        [i18n.label("level", lang), f'L{statement["agent"]["level"]}'],
        [i18n.label("period", lang), f'{statement["period"]["start"] or "—"} → {statement["period"]["end"] or "—"}'],
        [i18n.label("currency", lang), currency if currency in _FX else "USD"],
    ]

    # Transaction-level breakdown grouped by kind, preserving a stable kind order.
    by_kind: dict[str, list[dict]] = {}
    for entry in statement.get("entries", []):
        by_kind.setdefault(entry["kind"], []).append(entry)
    kinds = sorted(by_kind, key=lambda k: _KIND_ORDER.get(k, 99))

    rows = [[
        i18n.label("kind", lang), i18n.label("ref", lang), i18n.label("date", lang),
        i18n.label("client", lang), i18n.label("product", lang), i18n.label("notional", lang),
        i18n.label("rate", lang), i18n.label("amount", lang),
    ]]
    subtotal_rows: set[int] = set()   # indices (into rows) that are subtotals
    for kind in kinds:
        group = by_kind[kind]
        kind_lbl = i18n.enum_label("kind", kind, lang)
        sub_amt = 0.0
        for entry in group:
            detail = i18n.product_detail(entry, lang)
            roles = i18n.roles_summary(entry, lang)
            product_cell = entry["product_name"] + (f' · {detail}' if detail else "")
            if roles:
                product_cell += f'\n{roles}'
            # Show only the rate relevant to this row's income kind.
            rate = entry["override_rate"] if entry.get("override_rate") else entry["commission_rate"]
            rows.append([
                kind_lbl,
                entry["transaction_ref"],
                entry["trade_date"],
                entry["client_name"],
                product_cell,
                _money(entry["notional"], currency),
                _pct(rate),
                _money(entry["amount"], currency),
            ])
            sub_amt += entry["amount"]
        subtotal_rows.add(len(rows))
        rows.append([
            f'{kind_lbl} {i18n.label("subtotal", lang)}',
            "", "", "", "", "", "", _money(sub_amt, currency),
        ])

    totals = [
        [i18n.label("direct_total", lang), _money(statement["direct_total"], currency)],
        [i18n.label("override_total", lang), _money(statement["override_total"], currency)],
        [i18n.label("grand_total", lang), _money(statement["grand_total"], currency)],
    ]
    return {"header": header, "rows": rows, "totals": totals,
            "subtotal_rows": sorted(subtotal_rows)}


# --------------------------------------------------------------------------- #
# CSV  (UTF-8 BOM so Excel on Windows renders CJK correctly)
# --------------------------------------------------------------------------- #
_BOM = "﻿"


def statement_to_csv(statement: dict, lang: str | None = None, currency: str | None = None) -> str:
    rendered = render_statement(statement, lang, currency)
    buf = io.StringIO()
    w = csv.writer(buf)
    for k, v in rendered["header"]:
        w.writerow([k, v])
    w.writerow([])
    for row in rendered["rows"]:
        w.writerow(row)
    w.writerow([])
    for k, v in rendered["totals"]:
        w.writerow([k, v])
    return _BOM + buf.getvalue()


def agency_summary_to_csv(summary: list[dict], lang: str | None = None, currency: str | None = None) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([i18n.label("agent_id", lang), i18n.label("code", lang), i18n.label("name", lang),
                i18n.label("level", lang), i18n.label("afyp", lang),
                i18n.label("commission_income", lang), i18n.label("override_income", lang),
                i18n.label("total", lang)])
    for r in summary:
        w.writerow([r["agent_id"], r["code"], r["name"], r["level"],
                    _money(r.get("afyp", 0), currency), _money(r.get("direct", 0), currency),
                    _money(r.get("override", 0), currency), _money(r["total"], currency)])
    return _BOM + buf.getvalue()


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
def _table(data, col_widths=None, highlight_rows=None):
    font = _ensure_cjk_font()
    t = Table(data, colWidths=col_widths)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
        ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    # Per-kind subtotal rows get a tinted background and a line above.
    for r in (highlight_rows or []):
        style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#dbeafe")))
        style.append(("TEXTCOLOR", (0, r), (-1, r), colors.HexColor("#1e3a8a")))
        style.append(("LINEABOVE", (0, r), (-1, r), 0.6, colors.HexColor("#93c5fd")))
    t.setStyle(TableStyle(style))
    return t


def _title_style():
    """A Title style that uses the CJK font so Chinese titles render."""
    styles = getSampleStyleSheet()
    style = styles["Title"]
    style.fontName = _ensure_cjk_font()
    return style


def statement_to_pdf(statement: dict, lang: str | None = None, currency: str | None = None) -> bytes:
    rendered = render_statement(statement, lang, currency)
    buf = io.BytesIO()
    # Landscape to fit the wider per-transaction breakdown.
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), title=i18n.label("statement_doc", lang))
    elems = [Paragraph(i18n.label("statement_title", lang), _title_style()), Spacer(1, 5 * mm)]
    elems.append(_table(rendered["header"], col_widths=[40 * mm, 120 * mm]))
    elems.append(Spacer(1, 5 * mm))

    # Wrap the product cell in a Paragraph so long name+detail strings wrap.
    cell_style = ParagraphStyle("cell", fontName=_ensure_cjk_font(), fontSize=8, leading=10)
    rows = [list(r) for r in rendered["rows"]]
    for i, row in enumerate(rows):
        if i > 0 and row[_PRODUCT_COL]:
            text = str(row[_PRODUCT_COL]).replace("\n", "<br/>")
            row[_PRODUCT_COL] = Paragraph(text, cell_style)
    elems.append(_table(rows,
                        col_widths=[24 * mm, 24 * mm, 26 * mm, 38 * mm, 66 * mm,
                                    32 * mm, 26 * mm, 32 * mm],
                        highlight_rows=rendered.get("subtotal_rows")))
    elems.append(Spacer(1, 5 * mm))
    elems.append(_table(rendered["totals"], col_widths=[60 * mm, 60 * mm]))
    doc.build(elems)
    return buf.getvalue()


def agency_summary_to_pdf(summary: list[dict], lang: str | None = None, currency: str | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), title=i18n.label("summary_doc", lang))
    elems = [Paragraph(i18n.label("summary_title", lang), _title_style()), Spacer(1, 6 * mm)]
    data = [[i18n.label("code", lang), i18n.label("name", lang), i18n.label("level", lang),
             i18n.label("afyp", lang), i18n.label("commission_income", lang),
             i18n.label("override_income", lang), i18n.label("total", lang)]]
    for r in summary:
        data.append([r["code"], r["name"], f'L{r["level"]}',
                     _money(r.get("afyp", 0), currency), _money(r.get("direct", 0), currency),
                     _money(r.get("override", 0), currency), _money(r["total"], currency)])
    elems.append(_table(data, col_widths=[24 * mm, 46 * mm, 16 * mm, 34 * mm, 34 * mm, 34 * mm, 34 * mm]))
    doc.build(elems)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Payout result (per-agent payable, split into commission / override)
# --------------------------------------------------------------------------- #
def _payout_header(payout: dict, lang: str | None, currency: str | None) -> list[list[str]]:
    return [
        [i18n.label("period", lang), payout.get("period", "")],
        [i18n.label("currency", lang), currency if currency in _FX else "USD"],
    ]


def _payout_totals(payout: dict) -> tuple[float, float]:
    rows = payout.get("payable", [])
    return (sum(r.get("direct", 0) for r in rows), sum(r.get("override", 0) for r in rows))


def payout_to_csv(payout: dict, lang: str | None = None, currency: str | None = None) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    for k, v in _payout_header(payout, lang, currency):
        w.writerow([k, v])
    w.writerow([])
    w.writerow([i18n.label("name", lang), i18n.label("code", lang), i18n.label("unit", lang),
                i18n.label("commission", lang), i18n.label("override", lang), i18n.label("payable", lang)])
    for r in payout.get("payable", []):
        w.writerow([r.get("agent_name") or f'#{r["agent_id"]}', r.get("agent_code") or "",
                    r.get("unit_code") or "", _money(r.get("direct", 0), currency),
                    _money(r.get("override", 0), currency), _money(r.get("total", 0), currency)])
    direct_tot, override_tot = _payout_totals(payout)
    w.writerow([i18n.label("total", lang), "", "",
                _money(direct_tot, currency), _money(override_tot, currency),
                _money(payout.get("total", 0), currency)])
    return _BOM + buf.getvalue()


def payout_to_pdf(payout: dict, lang: str | None = None, currency: str | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), title=i18n.label("payout_doc", lang))
    elems = [Paragraph(i18n.label("payout_title", lang), _title_style()), Spacer(1, 5 * mm)]
    elems.append(_table(_payout_header(payout, lang, currency), col_widths=[40 * mm, 120 * mm]))
    elems.append(Spacer(1, 5 * mm))

    # Unit codes can be long; wrap that cell in a Paragraph so it never overflows.
    unit_style = ParagraphStyle("unit", fontName=_ensure_cjk_font(), fontSize=9, leading=11)
    data = [[i18n.label("name", lang), i18n.label("code", lang), i18n.label("unit", lang),
             i18n.label("commission", lang), i18n.label("override", lang), i18n.label("payable", lang)]]
    for r in payout.get("payable", []):
        unit = r.get("unit_code") or ""
        data.append([r.get("agent_name") or f'#{r["agent_id"]}', r.get("agent_code") or "",
                     Paragraph(unit, unit_style) if unit else "", _money(r.get("direct", 0), currency),
                     _money(r.get("override", 0), currency), _money(r.get("total", 0), currency)])
    direct_tot, override_tot = _payout_totals(payout)
    data.append([i18n.label("total", lang), "", "",
                 _money(direct_tot, currency), _money(override_tot, currency),
                 _money(payout.get("total", 0), currency)])
    highlight = [len(data) - 1]   # tint the totals row
    elems.append(_table(data, col_widths=[48 * mm, 22 * mm, 46 * mm, 36 * mm, 36 * mm, 36 * mm],
                        highlight_rows=highlight))
    doc.build(elems)
    return buf.getvalue()
