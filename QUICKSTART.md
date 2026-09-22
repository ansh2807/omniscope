# Quickstart

## Before anything else: unblock the download

Windows tags every file that arrives from the internet, and refuses to run them. If you
double-click `START.bat` and see *"These files can't be opened — your Internet security
settings prevented one or more files from being opened"*, that is what happened. It is not
a fault in the software and it happens to every downloaded zip.

**Fix it before extracting:**

1. Move the `.zip` somewhere simple — `C:\creator-intel` is ideal. **Not** `AppData`, not
   `Program Files`, not OneDrive or Dropbox, and not the zip preview window. Extracting
   into an app container folder such as `AppData\Local\Packages\...` puts you in a
   temporary sandbox that will break in confusing ways.
2. Right-click the `.zip` → **Properties** → tick **Unblock** → **OK**. This clears the
   flag from every file inside at once.
3. Right-click → **Extract All…**

**Already extracted and still blocked?** Unblocking the `.zip` does nothing once the files
are out of it — the flag lives on each extracted file. Right-click **`UNBLOCK.ps1`** →
*Run with PowerShell*, or run it yourself with the path changed to match:

```powershell
Get-ChildItem 'C:\Users\YOU\Desktop\creator-intel' -Recurse | Unblock-File
```

Verify it worked — this should print nothing at all:

```powershell
Get-ChildItem 'C:\Users\YOU\Desktop\creator-intel' -Recurse -File |
  ForEach-Object { Get-Item $_.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue }
```

**Still blocked, or company policy bans `.bat` outright?** Use the PowerShell launcher,
which unblocks the folder itself on the way through:

```powershell
powershell -ExecutionPolicy Bypass -File .\START.ps1
```

**Or skip every script file** and drive it directly — this cannot be blocked by anything
short of blocking Python itself:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe tools\bootstrap.py      # prints your API key
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

---

## The one-click way

**Windows** — double-click, in this order:

| File | What it does | Internet needed |
|---|---|---|
| `DEMO.bat` | Generates five sample reports from bundled data and opens them | No |
| `TEST.bat` | Runs the 48 engine self-tests | No |
| `ENABLE-BROWSER.bat` | One-time: installs a headless browser so the engine can read Instagram and YouTube with no API key | Yes, ~150 MB once |
| `START.bat` | Installs itself if needed, starts the server, opens your browser already signed in | Only for live reports |

**macOS / Linux** — `./start.sh` and `./demo.sh` from a terminal. If they refuse to run,
`chmod +x start.sh demo.sh` first.

The launcher creates the virtual environment, installs dependencies, generates a private
API key and saves it to `.env`, picks a free port, and opens the browser. First run takes
about ninety seconds; every run after that takes about five.

That is genuinely all most people need. The rest of this document is for when something
goes wrong, or when you want to drive the engine from the command line.

---

## The manual way

Four stages, each one proving more than the last. Do them in order — if stage 2 passes,
the engine is sound and any later failure is a network or config problem, not a logic one.

## 0. Prerequisites

* **Python 3.10 or newer.** Check with `python --version`. If that errors, install from
  python.org and tick **"Add python.exe to PATH"** during setup.
* No database, no Docker, no API keys needed for stages 1–2.

## 1. Install (about two minutes)

