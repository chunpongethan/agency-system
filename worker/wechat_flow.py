"""
Runs the 保易通助手 建議書 flow described in flow.toml against the WeChat PC client.

Controls are found by screen template matching (templates/*.png), because the
mini-program is a Chromium webview that exposes little to Windows UI Automation.
Positions that can't be templated (the newest card in a list, a field's input
area) are given relative to the focused mini-program window. Raises FlowError
(with the failing step) on any problem; the caller screenshots and reports it.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:          # Python < 3.11
    import tomli as tomllib

import pyautogui
import pyperclip
import requests

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
pyautogui.FAILSAFE = True          # slam the mouse into a screen corner to abort
pyautogui.PAUSE = 0.25

_window = None                     # the window the last `focus` step brought forward


class FlowError(RuntimeError):
    pass


def _simplified(text: str) -> str:
    try:
        from opencc import OpenCC
        return OpenCC("t2s").convert(text)
    except Exception:
        return text


def _job_values(job: dict) -> dict:
    premium = job.get("premium")
    if isinstance(premium, float) and premium.is_integer():
        premium = int(premium)
    product = str(job.get("product") or "")
    simp = _simplified(product)
    # 保易通 lists products in Simplified Chinese with spaces around the "·"; search
    # on the leading name only (e.g. 「飛揚·88」→ 飞扬) and click the first result.
    search = re.split(r"[\s·・•.\-－—「」『』（）()]+", simp.strip(" 「」『』"))
    search = next((s for s in search if s), simp)
    return {**job, "premium": premium, "product_simplified": simp, "product_search": search,
            "gender_label": "男" if job.get("gender") == "M" else "女"}


def _fill(value: str, job: dict) -> str:
    return value.format(**_job_values(job))


def load_steps() -> list[dict]:
    with open(HERE / "flow.toml", "rb") as f:
        return tomllib.load(f).get("step", [])


def _locate(template: str, confidence: float, timeout: float, within=None):
    """Find a template on screen; `within` = [x1, y1, x2, y2] relative to the focused
    window limits the search (e.g. to a picker sheet, so a same-looking label
    elsewhere on the page isn't matched)."""
    path = TEMPLATES / f"{template}.png"
    if not path.exists():
        raise FlowError(f"missing template image {path.name} — capture it with calibrate.py")
    region = None
    if within:
        x1, y1 = _win_point(within[:2])
        x2, y2 = _win_point(within[2:])
        region = (x1, y1, x2 - x1, y2 - y1)
    deadline = time.time() + timeout
    while True:
        try:
            box = pyautogui.locateOnScreen(str(path), confidence=confidence, grayscale=True,
                                           region=region)
        except pyautogui.ImageNotFoundException:
            box = None
        if box:
            return box
        if time.time() > deadline:
            return None
        time.sleep(0.5)


def _focus(title_regex: str) -> None:
    global _window
    from pywinauto import Desktop
    pattern = re.compile(title_regex)
    for w in Desktop(backend="uia").windows():
        try:
            title = w.window_text()
        except Exception:
            continue
        if title and pattern.search(title):
            if w.is_minimized():
                w.restore()
            w.set_focus()
            time.sleep(0.5)
            _window = w
            return
    raise FlowError(f"no window matching /{title_regex}/ — is WeChat open with 保易通助手?")


def _win_point(xy) -> tuple[int, int]:
    if _window is None:
        raise FlowError("no focused window (add a focus step first)")
    r = _window.rectangle()
    return r.left + int(xy[0]), r.top + int(xy[1])


def _win_shot():
    r = _window.rectangle()
    return pyautogui.screenshot(region=(r.left, r.top, r.width(), r.height()))


def _pdf_via_browser(url: str, timeout: float = 90) -> bytes:
    """Open the share link in a headless phone-sized browser, as a client would, and
    keep the PDF that 保易通's web viewer downloads in order to display it."""
    from playwright.sync_api import sync_playwright

    found: list[bytes] = []

    def on_response(resp):
        if found:
            return
        ctype = (resp.headers.get("content-type") or "").lower()
        if "pdf" in ctype or "octet-stream" in ctype:
            try:
                body = resp.body()
            except Exception:
                return
            if body.startswith(b"%PDF"):
                found.append(body)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True,
                                      accept_downloads=True)
            page = ctx.new_page()
            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            deadline = time.time() + timeout
            retried = 0
            while not found and time.time() < deadline:
                page.wait_for_timeout(1000)
                # The viewer sometimes shows 文件加载失败 + 重新加载 on first load.
                retry = page.get_by_text("重新加载")
                if retried < 3 and retry.count() and retry.first.is_visible():
                    retry.first.click()
                    retried += 1
        finally:
            browser.close()
    if not found:
        raise FlowError("the share link's viewer never loaded a PDF")
    return found[0]


def _download(url: str, folder: Path, name: str | None = None) -> Path:
    if not re.match(r"^https?://", url or ""):
        raise FlowError(f"clipboard doesn't hold a download link: {url[:80]!r}")
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    data = resp.content
    if not data.startswith(b"%PDF"):
        # 复制下载链接 points at 保易通's web viewer page, not the file itself.
        data = _pdf_via_browser(url)
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name or "").strip()
    if not safe.lower().endswith(".pdf"):
        safe = f"proposal-{time.strftime('%Y%m%d-%H%M%S')}.pdf"
    path = folder / safe
    path.write_bytes(data)
    return path


