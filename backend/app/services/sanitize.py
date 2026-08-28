"""Minimal allowlist HTML sanitiser for admin-authored rich-text remarks.

Only formatting tags survive; scripts/styles and their content are dropped, and
event-handler / javascript: URLs are stripped. Rendered to agents via the
frontend, so this is the trust boundary — keep the allowlist tight.
"""
from __future__ import annotations

from html import escape
from html.parser import HTMLParser

_ALLOWED_TAGS = {
    "p", "br", "b", "strong", "i", "em", "u", "s", "strike",
    "ul", "ol", "li", "a", "h3", "h4", "blockquote", "span", "div",
}
_VOID = {"br"}
_SKIP_CONTENT = {"script", "style"}      # drop these tags AND their text
_ALLOWED_ATTRS = {"a": {"href", "title"}}


def _safe_href(v: str | None) -> bool:
    s = (v or "").strip().lower()
    return not s.startswith(("javascript:", "data:", "vbscript:"))


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_CONTENT:
            self.skip += 1
            return
        if tag not in _ALLOWED_TAGS:
            return
        allowed = _ALLOWED_ATTRS.get(tag, set())
        kept = [(k.lower(), v) for k, v in attrs if k.lower() in allowed]
        if tag == "a":
            kept = [(k, v) for k, v in kept if k != "href" or _safe_href(v)]
            kept += [("target", "_blank"), ("rel", "noopener noreferrer")]
        attr_str = "".join(f' {k}="{escape(v or "", quote=True)}"' for k, v in kept)
        self.out.append(f"<{tag}{attr_str}>")

    def handle_startendtag(self, tag, attrs):
        if tag in _ALLOWED_TAGS and tag in _VOID:
            self.out.append(f"<{tag}/>")

    def handle_endtag(self, tag):
        if tag in _SKIP_CONTENT:
            if self.skip:
                self.skip -= 1
            return
        if tag in _ALLOWED_TAGS and tag not in _VOID:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data))


def sanitize_html(html: str | None) -> str | None:
    """Return `html` with only the allowlisted tags/attributes; None/empty pass
    through unchanged."""
    if not html:
        return html
    p = _Sanitizer()
    p.feed(html)
    p.close()
    return "".join(p.out)
