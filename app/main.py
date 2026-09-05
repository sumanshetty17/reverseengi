"""
Website Reverse Engineering — FastAPI Backend
College Project / Expo Demonstration
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from app.analyzer import analyze, get_job, list_jobs

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"
RECONSTRUCTIONS_DIR = BASE_DIR / "reconstructions"
ARTIFACTS_DIR = BASE_DIR / "artifacts"
DOWNLOADS_DIR = BASE_DIR / "downloads"

for d in (REPORTS_DIR, RECONSTRUCTIONS_DIR, ARTIFACTS_DIR, DOWNLOADS_DIR):
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Website Reverse Engineering",
    description=(
        "Deep website reverse-engineering and reconstruction platform. "
        "Enter a URL → crawl, render, fingerprint, collect assets → "
        "generate technical report + GitHub-ready reconstruction ZIP."
    ),
    version="1.0.0",
)

# Serve static frontend
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class AnalyzeRequest(BaseModel):
    url: str = Field(..., description="Target website URL")
    max_pages: int = Field(30, ge=1, le=100, description="Maximum pages to crawl")
    max_assets: int = Field(300, ge=1, le=500, description="Maximum assets to download")
    browser_mode: bool = Field(True, description="Use Playwright for dynamic content")
    build_reconstruction: bool = Field(True, description="Generate reconstruction ZIP")
    depth: int = Field(2, ge=1, le=5, description="Crawl depth")
    # Optional authorized login (only use accounts you own / are allowed to access)
    login_url: str | None = Field(None, description="Login page URL if different from site URL")
    username: str | None = Field(None, description="Username or email for authorized login")
    password: str | None = Field(None, description="Password for authorized login (not stored)")
    username_selector: str | None = Field(None, description="Optional CSS selector for username field")
    password_selector: str | None = Field(None, description="Optional CSS selector for password field")
    submit_selector: str | None = Field(None, description="Optional CSS selector for submit button")
    proxy: str | None = Field(None, description="Optional proxy URL so target sees proxy IP, not yours (http://host:port or socks5://host:port)")
    session_cookies: str | None = Field(None, description="Cookies after YOU logged in (browser cookie string or JSON). Tool uses your session — you solve CAPTCHA/login yourself.")
    private_mode: bool = Field(True, description="If true, refuse to start unless a proxy is set (target never sees server IP).")


class AnalyzeResponse(BaseModel):
    job_id: str
    status: str
    message: str
    url: str
    created_at: str


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main demonstration UI."""
    index = static_dir / "index.html"
    if index.exists():
        return HTMLResponse(content=index.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<h1>Website Reverse Engineering</h1><p>UI not found. Place index.html in app/static/</p>"
    )


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_site(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    """
    Start a reverse-engineering job for the given URL.
    Returns a job_id immediately; processing continues in background.
    """
    job_id = str(uuid.uuid4())
    created = datetime.now(timezone.utc).isoformat()

    # Privacy: never expose server IP when private_mode is on
    from app.privacy import resolve_proxy, require_proxy_enabled
    strict = bool(req.private_mode) or require_proxy_enabled()
    proxy_ok = resolve_proxy(req.proxy)
    if strict and not proxy_ok:
        raise HTTPException(
            status_code=400,
            detail=(
                "PRIVATE MODE: a working proxy is required so the target does not see this server's IP. "
                "Set the Proxy field (http://user:pass@host:port or socks5://host:port) "
                "or env CRAWLER_PROXY on Render. Placeholder values are rejected."
            ),
        )

    # Kick off background analysis
    login = None
    if req.username and req.password or req.session_cookies:
        login = {
            "login_url": req.login_url or req.url,
            "username": req.username or "",
            "password": req.password or "",
            "username_selector": req.username_selector or "",
            "password_selector": req.password_selector or "",
            "submit_selector": req.submit_selector or "",
            "session_cookies": req.session_cookies or "",
        }

    background_tasks.add_task(
        analyze,
        job_id=job_id,
        url=req.url,
        max_pages=req.max_pages,
        max_assets=req.max_assets,
        browser_mode=req.browser_mode,
        build_reconstruction=req.build_reconstruction,
        depth=req.depth,
        login=login,
        proxy=req.proxy,
        session_cookies=req.session_cookies,
    )

    return AnalyzeResponse(
        job_id=job_id,
        status="queued",
        message="Analysis started. Poll /api/report/{job_id} for results.",
        url=req.url,
        created_at=created,
    )


@app.get("/api/jobs")
async def api_list_jobs():
    """List recent analysis jobs."""
    return {"jobs": list_jobs()}


@app.get("/api/report/{job_id}")
async def get_report_summary(job_id: str):
    """Get job status and high-level report summary."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/report/{job_id}/json")
async def get_report_json(job_id: str):
    """Full JSON technical report."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    report_path = REPORTS_DIR / job_id / "report.json"
    if report_path.exists():
        return FileResponse(report_path, media_type="application/json", filename=f"report_{job_id}.json")
    # Fallback to in-memory
    if job.get("report"):
        return JSONResponse(content=job["report"])
    raise HTTPException(status_code=404, detail="Report not ready yet")


@app.get("/api/report/{job_id}/html", response_class=HTMLResponse)
async def get_report_html(job_id: str):
    """Human-readable HTML report."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    html_path = REPORTS_DIR / job_id / "report.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    # Minimal fallback
    status = job.get("status", "unknown")
    return HTMLResponse(
        f"<h1>Report {job_id}</h1><p>Status: {status}</p>"
        f"<pre>{job.get('message', '')}</pre>"
    )


@app.get("/api/report/{job_id}/bundle")
async def get_report_bundle(job_id: str):
    """Download full report + manifests as ZIP."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    bundle = REPORTS_DIR / job_id / "report_bundle.zip"
    if bundle.exists():
        return FileResponse(bundle, media_type="application/zip", filename=f"report_bundle_{job_id}.zip")
    raise HTTPException(status_code=404, detail="Report bundle not ready")


@app.get("/api/reconstruction/{job_id}/zip")
async def get_reconstruction_zip(job_id: str):
    """Download the reconstructed project ZIP (GitHub-ready)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    zip_path = RECONSTRUCTIONS_DIR / job_id / "reconstructed-site.zip"
    if zip_path.exists():
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=f"reconstructed-site_{job_id}.zip",
        )
    raise HTTPException(status_code=404, detail="Reconstruction ZIP not ready")


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "Website Reverse Engineering", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
