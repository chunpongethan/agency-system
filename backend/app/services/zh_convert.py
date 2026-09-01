"""Normalise admin-entered text to Hong Kong Traditional Chinese before saving.

Deterministic Simplified→Traditional character conversion via OpenCC (config
`s2hk`). English, numbers, codes and punctuation pass through unchanged, and
already-Traditional text is a no-op, so it's safe to run on any field. OpenCC
only maps Chinese codepoints, so it may also be run on a sanitised HTML string
(tags / ASCII / base64 data-URLs are left intact).

Best-effort: if the converter can't be loaded it returns the input unchanged, so
saves never fail because of this.
"""
from __future__ import annotations

import logging

log = logging.getLogger("zh_convert")

_converter = None
_loaded = False


def _get_converter():
    global _converter, _loaded
    if not _loaded:
        _loaded = True
        try:
            import opencc
            _converter = opencc.OpenCC("s2hk")
        except Exception as e:  # pragma: no cover - only when the lib is missing
            log.warning("OpenCC unavailable — text not converted: %s", e)
            _converter = None
    return _converter


def to_traditional(text: str | None) -> str | None:
    """Convert Simplified → HK Traditional. None/empty and non-str pass through."""
    if not text or not isinstance(text, str):
        return text
    conv = _get_converter()
    if conv is None:
        return text
    try:
        return conv.convert(text)
    except Exception:  # pragma: no cover - defensive
        return text


def convert_in(data: dict, *keys: str) -> None:
    """Convert the given string keys of `data` in place (skips missing/empty)."""
    for k in keys:
        v = data.get(k)
        if isinstance(v, str) and v:
            data[k] = to_traditional(v)
