# Website Reverse Engineering (Carbon)

Public-frontend reverse engineering → technical report + **GitHub / Render-ready reconstruction ZIP**.

## What this does

| Capability | Behavior |
|------------|----------|
| Public pages | HTML, CSS, JS, images, fonts |
| Scroll gates | Clicks “Scroll to explore”, cookie walls, unlocks overflow |
| Stack / purpose | Fingerprint + inferred public business shape |
| Key types | Strips secrets; `.env.example` lists **your** keys to add |
| Clone data | Reconstruction `server.js` stores **clone** users/forms in `data/db.json` |
| Original customers | **Never** copied |

## Deploy THIS tool on Render (analyzer)

1. Push this repo to GitHub.
2. Render → **New** → **Web Service** (or **Blueprint** + `render.yaml`).

| Setting | Value |
|---------|--------|
| Runtime | Python 3 |
| Build | `pip install -r requirements.txt && playwright install --with-deps chromium` |
| Start | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |

Free tier may OOM on heavy Chromium pages — turn browser mode off or use a paid plan.

## Push to GitHub

```bash
unzip website-reverse-engineering-carbon.zip
cd website-reverse-engineering-carbon
git init
git add .
git commit -m "Carbon: scroll gates, clone-owned backend, key placeholders"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/website-reverse-engineering.git
git push -u origin main
```

## Local run (analyzer)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open the URL, paste a public site, download the **reconstruction ZIP**.

## Reconstruction ZIP (the clone you host)

After analysis, download the ZIP. It includes:

- Public page snapshots + assets
- `server.js` — Express + **clone-owned** `/api/auth/*` and `/api/data/*`
- `data/db.json` created at runtime for **your** clone visitors only
- `.env.example` — add **your** publishable keys
- `render.yaml` — deploy the **clone** as a Node service on Render

```bash
cd reconstruction-folder
npm install
npm start
```

## Scope

Public frontend only. No original private database, no stolen API secrets, no phishing of the real site’s logins.
