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

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
)

from app.services import i18n

# Built-in Adobe CJK font — no external file needed. Registered once, lazily.
_CJK_FONT = "STSong-Light"
_cjk_registered = False


def _ensure_cjk_font() -> str:
    global _cjk_registered
    if not _cjk_registered:
        pdfmetrics.registerFont(UnicodeCIDFont(_CJK_FONT))
        _cjk_registered = True
    return _CJK_FONT


def render_statement(statement: dict, lang: str | None = None) -> dict:
    """
    Normalise an agent_statement dict into a header + rows + totals structure
    shared by every output format, with localized labels and enum values.
    """
    header = [
        [i18n.label("agent", lang), f'{statement["agent"]["name"]} ({statement["agent"]["code"]})'],
        [i18n.label("level", lang), f'L{statement["agent"]["level"]}'],
        [i18n.label("period", lang), f'{statement["period"]["start"] or "—"} → {statement["period"]["end"] or "—"}'],
    ]
    rows = [[i18n.label("kind", lang), i18n.label("product_type", lang),
             i18n.label("count", lang), i18n.label("amount", lang)]]
    for line in statement["lines"]:
        rows.append([
            i18n.enum_label("kind", line["kind"], lang),
            i18n.enum_label("product_type", line["product_type"], lang),
            str(line["count"]),
            f'{line["amount"]:,.2f}',
        ])
    totals = [
        [i18n.label("direct_total", lang), f'{statement["direct_total"]:,.2f}'],
        [i18n.label("override_total", lang), f'{statement["override_total"]:,.2f}'],
        [i18n.label("grand_total", lang), f'{statement["grand_total"]:,.2f}'],
    ]
    return {"header": header, "rows": rows, "totals": totals}


# --------------------------------------------------------------------------- #
# CSV  (UTF-8 BOM so Excel on Windows renders CJK correctly)
# --------------------------------------------------------------------------- #
_BOM = "﻿"


def statement_to_csv(statement: dict, lang: str | None = None) -> str:
    rendered = render_statement(statement, lang)
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


def agency_summary_to_csv(summary: list[dict], lang: str | None = None) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([i18n.label("agent_id", lang), i18n.label("code", lang),
                i18n.label("name", lang), i18n.label("level", lang), i18n.label("total", lang)])
    for r in summary:
        w.writerow([r["agent_id"], r["code"], r["name"], r["level"], f'{r["total"]:,.2f}'])
    return _BOM + buf.getvalue()


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
def _table(data, col_widths=None):
    font = _ensure_cjk_font()
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
        ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _title_style():
    """A Title style that uses the CJK font so Chinese titles render."""
    styles = getSampleStyleSheet()
    style = styles["Title"]
    style.fontName = _ensure_cjk_font()
    return style


def statement_to_pdf(statement: dict, lang: str | None = None) -> bytes:
    rendered = render_statement(statement, lang)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=i18n.label("statement_doc", lang))
    elems = [Paragraph(i18n.label("statement_title", lang), _title_style()), Spacer(1, 6 * mm)]
    elems.append(_table(rendered["header"], col_widths=[40 * mm, 120 * mm]))
    elems.append(Spacer(1, 6 * mm))
    elems.append(_table(rendered["rows"], col_widths=[35 * mm, 45 * mm, 35 * mm, 45 * mm]))
    elems.append(Spacer(1, 6 * mm))
    elems.append(_table(rendered["totals"], col_widths=[80 * mm, 80 * mm]))
    doc.build(elems)
    return buf.getvalue()


def agency_summary_to_pdf(summary: list[dict], lang: str | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=i18n.label("summary_doc", lang))
    elems = [Paragraph(i18n.label("summary_title", lang), _title_style()), Spacer(1, 6 * mm)]
    data = [[i18n.label("agent_id", lang), i18n.label("code", lang), i18n.label("name", lang),
             i18n.label("level", lang), i18n.label("total", lang)]]
    for r in summary:
        data.append([str(r["agent_id"]), r["code"], r["name"],
                     f'L{r["level"]}', f'{r["total"]:,.2f}'])
    elems.append(_table(data, col_widths=[25 * mm, 30 * mm, 60 * mm, 20 * mm, 40 * mm]))
    doc.build(elems)
    return buf.getvalue()
