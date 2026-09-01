"""Simplified → HK Traditional conversion used to normalise admin input on save."""
from app.services.zh_convert import to_traditional, convert_in


def test_simplified_to_traditional():
    assert to_traditional("香港分红险") == "香港分紅險"
    assert to_traditional("产品优势与网络") == "產品優勢與網絡"


def test_non_chinese_unchanged():
    assert to_traditional("AIA Global Felix 2") == "AIA Global Felix 2"
    assert to_traditional("INS-AIA-001") == "INS-AIA-001"


def test_already_traditional_is_noop():
    assert to_traditional("香港分紅險") == "香港分紅險"


def test_html_tags_preserved():
    # Chinese text nodes convert; tags / attributes / ASCII stay intact.
    out = to_traditional('<p class="x">红险</p><img src="data:image/png;base64,AAAA">')
    assert out == '<p class="x">紅險</p><img src="data:image/png;base64,AAAA">'


def test_empty_and_none_pass_through():
    assert to_traditional(None) is None
    assert to_traditional("") == ""


def test_convert_in_only_listed_string_keys():
    d = {"name": "红险", "code": "X-1", "count": 5}
    convert_in(d, "name", "code", "missing")
    assert d["name"] == "紅險"      # converted
    assert d["code"] == "X-1"       # ASCII untouched
    assert d["count"] == 5          # non-str untouched
