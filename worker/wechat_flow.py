"""
Runs the 保易通助手 建議書 flow described in flow.toml against the WeChat PC client.

Controls are found by screen template matching (templates/*.png), because the
mini-program is a Chromium webview that exposes little to Windows UI Automation.
Raises FlowError (with the failing step) on any problem; the caller screenshots
the screen and reports the failure to FOA.
"""
from __future__ import annotations

import re
import time
try:
    import tomllib
except ModuleNotFoundError:          # Python < 3.11
    import tomli as tomllib
from pathlib import Path

import pyautogui
import pyperclip

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
pyautogui.FAILSAFE = True          # slam the mouse into a screen corner to abort
pyautogui.PAUSE = 0.25


class FlowError(RuntimeError):
    pass


def _fill(value: str, job: dict) -> str:
    gender_label = "男" if job.get("gender") == "M" else "女"
    premium = job.get("premium")
    if isinstance(premium, float) and premium.is_integer():
        premium = int(premium)
    values = {**job, "premium": premium, "gender_label": gender_label}
    return value.format(**{k: v for k, v in values.items()})


def load_steps() -> list[dict]:
    with open(HERE / "flow.toml", "rb") as f:
        return tomllib.load(f).get("step", [])


def _locate(template: str, confidence: float, timeout: float):
    path = TEMPLATES / f"{template}.png"
    if not path.exists():
        raise FlowError(f"missing template image {path.name} — run calibrate.py")
    deadline = time.time() + timeout
    while True:
        try:
            box = pyautogui.locateOnScreen(str(path), confidence=confidence, grayscale=True)
        except pyautogui.ImageNotFoundException:
            box = None
        if box:
            return box
        if time.time() > deadline:
            return None
        time.sleep(0.5)


def _focus(title_regex: str) -> None:
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
            return
    raise FlowError(f"no window matching /{title_regex}/ — is WeChat open with 保易通助手?")


def _newest_pdf(folder: Path, since: float) -> Path | None:
    pdfs = [p for p in folder.glob("*.pdf") if p.stat().st_mtime >= since]
    return max(pdfs, key=lambda p: p.stat().st_mtime) if pdfs else None


def run(job: dict, cfg: dict, log=print) -> Path:
    """Execute the flow for one job's inputs; return the downloaded PDF path."""
    downloads = Path(cfg["downloads_dir"])
    confidence = float(cfg.get("match_confidence", 0.85))
    started = time.time()

    for n, step in enumerate(load_steps(), start=1):
        action = step.get("action")
        timeout = float(step.get("timeout", 15))
        label = f"step {n} ({action} {step.get('template') or step.get('text') or ''})".strip()
        log(label)
        try:
            if action == "focus":
                _focus(step["title"])
            elif action in ("click", "wait_for"):
                template = _fill(step["template"], job)
                box = _locate(template, confidence, timeout)
                if box is None:
                    if step.get("optional"):
                        log(f"  skipped (optional, {template} not found)")
                        continue
                    raise FlowError(f"{template} not found on screen")
                if action == "click":
                    dx, dy = step.get("offset", [0, 0])
                    x, y = pyautogui.center(box)
                    pyautogui.click(x + dx, y + dy)
                    time.sleep(float(step.get("after", 0.6)))
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
            elif action == "wait_download":
                limit = time.time() + float(cfg.get("download_timeout", 120))
                while time.time() < limit:
                    pdf = _newest_pdf(downloads, started)
                    # wait until the file stops growing (download finished)
                    if pdf and not pdf.name.endswith(".crdownload"):
                        size = pdf.stat().st_size
                        time.sleep(1.5)
                        if pdf.exists() and pdf.stat().st_size == size and size > 0:
                            return pdf
                    time.sleep(1)
                raise FlowError(f"no new PDF appeared in {downloads}")
            else:
                raise FlowError(f"unknown action {action!r}")
        except FlowError as e:
            raise FlowError(f"{label}: {e}") from None
        except pyautogui.FailSafeException:
            raise FlowError(f"{label}: aborted by moving the mouse to a screen corner") from None
        except Exception as e:
            raise FlowError(f"{label}: {type(e).__name__}: {e}") from None

    raise FlowError("flow ended without a wait_download step")