Open **PowerShell**, `cd` into the extracted folder (the one containing `README.md`), then:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env
```

If PowerShell refuses to activate the venv with a script-execution error, run this once in
the same window and retry:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Using `cmd.exe` instead of PowerShell? The activate line is `.venv\Scripts\activate.bat`.

You should now see `(.venv)` at the start of your prompt. Everything below assumes that.

## 2. Prove the engine works — no internet required

```powershell
python -m pytest tests/ -q
```

Expect `82 passed`. These run the whole engine against frozen real data from four
creators and assert the conclusions, not the exact numbers — including that it
independently rediscovers the "one shot" and "free finance courses" formulas from raw
titles and view counts.

```powershell
python scripts_demo.py
```

Expect five lines of output and ten files in `data\samples\`. Open both kinds:

```powershell
start data\samples\sunil_panda.html   # single creator, 13 sections
start data\samples\cohort.html        # all four compared, plus the cohort layer
```

That is exactly what a client receives. If these look right, the engine, all the analysis
modules and both renderers are working.

## 3. First live run — one creator, via the CLI

Use the CLI before the web app. It prints progress to the console, so when a collector
fails you see precisely where.

```powershell
python cli.py https://www.youtube.com/@sunilpandaofficial --out .\out
```

YouTube first, deliberately — it is the collector with the richest public data and no
login wall, so it is the cleanest test of the whole pipeline.

Then try an Instagram seed:

```powershell
python cli.py https://www.instagram.com/chanchal_iim/ --out .\out
```

Instagram post data is login-walled, so the CLI will model those dimensions and say so.
To supply the numbers yourself, create `ig.json`:

```json
{ "followers": 33300, "avg_reel_views": 42000, "avg_likes": 1800,
  "highlights": "Self Prep for CAT, Resume, Info carousels, Workshops" }
```

and re-run with `--manual .\ig.json`.

**A cohort report** — pass several links and the engine adds comparison, pairwise
audience overlap, lifecycle ordering and an investment verdict on top:

```powershell
python cli.py https://www.youtube.com/@one https://www.instagram.com/two/ @three --out .\out
```

**Competitor discovery** is opt-in because it spends search queries:

```powershell
python cli.py @handle --competitors
```

**Skip the search layer while testing** with `--no-dorks`. Without a search API key it is
skipped anyway, and the report will say identity expansion ran on owned links only.

## 4. Run the web app

```powershell
uvicorn app.main:app --reload
```

Open **http://localhost:8000**, sign in with `dev-key-change-me` (from your `.env`), paste
a creator link, and watch the job page. Paste **several links, one per line** (up to 8) and
you get a cohort report instead. Tick the competitor box to enable that stage.

When a job needs Instagram numbers it moves to `needs_input` and offers the paste-form;
fill what you have and leave the rest blank — anything blank is modelled with a confidence
score rather than left as a hole.

Test the API directly:

```powershell
# single creator
curl.exe -X POST http://localhost:8000/api/reports `
  -H "content-type: application/json" -H "x-api-key: dev-key-change-me" `
  -d '{\"url\":\"https://www.youtube.com/@sunilpandaofficial\"}'

# cohort
curl.exe -X POST http://localhost:8000/api/reports `
  -H "content-type: application/json" -H "x-api-key: dev-key-change-me" `
  -d '{\"urls\":[\"@one\",\"@two\",\"@three\"],\"with_competitors\":true}'
```

Both return a `job_id`. Poll `GET /api/jobs/{id}` until `status` is `done`, then the
response carries the share link and the Word download.

Use `curl.exe`, not `curl` — bare `curl` in PowerShell is an alias for `Invoke-WebRequest`
and takes different arguments.

## 5. Turn on the optional data sources

Both are free to start and both materially improve output quality.

**YouTube Data API** — exact subscriber counts, per-video stats, real publish dates.
Google Cloud Console → new project → enable *YouTube Data API v3* → create an API key →
put it in `.env` as `YOUTUBE_API_KEY`. Free quota is 10,000 units/day, roughly 300 reports.

**Browser tier — do this one first.** Run `ENABLE-BROWSER.bat` once. It installs a
headless Chromium and lets the engine read Instagram follower counts, YouTube's
all-time-Popular view counts and YouTube comment threads with **no API key at all** —
logged out, exactly as a visitor sees them. This is the single biggest upgrade and it
costs nothing.

**Search / discovery layer** — the one thing the browser cannot replace, because
scraping a search engine gets you blocked within the hour. It powers identity expansion,
the SEO section and competitor discovery. Without it those sections honestly report "not
assessed" rather than guessing. Cheapest start is serper.dev (2,500 free queries). Set:

```
SEARCH_PROVIDER="serper"
SERPER_API_KEY="your-key"
```

