# Website Reverse Engineering (Carbon)

Public-frontend reverse engineering → report + GitHub/Render-ready reconstruction ZIP.

## Deploy on Render (Web Service — not Static)

| Setting | Value |
|---------|--------|
| Type | **Web Service** |
| Runtime | Python 3 |
| Build | `pip install -r requirements.txt && python -m playwright install chromium` |
| Start | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| PYTHON_VERSION | `3.12.0` |

Leave **Browser mode OFF** on free tier (Playwright often kills the process).

## Push to GitHub

```bash
unzip website-reverse-engineering-carbon.zip
cd website-reverse-engineering-carbon
git init
git add .
git commit -m "Fix: disk job store, JSON status, browser off by default"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/reverseengi.git
git push -u origin main
```

Then **Manual Deploy** on Render (clear build cache if available).

## Verify after deploy

Open:

- `https://YOUR-APP.onrender.com/api/health` → should show JSON `{"status":"ok",...}`
- `https://YOUR-APP.onrender.com/` → the UI

If health returns HTML, the start command is wrong or the service is not the Python app.

## Local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
