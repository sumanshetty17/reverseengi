# Website Reverse Engineering (Carbon)

Public-frontend reverse engineering → report + GitHub/Render-ready reconstruction ZIP.

## Sequential rounds (stops free-host OOM / 502)

Each request captures only a small batch (default **4 pages per round**), writes a zip, then the next request continues from the queue:

| Round | Output | Behavior |
|-------|--------|----------|
| 1 | `reconstructed-site-round-1.zip` | Full scaffold + pages + `merge.js` + `MERGE.md` |
| 2+ | `reconstructed-site-round-N.zip` | New `pages/` + `maps/` only (no duplicates) |
| Done | All rounds listed in UI | Download each zip, or merge with `node merge.js` |

- Session queue is stored on disk (`sessions/`) so Round 2 starts where Round 1 stopped.
- Failed pages are skipped once and marked visited (crawl continues).
- **Pages per round** in the UI: use **3–4** on Render free tier.
- Leave **Browser mode OFF** on free tier (Playwright often OOMs). Later rounds never start Playwright.
- **Keep going round by round** (checked by default) auto-starts the next round until the queue is empty.

## Deploy on Render (Web Service — not Static Site)

1. Push this repo to GitHub (files at **repo root**: `app/`, `requirements.txt`, etc.).
2. Render → **New → Web Service** → connect the repo.
3. Settings:

| Setting | Value |
|---------|--------|
| Runtime | **Python 3** |
| Build Command | `pip install -r requirements.txt && python -m playwright install chromium \|\| true` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Instance type | Free |
| Env `PYTHON_VERSION` | `3.12.0` |

Optional: use the included `render.yaml` (Blueprint) instead of manual settings.

4. Deploy. After build finishes open:
   - `https://YOUR-APP.onrender.com/api/health` → should be JSON with `"rounds": true`
   - `https://YOUR-APP.onrender.com/` → Carbon UI

If `/api/health` returns HTML, the start command is wrong or the service type is Static Site.

## Push to GitHub

Unzip this package, then from **inside** the folder that contains `app/` and `requirements.txt`:

```bash
cd website-reverse-engineering-carbon
git init
git add .
git commit -m "Carbon: sequential crawl rounds (round-N zips, no OOM)"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

**Important:** `app/` and `requirements.txt` must be at the **repository root** (not nested under another folder), unless you set Render **Root Directory** to that folder.

## After deploy — how to use

1. Paste a public site URL.
2. Set **Pages per round** to `4` (or `3` if it still times out).
3. Leave **Browser mode** off on free tier.
4. Keep **Keep going round by round** checked.
5. Start analysis. Download each `…-round-N.zip` as it appears.
6. Merge offline:
   - Unzip `reconstructed-site-round-1.zip`
   - Copy later rounds’ `pages/` (and `maps/`) into it
   - Run `node merge.js` then `npm install && npm start`

## Local run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Railway (optional)

Same code. Root Directory = folder with `app/` + `requirements.txt` (empty if at repo root).

- Build: `pip install -r requirements.txt && python -m playwright install chromium || true`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Serverless: **OFF**

## Project layout

```
app/                 FastAPI app + crawler + reconstruction
app/static/          UI (pages per round, keep going, round zip list)
sessions/            Durable crawl queue (gitignored contents)
reconstructions/     Round zips (gitignored contents)
requirements.txt
render.yaml
Procfile
runtime.txt
```
