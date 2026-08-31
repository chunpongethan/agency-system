"""Knowledge-base retrieval: assemble a text corpus from the four sources and
rank chunks against a query with a simple keyword / CJK-bigram scorer.

No embeddings — the corpus is modest, so ranked chunks fit Claude's context.
Kept free of any dependency on app.main to avoid import cycles.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import (
    KbArticle, KbDocument, TrainingMaterial, TrainingFile, Product, ProductRate,
)

# Web links (hash routes) back into the app for each source.
_LINK = {
    "article": "#/knowledge-base",
    "document": "#/knowledge-base",
    "training": "#/training",
    "product": "#/products",
}

_MAX_DOC_PAGES = 20          # cap PDF text extraction
_CHUNK_CHARS = 900           # split long texts into ~paragraph chunks
_DEFAULT_BUDGET = 24000      # total context chars fed to the model


@dataclass
class Chunk:
    source_type: str         # article | document | training | product
    ref_id: int
    title: str
    link: str
    text: str


# --- text helpers ------------------------------------------------------------
class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    p = _Stripper()
    try:
        p.feed(html)
        p.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"[ \t]+", " ", "".join(p.parts)).strip()


def pdf_to_text(data: bytes) -> str:
    """Extract text from a PDF byte string via PyMuPDF (best-effort)."""
    try:
        try:
            import pymupdf as fitz
        except Exception:
            import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        out = []
        for i, page in enumerate(doc):
            if i >= _MAX_DOC_PAGES:
                break
            out.append(page.get_text())
        return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    except Exception:
        return ""


def _split(text: str, size: int = _CHUNK_CHARS) -> list[str]:
    text = (text or "").strip()
    if len(text) <= size:
        return [text] if text else []
    out, buf = [], []
    n = 0
    for para in re.split(r"\n{2,}", text):
        if n + len(para) > size and buf:
            out.append("\n".join(buf)); buf, n = [], 0
        buf.append(para); n += len(para) + 2
    if buf:
        out.append("\n".join(buf))
    return [c for c in out if c.strip()]


# --- tokenisation / scoring --------------------------------------------------
def _terms(s: str) -> set[str]:
    s = (s or "").lower()
    words = set(re.findall(r"[a-z0-9]{2,}", s))
    cjk = re.findall(r"[一-鿿]", s)
    bigrams = {cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)}
    return words | bigrams | set(cjk)


# --- corpus ------------------------------------------------------------------
def _product_text(p: Product, pr: ProductRate | None) -> str:
    ptype = getattr(p.type, "value", p.type)
    bits = [f"{p.name} ({p.code})", f"類型 type: {ptype}"]
    if p.provider:
        bits.append(f"供應商 provider: {p.provider}")
    if pr is not None:
        try:
            bits.append(f"基本佣金 base rate: {float(pr.base_commission_rate) * 100:.2f}%")
            if pr.year_commissions:
                yrs = " / ".join(f"Y{i+1} {float(x)*100:.2f}%" for i, x in enumerate(pr.year_commissions))
                bits.append(f"各年佣金 yearly: {yrs}")
        except Exception:
            pass
    if p.payment_tenor:
        bits.append(f"供款年期 tenor: {p.payment_tenor}")
    return " · ".join(bits)


def build_corpus(db: Session, *, company: str, is_admin: bool) -> list[Chunk]:
    """Gather retrievable chunks from articles, documents, (company-visible)
    training materials, and products. Lazily extracts + caches training-file and
    document text as a side effect (committed once)."""
    chunks: list[Chunk] = []
    dirty = False

    # KB articles (shared)
    for a in db.execute(select(KbArticle).where(KbArticle.is_active == True)).scalars():  # noqa: E712
        body = html_to_text(a.body)
        for i, part in enumerate(_split(f"{a.title}\n{body}")):
            chunks.append(Chunk("article", a.id, a.title, _LINK["article"], part))
        if not body:
            chunks.append(Chunk("article", a.id, a.title, _LINK["article"], a.title))

    # KB documents (shared) — extract+cache text on first use
    for d in db.execute(select(KbDocument)).scalars():
        if d.extracted_text is None:
            d.extracted_text = pdf_to_text(d.data) if (d.content_type or "").lower() == "application/pdf" else ""
            dirty = True
        text = f"{d.title}\n{d.extracted_text or ''}"
        for part in _split(text):
            chunks.append(Chunk("document", d.id, d.title, _LINK["document"], part))

    # Training materials — respect per-company visibility
    for m in db.execute(select(TrainingMaterial)).scalars():
        comps = m.companies or []
        if not is_admin and comps and company not in comps:
            continue
        desc = html_to_text(m.description)
        text = f"{m.title}\n{desc}"
        # attached files: use cached/extracted text (pdf or office-preview)
        for f in db.execute(select(TrainingFile).where(TrainingFile.material_id == m.id)).scalars():
            if f.extracted_text is None:
                src = f.preview_data if f.preview_data else (f.data if (f.content_type or "").lower() == "application/pdf" else None)
                f.extracted_text = pdf_to_text(src) if src else ""
                dirty = True
            if f.extracted_text:
                text += "\n" + f.extracted_text
        for part in _split(text):
            chunks.append(Chunk("training", m.id, m.title, _LINK["training"], part))

    # Products (shared catalogue; company rate when available)
    rates = {r.product_id: r for r in db.execute(
        select(ProductRate).where(ProductRate.company == company)).scalars()}
    for p in db.execute(select(Product).where(Product.is_active == True)).scalars():  # noqa: E712
        chunks.append(Chunk("product", p.id, p.name, _LINK["product"], _product_text(p, rates.get(p.id))))

    if dirty:
        try:
            db.commit()
        except Exception:
            db.rollback()
    return chunks


def rank(chunks: list[Chunk], query: str, *, k: int = 12, budget: int = _DEFAULT_BUDGET) -> list[Chunk]:
    """Top-k chunks by term overlap with the query, capped to a char budget."""
    q = _terms(query)
    if not q:
        return []
    scored = []
    for c in chunks:
        ct = _terms(c.text)
        title_t = _terms(c.title)
        score = len(q & ct) + 2 * len(q & title_t)   # title matches weigh more
        if score:
            scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    out, used = [], 0
    for _, c in scored:
        if len(out) >= k or used + len(c.text) > budget:
            continue
        out.append(c); used += len(c.text)
    return out


def snippet(text: str, query: str, width: int = 180) -> str:
    """A short excerpt around the first query-term hit (for search results)."""
    terms = [t for t in _terms(query) if len(t) >= 2]
    low = text.lower()
    pos = min((low.find(t) for t in terms if t in low), default=-1)
    if pos < 0:
        return text[:width].strip()
    start = max(0, pos - width // 3)
    return ("…" if start else "") + text[start:start + width].strip() + ("…" if start + width < len(text) else "")
