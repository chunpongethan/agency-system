# FOA 建議書 worker (Windows)

Runs on a Windows PC with WeChat logged in. It picks up proposal requests from FOA,
drives the 保易通助手 mini-program to generate the 建議書, and uploads the PDF back.
FOA then adds the AI analysis.

**While it runs it takes over the mouse and keyboard** — use a PC nobody is working
on. Move the mouse into any screen corner to abort a run immediately.

## 1. One-time setup

1. Install Python 3.10+ (3.11+ recommended) from python.org (tick "Add to PATH").
2. In this folder:
   ```
   pip install -r requirements.txt
   copy config.example.toml config.toml
   ```
3. On the server, generate a token and add it to the VM `.env`, then redeploy:
   ```
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   # .env:  PROPOSAL_WORKER_TOKEN=<that value>
   ```
4. Edit `config.toml`: `api_base` (your FOA API domain), the same `token`, and
   `downloads_dir` (where 保易通's download button saves PDFs).
5. Windows: Settings → Display → Scale **100%**; disable screen lock and sleep
   (Settings → Power). The desktop must stay unlocked — UI automation can't
   click on a locked screen.
6. Open WeChat, open 保易通助手 and leave it on the 工作台 screen. Keep the window
   the same size and position from now on.

## 2. Teach it the screens (calibration)

`flow.toml` lists the steps (click 建議書 → search product → fill age, gender,
premium, term, currency → generate → download). It's a **draft**: open the real
flow once by hand, then adjust `flow.toml` to match the screens and field order.

Capture the images it clicks:
```
python calibrate.py
```
For each item, hover the top-left then bottom-right corner of that button/label
and press Enter. Images go to `templates/`.

Test locally (no FOA involved) with the sample job (30 F, 飛揚·88, USD 50,000, 2 yrs):
```
python main.py --test
```
Fix any step it reports (`step 7 (click label_age): label_age not found on screen`)
by recapturing that template (`python calibrate.py label_age`) or adjusting the step.

## 3. Run

```
python main.py --once --dry-run   # take one real job, don't upload
python main.py                    # run continuously
```
FOA shows "生成機器在線" on the 建議書生成 page while the worker is running.

To start it automatically: Task Scheduler → Create Task → "At log on" →
action `pythonw.exe main.py` with "Start in" = this folder.

## When something breaks

- A failed job is retried up to 3 times, then shows **失敗** in FOA with the error
  and a screenshot of the screen at the time.
- If 保易通 changes its screens, recapture the affected templates; no code changes
  are needed unless the step order changes (then edit `flow.toml`).
- Admins can always attach a PDF by hand on the request in FOA (手動上傳 PDF).

## Caveats

Automating a third-party mini-program may be against its terms and could get the
WeChat account restricted. Only the insured's age, gender, product, premium, term
and currency are sent here — never client names or contact details.