Restart the server. The Settings page shows which sources are live; Diagnostics tests each one against a real public page.

## When something is not working

**Open Diagnostics in the app first.** It tests every collection tier against real public
pages and tells you exactly which one is failing and how to fix it. That is faster than
anything in the table below.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "These files can't be opened / Internet security settings" | Mark of the Web. Unblock the zip before extracting, or run `Get-ChildItem <folder> -Recurse \| Unblock-File`. See the top of this document. |
| Path contains `AppData\Local\Packages\` | You are running from inside an app's temporary container. Move the folder to `C:\creator-intel` and start again. |
| `START.bat` flashes and closes | Python is missing or not on PATH. Install from python.org with "Add python.exe to PATH" ticked. The window stays open on every other error. |
| Launcher says the port is in use | It tries 8000, 8001, 8002, 8003, then 8010 automatically. If all are busy, close whatever is holding them. |
| Browser opens to a "Sign in" box | The auto-login key did not reach the page. Copy `API_KEYS` from `.env` and paste it in. |
| `'python' is not recognized` | Python not on PATH. Reinstall with the PATH box ticked, or use `py` instead. |
| `Activate.ps1 cannot be loaded` | PowerShell execution policy. Run the `Set-ExecutionPolicy -Scope Process` line above. |
| `ImportError: ... socksio` | You are behind a SOCKS proxy. `pip install "httpx[socks]"`. |
| `sqlite3.OperationalError: disk I/O error` | The database file is on a network drive or synced folder (OneDrive, Dropbox). Point `DATABASE_URL` at a local path, e.g. `sqlite:///C:/creatorintel/ci.db`. |
| YouTube collector returns no videos | The public-page fallback broke because YouTube changed its markup. Set `YOUTUBE_API_KEY` — the API path is stable. |
| Instagram returns no follower count | Instagram declined to serve public meta for that profile. Expected, not a bug — use the paste-form. |
| Asked for Instagram numbers before the report | Only happens when Instagram returned no follower count at all. Run `ENABLE-BROWSER.bat` and re-run the job — it reads the count off the rendered page. |
| Follower count looks wrong or suspiciously round | Instagram's meta tag rounds hard ("10M" could be anything from 9.5M to 10.5M). The report flags this as *rounded, low precision*. Install the browser tier for the exact figure. |
| Everything says "no public presence discovered" | The browser tier is not installed, so nothing could be read or verified. Run `START.bat` again — it installs it. |
| Does Chromium download every time? | No. `START.bat` writes a stamp file after the first success and skips the step forever after. |
| Reports piling up on disk | They do not. Retention prunes after every run — see Settings for usage, limits and a Clear button. |
| Sections 6/7/8 empty, or Instagram followers missing | Run `ENABLE-BROWSER.bat` (for 6 and Instagram) and set `SEARCH_PROVIDER` (for 7 and 8). |
| "Browser tier unavailable" in a report | Playwright is not installed. Run `ENABLE-BROWSER.bat`, or `pip install playwright && python -m playwright install chromium`. |
| Report says "Search provider not configured" | Working as intended. Set `SEARCH_PROVIDER` to enable the discovery, SEO and competitor sections. |
| Sections 7 and 8 say "not assessed" | Same cause — no search key. Everything else still generates. |
| Section 5 says content analysis could not run | Fewer than four items carried a public view count. Normal for Instagram-only subjects; add a YouTube link to the same job. |
| Job stuck at `running` | Look at the uvicorn console. Collector exceptions surface there and in the job's `error` field. |

## What I could not test for you

The **collection layer against live sites** — my build environment blocked outbound HTTP,
so the YouTube, Instagram, Topmate and web collectors are written and unit-reachable but
have not been run against the real internet. Everything downstream of collection
(inference, rules, renderers, API, share links, job flow) is verified end to end.

Stage 3 is therefore your real first test. If a collector misbehaves, the failure will be
in parsing, and it will be visible in the job's `errors` list and in the report's
"Collected surfaces" table rather than crashing the run — every collector catches its own
exceptions and records them.
