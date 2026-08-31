"""Anthropic Claude wrapper for the AI knowledge base.

Configured from the environment (same pattern as the mailer):
  ANTHROPIC_API_KEY   — required to enable the AI assistant
  ANTHROPIC_MODEL     — model id (default: claude-sonnet-5)

When the key is absent, `ai_enabled()` is False and the /kb/ask endpoint tells
the user the assistant isn't configured (browse/search still work). The answer
is grounded in the supplied knowledge-base context; the model is told to say so
when the context doesn't cover the question, and to avoid personalised financial
or medical advice.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("kb_ai")

DEFAULT_MODEL = "claude-sonnet-5"
_MAX_TOKENS = 1024

_SYSTEM = (
    "You are the FOA 家辦代理系統 knowledge-base assistant for insurance agents. "
    "Answer the agent's question using ONLY the numbered sources in the context "
    "below. Cite the sources you used by their number like [1], [2]. If the answer "
    "is not in the sources, say you couldn't find it in the knowledge base and "
    "suggest who to ask — do not invent facts. Reply in the same language as the "
    "question (default Traditional Chinese). Be concise. Do not give personalised "
    "financial, tax, or medical advice; keep to factual product/company knowledge."
)


class KbAiError(RuntimeError):
    """Raised when the assistant can't run (no key) or the API call fails."""


def ai_enabled() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _format_context(chunks) -> str:
    lines = []
    for i, c in enumerate(chunks, start=1):
        lines.append(f"[{i}] ({c.source_type}) {c.title}\n{c.text}")
    return "\n\n".join(lines) if lines else "(no matching knowledge-base entries)"


def answer(question: str, history: list[dict] | None, chunks) -> dict:
    """Return {"text": str, "sources": [{n,title,source_type,link,ref_id}]}.

    `history` is a list of prior turns [{role: "user"|"assistant", content: str}].
    Raises KbAiError when the assistant is unavailable.
    """
    if not ai_enabled():
        raise KbAiError("AI assistant is not configured (ANTHROPIC_API_KEY missing).")
    try:
        import anthropic
    except Exception as e:  # pragma: no cover - import guard
        raise KbAiError(f"anthropic SDK unavailable: {e}")

    model = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    messages: list[dict] = []
    for turn in (history or [])[-6:]:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        content = (turn.get("content") or "").strip()
        if content:
            messages.append({"role": role, "content": content})
    context = _format_context(chunks)
    messages.append({"role": "user",
                     "content": f"Knowledge-base context:\n{context}\n\nQuestion: {question}"})

    try:
        resp = client.messages.create(
            model=model, max_tokens=_MAX_TOKENS, system=_SYSTEM, messages=messages)
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
    except Exception as e:
        log.exception("Anthropic call failed")
        raise KbAiError(f"AI request failed: {e}")

    sources = [{"n": i, "title": c.title, "source_type": c.source_type,
                "link": c.link, "ref_id": c.ref_id} for i, c in enumerate(chunks, start=1)]
    return {"text": text or "（沒有回覆）", "sources": sources}
