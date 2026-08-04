"""
Exports: CSV and PDF for agent statements and the agency summary.

`render_statement()` produces the neutral row structure that feeds both the API
JSON, the CSV writer, and the PDF renderer, so all three stay in lockstep.
"""
from __future__ import annotations

import csv
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
)


def render_statement(statement: dict) -> dict:
    """
    Normalise an agent_statement dict into a header + rows + totals structure
    shared by every output format.
    """
    header = [
        ["Agent", f'{statement["agent"]["name"]} ({statement["agent"]["code"]})'],
        ["Level", f'L{statement["agent"]["level"]}'],
        ["Period", f'{statement["period"]["start"] or "—"} → {statement["period"]["end"] or "—"}'],
    ]
    rows = [["Kind", "Product type", "Count", "Amount"]]
    for line in statement["lines"]:
        rows.append([
            line["kind"], line["product_type"], str(line["count"]),
            f'{line["amount"]:,.2f}',
        ])
    totals = [
        ["Direct total", f'{statement["direct_total"]:,.2f}'],
        ["Override total", f'{statement["override_total"]:,.2f}'],
        ["Grand total", f'{statement["grand_total"]:,.2f}'],
    ]
    return {"header": header, "rows": rows, "totals": totals}


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #
def statement_to_csv(statement: dict) -> str:
    rendered = render_statement(statement)
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
    return buf.getvalue()


def agency_summary_to_csv(summary: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["agent_id", "code", "name", "level", "total"])
    for r in summary:
        w.writerow([r["agent_id"], r["code"], r["name"], r["level"], f'{r["total"]:,.2f}'])
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
def _table(data, col_widths=None):
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
        ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def statement_to_pdf(statement: dict) -> bytes:
    rendered = render_statement(statement)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="Agent Statement")
    styles = getSampleStyleSheet()
    elems = [Paragraph("Agent Commission Statement", styles["Title"]), Spacer(1, 6 * mm)]
    elems.append(_table(rendered["header"], col_widths=[40 * mm, 120 * mm]))
    elems.append(Spacer(1, 6 * mm))
    elems.append(_table(rendered["rows"], col_widths=[35 * mm, 45 * mm, 35 * mm, 45 * mm]))
    elems.append(Spacer(1, 6 * mm))
    elems.append(_table(rendered["totals"], col_widths=[80 * mm, 80 * mm]))
    doc.build(elems)
    return buf.getvalue()


def agency_summary_to_pdf(summary: list[dict]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="Agency Summary")
    styles = getSampleStyleSheet()
    elems = [Paragraph("Agency Commission Summary", styles["Title"]), Spacer(1, 6 * mm)]
    data = [["Agent ID", "Code", "Name", "Level", "Total"]]
    for r in summary:
        data.append([str(r["agent_id"]), r["code"], r["name"],
                     f'L{r["level"]}', f'{r["total"]:,.2f}'])
    elems.append(_table(data, col_widths=[25 * mm, 30 * mm, 60 * mm, 20 * mm, 40 * mm]))
    doc.build(elems)
    return buf.getvalue()
