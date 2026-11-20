"""
Publish a 問答特訓 HTML page to the web app (frontend/public/training/<slug>.html).

Prepares the page as delivered:
  * adds <meta name="robots" content="noindex, nofollow">
  * loads training/tracker.js, which asks the learner's name once and reports
    progress to FOA (admin page 問答特訓紀錄)
  * hooks the page's engine: chapter opened, chapter finished, 结业测验 score

Idempotent: re-running it on an already-published page changes nothing. It fails loudly if
the engine has changed and a hook point can't be found. Then check the page in a browser.

Usage:
    python scripts/publish_training_page.py "C:/Users/me/Downloads/crs-tax-qa.html"
    python scripts/publish_training_page.py <file.html> --slug new-name     # choose the URL name
    python scripts/publish_training_page.py --all                            # re-process published pages
"""
from __future__ import annotations

import argparse
import os
import re
import sys

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "training")

VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1">'
ROBOTS = '<meta name="robots" content="noindex, nofollow">'
TRACKER = '<script src="tracker.js"></script>'

# (marker that shows the hook is in, text to find, replacement)
HOOKS = [
    ('HTQA.log("finish"',
     "function markDone(mid){ if(done[mid]) return; done[mid]=true;",
     'function markDone(mid){ if(done[mid]) return; done[mid]=true; '
     'if(window.HTQA) HTQA.log("finish",mod(mid));'),
    ("HTQA.open(",
     'var f=FLOW[pos], m=mod(f.m), stage=$("stage");',
     'var f=FLOW[pos], m=mod(f.m), stage=$("stage"); if(window.HTQA) HTQA.open(m);'),
    ('HTQA.log("exam"',
     "result.hidden=false;",
     'if(window.HTQA) HTQA.log("exam",null,right,pick.length); result.hidden=false;'),
]


def prepare(html: str) -> str:
    if ROBOTS not in html:
        if VIEWPORT not in html:
            raise ValueError("no viewport <meta> to anchor the robots tag")
        html = html.replace(VIEWPORT, VIEWPORT + "\n" + ROBOTS, 1)
    if TRACKER not in html:
        html = html.replace(ROBOTS, ROBOTS + "\n" + TRACKER, 1)
    for marker, find, repl in HOOKS:
        if marker in html:
            continue
        n = html.count(find)
        if n != 1:
            raise ValueError(f"hook point found {n} times (expected 1): {find}")
        html = html.replace(find, repl, 1)
    return html


def publish(src: str, slug: str | None) -> str:
    slug = slug or os.path.splitext(os.path.basename(src))[0]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", slug):
        raise ValueError(f"URL name must be lowercase letters, digits and dashes: {slug!r} (use --slug)")
    with open(src, encoding="utf-8") as fh:
        html = prepare(fh.read())
    dest = os.path.join(OUT_DIR, slug + ".html")
    with open(dest, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    return slug


def main() -> int:
    p = argparse.ArgumentParser(description="Publish a 問答特訓 page to /training/.")
    p.add_argument("file", nargs="?", help="the page's HTML file")
    p.add_argument("--slug", help="URL name (default: the file name)")
    p.add_argument("--all", action="store_true", help="re-process every published page")
    a = p.parse_args()
    srcs = ([os.path.join(OUT_DIR, f) for f in sorted(os.listdir(OUT_DIR)) if f.endswith(".html")]
            if a.all else [a.file] if a.file else [])
    if not srcs:
        p.error("give a file or --all")
    for src in srcs:
        slug = publish(src, None if a.all else a.slug)
        print(f"published /training/{slug}.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
