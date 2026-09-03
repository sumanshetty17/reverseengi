# Website Reverse Engineering Platform

College Project / Expo Demonstration

Deep website reverse-engineering and reconstruction system.  
Enter a URL → crawl, render, fingerprint, collect code & assets → technical report + **GitHub-ready reconstruction ZIP**.

---

## Deploy on Render (recommended)

1. Push this repo to GitHub.
2. Go to [https://dashboard.render.com](https://dashboard.render.com) → **New** → **Web Service**.
3. Connect your GitHub repository.
4. Render settings (or use the included `render.yaml` Blueprint):

| Setting | Value |
|---------|--------|
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |

5. Click **Create Web Service**. After deploy, open the Render URL (e.g. `https://your-app.onrender.com`).

> **Note:** Playwright/browser rendering needs extra memory. On the free plan, leave **Browser rendering** unchecked in the UI (HTTP crawl + parse still work). On a paid plan you can add `playwright install chromium` to the build command if needed.

### Blueprint deploy

If your account supports Blueprints:

```bash
# After pushing to GitHub, in Render Dashboard:
# New → Blueprint → select this repo (uses render.yaml)
```

---

## Push to GitHub

```bash
unzip website-reverse-engineering.zip
cd website-reverse-engineering

git init
git add .
git commit -m "Initial commit: Website Reverse Engineering platform"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/website-reverse-engineering.git
git push -u origin main
```

---

## Features

| Area | Capability |
|------|------------|
| Input | Website URL + limits |
| Crawling | Multi-page, same-origin, depth-limited |
| Rendering | Playwright (optional) for dynamic sites |
| Collection | HTML, CSS, JS, images, fonts, JSON |
| Fingerprinting | 30+ technology rules with evidence |
| Purpose | Title, motto/slogan, inferred positioning |
| APIs | Client-visible endpoints |
| Output | Report (JSON/HTML) + reconstruction ZIP |

---

## API

```
POST /api/analyze
GET  /api/report/{job_id}
GET  /api/report/{job_id}/json
GET  /api/report/{job_id}/html
GET  /api/report/{job_id}/bundle
GET  /api/reconstruction/{job_id}/zip
GET  /api/health
```

---

## Project structure

```
website-reverse-engineering/
├── app/
│   ├── main.py
│   ├── analyzer.py
│   ├── crawler.py
│   ├── browser.py
│   ├── parser.py
│   ├── fingerprint.py
│   ├── data_analyzer.py
│   ├── asset_collector.py
│   ├── reconstruction.py
│   ├── reporting.py
│   └── static/index.html
├── reports/
├── reconstructions/
├── downloads/
├── tests/
├── requirements.txt
├── render.yaml
├── runtime.txt
├── README.md
└── PROJECT_SPEC.md
```

---

## Local run (optional)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## License

Educational / college project use.
