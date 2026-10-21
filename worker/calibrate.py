"""
Capture the button/label images (templates) the flow clicks on.

For each template it asks you to hover the mouse over the TOP-LEFT corner of the
element and press Enter, then the BOTTOM-RIGHT corner and press Enter. The region
is saved to templates/<name>.png.

  python calibrate.py              # capture every template the flow needs that's missing
  python calibrate.py jianyishu    # (re)capture specific templates
  python calibrate.py --all        # recapture everything

Tips: keep Windows display scaling at 100% and the WeChat window at the same size
you'll run it at. Capture a tight crop of distinctive text/icons, not blank space.
"""
from __future__ import annotations

import re
import sys

import pyautogui

from wechat_flow import TEMPLATES, load_steps

# Values the placeholder templates can take; add more terms if you sell them.
EXPAND = {
    "gender": ["M", "F"],
    "currency": ["USD", "HKD", "RMB"],
    "term_years": ["1", "2", "3", "5", "10"],
}


def needed() -> list[str]:
    names: list[str] = []
    for step in load_steps():
        t = step.get("template")
        if not t:
            continue
        m = re.search(r"\{(\w+)\}", t)
        variants = [t.replace(m.group(0), v) for v in EXPAND.get(m.group(1), [])] if m else [t]
        for v in variants:
            if v not in names:
                names.append(v)
    return names


def capture(name: str) -> None:
    input(f"\n[{name}] hover the TOP-LEFT corner, then press Enter… ")
    x1, y1 = pyautogui.position()
    input(f"[{name}] hover the BOTTOM-RIGHT corner, then press Enter… ")
    x2, y2 = pyautogui.position()
    left, top = min(x1, x2), min(y1, y2)
    w, h = abs(x2 - x1), abs(y2 - y1)
    if w < 8 or h < 8:
        print("  too small, skipped — try again")
        return
    TEMPLATES.mkdir(exist_ok=True)
    pyautogui.screenshot(region=(left, top, w, h)).save(TEMPLATES / f"{name}.png")
    print(f"  saved templates/{name}.png ({w}×{h})")


def main() -> None:
    args = sys.argv[1:]
    all_names = needed()
    if "--all" in args:
        todo = all_names
    elif args:
        todo = args
    else:
        todo = [n for n in all_names if not (TEMPLATES / f"{n}.png").exists()]
    if not todo:
        print("All templates captured. Use --all to recapture, or name specific ones.")
        return
    print("Templates to capture:", ", ".join(todo))
    print("Optional ones you don't have on screen (e.g. a term you don't sell): press Ctrl+C to stop "
          "and rerun later with just the names you need.")
    for name in todo:
        capture(name)


if __name__ == "__main__":
    main()