def run(job: dict, cfg: dict, log=print) -> Path:
    """Execute the flow for one job's inputs; return the downloaded PDF path."""
    downloads = Path(cfg["downloads_dir"])
    confidence = float(cfg.get("match_confidence", 0.85))

    for n, step in enumerate(load_steps(), start=1):
        action = step.get("action")
        timeout = float(step.get("timeout", 15))
        label = f"step {n} ({action} {step.get('template') or step.get('text') or step.get('note') or ''})".strip()
        log(label)
        try:
            if action == "focus":
                _focus(step["title"])
            elif action in ("click", "wait_for"):
                template = _fill(step["template"], job)
                box = _locate(template, confidence, timeout, step.get("within"))
                if box is None:
                    if step.get("optional"):
                        log(f"  skipped (optional, {template} not found)")
                        continue
                    raise FlowError(f"{template} not found on screen")
                if action == "click":
                    dx, dy = step.get("offset", [0, 0])
                    x, y = pyautogui.center(box)
                    pyautogui.click(x + dx, y + dy)
            elif action == "back_until":
                # Leave whatever page the last run ended on: press back until one of
                # the target templates is visible (or give up after `max` presses).
                targets = step["until"]
                for _ in range(int(step.get("max", 8)) + 1):
                    if any(_locate(t, confidence, 1.5) for t in targets):
                        break
                    back = _locate(step["back_template"], confidence, 2)
                    if back is None:
                        break
                    pyautogui.click(*pyautogui.center(back))
                    time.sleep(float(step.get("pause", 2.5)))
            elif action == "click_at":
                pyautogui.click(*_win_point(step["at"]))
            elif action == "scroll":
                pyautogui.moveTo(*_win_point(step.get("at", [260, 600])))
                pyautogui.scroll(int(step.get("amount", -5)) * 120)
            elif action == "paste":
                pyperclip.copy(_fill(step["text"], job))
                pyautogui.hotkey("ctrl", "v")
            elif action == "type":
                pyautogui.write(_fill(step["text"], job), interval=0.05)
            elif action == "clear":
                pyautogui.hotkey("ctrl", "a")
                pyautogui.press("backspace")
            elif action == "key":
                pyautogui.press(step["key"])
            elif action == "wait":
                time.sleep(float(step.get("seconds", 1)))
            elif action == "wait_ready":
                # Generation is asynchronous: keep re-opening the list (refresh clicks)
                # until the pending badge is no longer on the newest (top) card.
                # Either wait for ready_template to appear, or for pending_template to
                # leave the top of the window (max_y), refreshing between checks.
                want = step.get("ready_template") or step["pending_template"]
                tpl = TEMPLATES / f"{want}.png"
                max_y = int(step.get("max_y", 100000))
                limit = time.time() + float(step.get("timeout", 900))
                while True:
                    try:
                        hit = pyautogui.locate(str(tpl), _win_shot(), confidence=confidence, grayscale=True)
                    except pyautogui.ImageNotFoundException:
                        hit = None
                    present = bool(hit and hit.top < max_y)
                    if present == bool(step.get("ready_template")):
                        break
                    if time.time() > limit:
                        raise FlowError("proposal still not ready after waiting")
                    time.sleep(float(step.get("interval", 30)))
                    if step.get("refresh_scroll"):           # scroll up on the list = refresh
                        pyautogui.moveTo(*_win_point(step["refresh_scroll"]))
                        pyautogui.scroll(6 * 120)
                        time.sleep(4)
                    for xy in step.get("refresh", []):
                        pyautogui.click(*_win_point(xy))
                        time.sleep(2.5)
            elif action == "copy_link_download":
                pyperclip.copy("")
                box = _locate(step["template"], confidence, timeout)
                if box is None:
                    raise FlowError(f"{step['template']} not found on screen")
                pyautogui.click(*pyautogui.center(box))
                # The clipboard holds "<link>\n<file name>.pdf\n<summary>"; take the link.
                deadline = time.time() + 10
                url, name = "", None
                while time.time() < deadline and not url:
                    time.sleep(0.5)
                    clip = pyperclip.paste() or ""
                    m = re.search(r"https?://\S+", clip)
                    url = m.group(0) if m else ""
                    name = next((ln.strip() for ln in clip.splitlines() if ln.strip().lower().endswith(".pdf")), None)
                return _download(url, downloads, name)
            else:
                raise FlowError(f"unknown action {action!r}")
            time.sleep(float(step.get("after", 0.8)))
        except FlowError as e:
            raise FlowError(f"{label}: {e}") from None
        except pyautogui.FailSafeException:
            raise FlowError(f"{label}: aborted by moving the mouse to a screen corner") from None
        except Exception as e:
            raise FlowError(f"{label}: {type(e).__name__}: {e}") from None

    raise FlowError("flow ended without a copy_link_download step")
