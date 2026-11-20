"""
Publish an H5 视频课 folder to the web app (frontend/public/training/<slug>/).

A video course is a folder: index.html, scenes.js, video-data.js, logo.png, audio/*.mp3.
This script copies it in (when given a source folder) and prepares index.html:
  * adds <meta name="robots" content="noindex, nofollow">
  * loads ../tracker.js (shared with the 問答特訓 pages: asks the learner's name once and
    reports progress to FOA, admin page 問答特訓紀錄)
  * hooks the player:
      - counts the seconds of each chapter actually played (fast-forwarding doesn't count)
      - chapter started  -> HTQA.open(chapter)
      - chapter finished -> marked 已完成 and HTQA.log("finish", chapter), but only if
        at least 80% of the chapter was actually played; otherwise the quiz header says so
      - a chapter quiz fully answered -> HTQA.log("quiz", chapter, right, total)

Idempotent: re-running it on an already-published folder changes nothing. It fails loudly if
the player has changed and a hook point can't be found. Then check the page in a browser.

Usage:
    python scripts/publish_training_video.py "C:/Users/me/Downloads/crs-video"      # copy + prepare
    python scripts/publish_training_video.py <folder> --slug new-name               # choose the URL name
    python scripts/publish_training_video.py --all                                   # re-process published videos
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "training")

VIEWPORT_RE = re.compile(r'<meta name="viewport"[^>]*>')
ROBOTS = '<meta name="robots" content="noindex, nofollow">'
TRACKER = '<script src="../tracker.js"></script>'
WATCH_SHARE = 0.8   # share of a chapter that must actually be played to count as 已完成

# (marker that shows the hook is in, text to find, replacement)
HOOKS = [
    # chapter helpers + module list for the tracker (module_total)
    ("function chMod(",
     'var KEY="',
     'function chMod(ci){ var c=CH[ci]; return {id:"ch"+c.n, name:"第"+c.n+"章 · "+c.title}; }\n'
     '  window.MODULES=CH.map(function(c,ci){ return chMod(ci); });\n'
     '  var KEY="'),
    # count real play time per chapter (content seconds; capped so a sleeping tab doesn't count)
    ("prog.w[wk]",
     "var dt=last?(now-last)/1000:0; last=now;",
     "var dt=last?(now-last)/1000:0; last=now;\n"
     "    if(st.playing && dt>0 && dt<1.5 && CH[st.ch]){ var wk=CH[st.ch].n; prog.w=prog.w||{}; "
     "prog.w[wk]=(prog.w[wk]||0)+dt*st.rate; }"),
    # chapter started
    ("HTQA.open(",
     '$("cttl").textContent="第 "+CH[ci].n+" 章 · "+CH[ci].title;',
     '$("cttl").textContent="第 "+CH[ci].n+" 章 · "+CH[ci].title; if(window.HTQA) HTQA.open(chMod(ci));'),
    # chapter finished: only when watched; reset the counter for the next viewing
    ('HTQA.log("finish"',
     "var c=CH[st.ch]; prog.done[c.n]=true;",
     "var c=CH[st.ch], full=((prog.w||{})[c.n]||0)>=" + str(WATCH_SHARE) + "*total;"
     ' if(full){ prog.done[c.n]=true; if(window.HTQA) HTQA.log("finish",chMod(st.ch)); }'
     " if(prog.w) prog.w[c.n]=0;"),
    ("未完整观看",
     '$("qh").textContent="本章小测";',
     '$("qh").textContent= full ? "本章小测" : "本章小测 · 未完整观看，本章暂不计完成";'),
    # quiz result once every question in the chapter quiz is answered
    ('HTQA.log("quiz"',
     'var x=document.createElement("div"); x.className="qx";',
     'qAns++; if(oi===it.a) qRight++; if(qAns===(Q[c.n]||[]).length && window.HTQA) '
     'HTQA.log("quiz",chMod(st.ch),qRight,qAns);\n'
     '          var x=document.createElement("div"); x.className="qx";'),
    ("var qAns=0",
     'var ql=$("qlist"); ql.innerHTML="";',
     'var ql=$("qlist"); ql.innerHTML=""; var qAns=0, qRight=0;'),
    # save the watch counter when the page is left mid-chapter
    ('addEventListener("pagehide"',
     "prep(prog.ch||0); openCover();",
     'window.addEventListener("pagehide",function(){ try{ localStorage.setItem(KEY,JSON.stringify(prog)); }catch(e){} });\n'
     "  prep(prog.ch||0); openCover();"),
    # where the tracker shows 「学员：…」
    ('id="htqa-anchor"',
     '<button class="btn" id="bstart" type="button">开始观看</button>',
     '<button class="btn" id="bstart" type="button">开始观看</button>\n    <div id="htqa-anchor"></div>'),
]


def prepare(html: str) -> str:
    if ROBOTS not in html:
        m = VIEWPORT_RE.search(html)
        if not m:
            raise ValueError("no viewport <meta> to anchor the robots tag")
        html = html[:m.end()] + "\n" + ROBOTS + html[m.end():]
    if TRACKER not in html:
        anchor = '<script src="scenes.js"></script>'
        if html.count(anchor) != 1:
            raise ValueError("can't find where to load tracker.js")
        html = html.replace(anchor, TRACKER + "\n" + anchor, 1)
    for marker, find, repl in HOOKS:
        if marker in html:
            continue
        n = html.count(find)
        if n != 1:
            raise ValueError(f"hook point found {n} times (expected 1): {find}")
        html = html.replace(find, repl, 1)
    return html


def publish_dir(folder: str) -> None:
    path = os.path.join(folder, "index.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    out = prepare(html)
    if out != html:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(out)
    print("published /training/" + os.path.basename(os.path.normpath(folder)) + "/")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", nargs="?", help="video course folder to publish")
    ap.add_argument("--slug", help="URL name (default: the folder name)")
    ap.add_argument("--all", action="store_true", help="re-process every published video folder")
    a = ap.parse_args()
    out_dir = os.path.abspath(OUT_DIR)
    if a.all:
        dirs = sorted(d for d in os.listdir(out_dir)
                      if os.path.isfile(os.path.join(out_dir, d, "index.html"))
                      and os.path.isfile(os.path.join(out_dir, d, "video-data.js")))
        for d in dirs:
            publish_dir(os.path.join(out_dir, d))
        return 0
    if not a.src:
        ap.error("give a folder or --all")
    src = os.path.abspath(a.src)
    slug = (a.slug or os.path.basename(src)).lower()
    if not re.match(r"^[a-z0-9][a-z0-9-]{0,79}$", slug):
        ap.error("slug must be lowercase letters, digits and dashes")
    dst = os.path.join(out_dir, slug)
    if src != dst:
        shutil.copytree(src, dst, dirs_exist_ok=True)
    publish_dir(dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
