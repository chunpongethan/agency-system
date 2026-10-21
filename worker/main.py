"""
FOA 建議書 worker — runs on the Windows PC that has WeChat logged in.

Loop: heartbeat → claim a queued proposal from FOA → drive 保易通助手 (wechat_flow)
→ upload the PDF, or report the failure with a screenshot. One job at a time.

Usage:
  python main.py                 # run forever
  python main.py --once          # handle at most one job, then exit
  python main.py --test          # run the flow locally with a sample job (no FOA)
  add --dry-run to skip uploading (the PDF stays in your Downloads folder)
"""
from __future__ import annotations

import argparse
import io
import threading
import time
try:
    import tomllib
except ModuleNotFoundError:          # Python < 3.11
    import tomli as tomllib
import traceback
from pathlib import Path

import pyautogui
import requests

import wechat_flow

HERE = Path(__file__).resolve().parent
VERSION = "0.1"
SAMPLE_JOB = {"age": 30, "gender": "F", "product": "飛揚·88", "premium": 50000,
              "term_years": 2, "currency": "USD"}


def load_config() -> dict:
    path = HERE / "config.toml"
    if not path.exists():
        raise SystemExit("config.toml not found — copy config.example.toml and fill it in")
    with open(path, "rb") as f:
        return tomllib.load(f)


class Foa:
    def __init__(self, cfg: dict):
        self.base = cfg["api_base"].rstrip("/")
        self.worker_id = cfg["worker_id"]
        self.s = requests.Session()
        self.s.headers["X-Worker-Token"] = cfg["token"]

    def _post(self, path: str, **kw):
        r = self.s.post(self.base + path, timeout=60, **kw)
        if r.status_code == 403:
            raise SystemExit("FOA rejected the worker token — check token in config.toml "
                             "matches PROPOSAL_WORKER_TOKEN on the server")
        r.raise_for_status()
        return r

    def heartbeat(self, status: str) -> None:
        self._post("/worker/heartbeat", json={"worker_id": self.worker_id,
                                              "status": status, "version": VERSION})

    def claim(self) -> dict | None:
        r = self._post("/worker/proposals/claim", json={"worker_id": self.worker_id})
        return None if r.status_code == 204 else r.json()

    def result(self, job_id: int, pdf: Path) -> None:
        with open(pdf, "rb") as f:
            self._post(f"/worker/proposals/{job_id}/result", data={"worker_id": self.worker_id},
                       files={"file": (pdf.name, f, "application/pdf")})

    def fail(self, job_id: int, error: str, screenshot: bytes | None) -> None:
        files = {"screenshot": ("screenshot.png", screenshot, "image/png")} if screenshot else None
        self._post(f"/worker/proposals/{job_id}/fail",
                   data={"worker_id": self.worker_id, "error": error[:2000]}, files=files)


def screenshot_png() -> bytes | None:
    try:
        buf = io.BytesIO()
        pyautogui.screenshot().save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def start_heartbeat(foa: Foa, cfg: dict, state: dict) -> None:
    def beat():
        while True:
            try:
                foa.heartbeat(state["status"])
            except SystemExit:
                raise
            except Exception as e:
                print(f"heartbeat failed: {e}")
            time.sleep(float(cfg.get("heartbeat_seconds", 30)))
    threading.Thread(target=beat, daemon=True).start()


def handle(foa: Foa, job: dict, cfg: dict, dry_run: bool) -> None:
    jid, inputs = job["id"], job["inputs"]
    print(f"job #{jid} (attempt {job.get('attempt')}): {inputs}")
    try:
        pdf = wechat_flow.run(inputs, cfg)
    except Exception as e:
        msg = str(e) if isinstance(e, wechat_flow.FlowError) else traceback.format_exc()
        print(f"job #{jid} failed: {msg}")
        foa.fail(jid, msg, screenshot_png())
        return
    print(f"job #{jid} produced {pdf}")
    if dry_run:
        print("dry run — not uploading")
        return
    foa.result(jid, pdf)
    print(f"job #{jid} uploaded")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    dry_run = args.dry_run or bool(cfg.get("dry_run"))

    if args.test:
        print(f"test run with {SAMPLE_JOB}")
        print(f"PDF: {wechat_flow.run(SAMPLE_JOB, cfg)}")
        return

    foa = Foa(cfg)
    state = {"status": "idle"}
    start_heartbeat(foa, cfg, state)
    print(f"worker {cfg['worker_id']} polling {foa.base} (move the mouse to a screen corner to abort a run)")
    while True:
        try:
            job = foa.claim()
        except SystemExit:
            raise
        except Exception as e:
            print(f"claim failed: {e}")
            job = None
        if job:
            state["status"] = f"working #{job['id']}"
            try:
                handle(foa, job, cfg, dry_run)
            finally:
                state["status"] = "idle"
            if args.once:
                return
            continue
        if args.once:
            print("no job queued")
            return
        time.sleep(float(cfg.get("poll_seconds", 10)))


if __name__ == "__main__":
    main()
