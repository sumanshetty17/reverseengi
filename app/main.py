"""
main.py
-------
FastAPI application wiring together security.py, analyzer.py and
reporting.py. Implements the API surface from Section 11 of the spec:

    POST /api/analyze                {url, max_assets}
    GET  /api/report/{job_id}
    GET  /api/report/{job_id}/json
    GET  /api/report/{job_id}/html
    GET  /api/report/{job_id}/bundle

Jobs run in-process (asyncio) and are held in memory for this first version
(Phase 1-4 of the roadmap). Phase 7 (Postgres + Redis + queue + accounts) is
a drop-in replacement for the JOBS dict / run_analysis() call site — nothing
else in this file should need to change.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analyzer, reporting, security
from .analyzer import (
    OBSERVED,
    INFERRED,
    UNKNOWN,
    NOT_APPLICABLE,
    Evidence,
    SafeAsyncClient,
    extract_assets,
    extract_forms,
    extract_links,
    extract_metadata,
    detect_motto,
    fingerprint_technologies,
    sha256_of,
    summarize_security_headers,
)
from .security import DEFAULT_LIMITS, SecurityError

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"
DOWNLOADS_DIR = BASE_DIR / "downloads"
REPORTS_DIR.mkdir(exist_ok=True)
DOWNLOADS_DIR.mkdir(exist_ok=True)

app = FastAPI(
    title="SiteScope",
    description="Evidence-backed analysis of a public website's observable implementation.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# In-memory job store (Phase 1-4). job_id -> dict with status/report/errors.
JOBS: dict[str, dict] = {}


class AnalyzeRequest(BaseModel):
    url: str = Field(..., description="Public http(s) URL to analyze.")
    max_assets: int = Field(30, ge=1, le=DEFAULT_LIMITS.max_assets_per_page,
                             description="Max number of assets to actually download.")


class AnalyzeResponse(BaseModel):
    job_id: str
    status: str


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    # Fail fast on obviously bad input before creating a job.
    try:
        security.validate_url(req.url)
    except SecurityError as e:
        raise HTTPException(status_code=400, detail=str(e))

    job_id = uuid.uuid4().hex[:16]
    JOBS[job_id] = {"status": "running", "report": None, "errors": []}
    asyncio.create_task(run_analysis(job_id, req.url, req.max_assets))
    return AnalyzeResponse(job_id=job_id, status="running")


@app.get("/api/report/{job_id}")
async def get_report_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job_id.")
    return {"job_id": job_id, "status": job["status"], "errors": job["errors"]}


@app.get("/api/report/{job_id}/json")
async def get_report_json(job_id: str):
    job = _require_finished_job(job_id)
    return JSONResponse(job["report"])


@app.get("/api/report/{job_id}/html")
async def get_report_html(job_id: str):
    job = _require_finished_job(job_id)
    return HTMLResponse(reporting.render_html_report(job["report"]))


@app.get("/api/report/{job_id}/bundle")
async def get_report_bundle(job_id: str):
    job = _require_finished_job(job_id)
    bundle_path = job.get("bundle_path")
    if not bundle_path or not Path(bundle_path).exists():
        raise HTTPException(status_code=404, detail="Bundle not available for this job.")
    return FileResponse(bundle_path, filename=Path(bundle_path).name, media_type="application/zip")


def _require_finished_job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job_id.")
    if job["status"] == "running":
        raise HTTPException(status_code=202, detail="Job still running.")
    if job["status"] == "failed":
        raise HTTPException(status_code=500, detail=f"Job failed: {job['errors']}")
    return job


# ---------------------------------------------------------------------------
# Core job runner
# ---------------------------------------------------------------------------
async def run_analysis(job_id: str, target_url: str, max_assets: int):
    errors: list[str] = []
    client = SafeAsyncClient()
    try:
        # --- 1. Fetch the main page (Section 12: async client, redirects, timeout) ---
        resp, final_url, body = await client.safe_get(target_url)
        if resp.status_code >= 400:
            raise SecurityError(f"Target responded with HTTP {resp.status_code}.")
        content_type = resp.headers.get("content-type", "")
        if "html" not in content_type.lower() and body[:15].lower().lstrip().find(b"<html") == -1:
            errors.append(
                f"Response content-type was '{content_type}', not HTML. "
                "Analysis will proceed on a best-effort basis."
            )
        html_text = body.decode(resp.encoding or "utf-8", errors="replace")
        soup = BeautifulSoup(html_text, "lxml")
        raw_headers = dict(resp.headers)
        scrubbed_headers = security.scrub_response_headers(raw_headers)
        sensitive_present = security.sensitive_response_header_names_present(raw_headers)

        # --- 2. Metadata / purpose / motto ---
        metadata = extract_metadata(soup)
        motto_evidence = detect_motto(soup, metadata)
        purpose_text = _infer_purpose(metadata)

        # --- 3. Technology fingerprinting ---
        tech_findings = fingerprint_technologies(html_text, raw_headers, final_url)

        # --- 4. Assets / forms / links ---
        asset_records = extract_assets(soup, final_url)[: DEFAULT_LIMITS.max_assets_per_page]
        forms = extract_forms(soup, final_url)
        links = extract_links(soup, final_url)

        # --- 5. Selectively download a bounded number of public assets ---
        downloaded_paths: list[Path] = []
        job_download_dir = DOWNLOADS_DIR / job_id
        job_download_dir.mkdir(parents=True, exist_ok=True)
        to_download = [a for a in asset_records if a.kind in ("css", "js")][:max_assets]
        for i, asset in enumerate(to_download):
            try:
                a_resp, a_final_url, a_body = await client.safe_get(
                    asset.source_url, max_bytes=DEFAULT_LIMITS.max_asset_bytes
                )
                if a_resp.status_code == 200:
                    ext = "css" if asset.kind == "css" else "js"
                    fname = f"{i:03d}_{asset.kind}.{ext}"
                    fpath = job_download_dir / fname
                    fpath.write_bytes(a_body)
                    asset.local_filename = fname
                    asset.size_bytes = len(a_body)
                    asset.sha256 = sha256_of(a_body)
                    asset.fetched = True
                    downloaded_paths.append(fpath)
            except (SecurityError, Exception) as e:  # noqa: BLE001 - best-effort per-asset
                asset.note = f"Not downloaded: {e}"

        # save the main HTML too, as part of the public source inventory
        main_html_path = job_download_dir / "index.html"
        main_html_path.write_bytes(html_text.encode("utf-8", errors="replace"))
        downloaded_paths.append(main_html_path)

        # --- 6. robots.txt / sitemap.xml ---
        robots_evidence = await _fetch_robots(client, final_url)
        sitemap_evidence = await _fetch_sitemap(client, final_url)

        # --- 7. Security header summary ---
        sec_headers_summary = summarize_security_headers(scrubbed_headers)

        # --- 8. Third-party services (derived from tech findings, dedup by category) ---
        third_party = sorted({
            t.name for t in tech_findings
            if t.category in ("Analytics", "Payments", "Customer Support", "Error Monitoring",
                               "A/B Testing", "Security/Bot-protection", "CDN/Hosting", "Fonts")
        })

        # --- 9. Assemble canonical report dict ---
        exec_summary = _build_exec_summary(metadata, tech_findings, final_url)
        frontend_architecture = _describe_frontend_architecture(tech_findings, asset_records)
        limitations = _standard_limitations(sensitive_present)
        unknowns = _standard_unknowns()

        report_input = {
            "job_id": job_id,
            "target_url": target_url,
            "final_url": final_url,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "executive_summary": exec_summary,
            "identity": {
                "title": metadata["title"],
                "description": metadata["description"],
                "canonical_url": metadata["canonical_url"],
                "language": metadata["language"],
                "generator": metadata["generator"],
            },
            "purpose": purpose_text,
            "motto": motto_evidence.to_dict(),
            "technology_stack": [t.to_dict() for t in tech_findings],
            "frontend_architecture": frontend_architecture,
            "html_css_js_inventory": {
                "css_files_found": sum(1 for a in asset_records if a.kind == "css"),
                "js_files_found": sum(1 for a in asset_records if a.kind == "js"),
                "images_found": sum(1 for a in asset_records if a.kind == "image"),
                "fonts_found": sum(1 for a in asset_records if a.kind == "font"),
                "icons_found": sum(1 for a in asset_records if a.kind == "icon"),
            },
            "public_source_inventory": {
                "summary": (
                    f"{len(downloaded_paths)} publicly delivered file(s) downloaded and included "
                    "in the bundle (main HTML plus a bounded number of CSS/JS assets)."
                ),
            },
            "assets": [a.to_dict() for a in asset_records],
            "forms": forms,
            "links_and_routes": links,
            "third_party_services": third_party,
            "seo_and_structured_data": {
                "open_graph": metadata["open_graph"],
                "twitter_card": metadata["twitter_card"],
                "json_ld": metadata["json_ld"],
            },
            "http_headers": scrubbed_headers,
            "security_observations": {
                "headers": sec_headers_summary,
                "sensitive_header_names_seen_but_redacted": sensitive_present,
            },
            "robots_txt": robots_evidence.to_dict(),
            "sitemap_xml": sitemap_evidence.to_dict(),
            "performance_and_accessibility_notes": _perf_a11y_notes(soup),
            "unknown_or_private_components": unknowns,
            "limitations": limitations,
            "errors": errors,
        }

        report = reporting.build_json_report(report_input)

        # --- 10. Write JSON + HTML to reports/ and build the bundle ---
        job_report_dir = REPORTS_DIR / job_id
        job_report_dir.mkdir(parents=True, exist_ok=True)
        (job_report_dir / "report.json").write_text(
            __import__("json").dumps(report, indent=2), encoding="utf-8"
        )
        (job_report_dir / "report.html").write_text(
            reporting.render_html_report(report), encoding="utf-8"
        )
        bundle_path = reporting.write_bundle(job_report_dir, report, downloaded_paths)

        JOBS[job_id] = {
            "status": "done",
            "report": report,
            "errors": errors,
            "bundle_path": str(bundle_path),
        }

    except SecurityError as e:
        JOBS[job_id] = {"status": "failed", "report": None, "errors": [str(e)]}
    except Exception as e:  # noqa: BLE001 - top-level job guard
        JOBS[job_id] = {"status": "failed", "report": None, "errors": [f"Unexpected error: {e}"]}
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Helper reasoning functions (kept small & explicit per Section 2's evidence model)
# ---------------------------------------------------------------------------
def _infer_purpose(metadata: dict) -> str:
    bits = []
    if metadata.get("description"):
        bits.append(f'Meta description: "{metadata["description"]}"')
    og_type = (metadata.get("open_graph") or {}).get("type")
    if og_type:
        bits.append(f"Open Graph type declared as '{og_type}'")
    if metadata.get("headings_sample"):
        bits.append("Top headings: " + "; ".join(metadata["headings_sample"][:5]))
    if not bits:
        return "INFERRED: insufficient on-page signal to characterize purpose/audience with confidence."
    return "INFERRED positioning based on on-page signals — " + " | ".join(bits)


def _build_exec_summary(metadata: dict, tech_findings: list, final_url: str) -> str:
    title = metadata.get("title") or "(no <title> found)"
    top_tech = ", ".join(t.name for t in tech_findings[:5]) or "no technologies fingerprinted with confidence"
    return (
        f"SiteScope analyzed the publicly served page at {final_url}. Page title: \"{title}\". "
        f"Top technology signals: {top_tech}. This summary reflects only what a public, "
        f"unauthenticated client received — see 'Unknown / Private Components' and 'Limitations' "
        f"for what could not be observed."
    )


def _describe_frontend_architecture(tech_findings: list, asset_records: list) -> str:
    frameworks = [t.name for t in tech_findings if t.category == "Framework"]
    css_count = sum(1 for a in asset_records if a.kind == "css")
    js_count = sum(1 for a in asset_records if a.kind == "js")
    if frameworks:
        return (
            f"Client-side framework signal(s) detected: {', '.join(frameworks)}. "
            f"{js_count} script reference(s) and {css_count} stylesheet reference(s) found in the "
            "delivered HTML. Rendering behavior beyond the raw HTML (e.g. client-side routing, "
            "lazy-loaded content) is UNKNOWN without browser rendering (see Roadmap Phase 5)."
        )
    return (
        f"No specific client-side framework markers detected in the raw HTML; the page may be "
        f"server-rendered or use a framework without a detectable static signature. "
        f"{js_count} script reference(s) and {css_count} stylesheet reference(s) found."
    )


def _perf_a11y_notes(soup: BeautifulSoup) -> list[str]:
    notes = []
    imgs = soup.find_all("img")
    missing_alt = sum(1 for i in imgs if not i.get("alt"))
    if imgs:
        notes.append(f"{missing_alt} of {len(imgs)} <img> tag(s) are missing an 'alt' attribute.")
    if not soup.find("meta", attrs={"name": "viewport"}):
        notes.append("No <meta name=\"viewport\"> tag found — page may not declare mobile responsiveness.")
    render_blocking = len(soup.find_all("script", src=True, attrs={"async": False, "defer": False}))
    if render_blocking:
        notes.append(f"{render_blocking} script tag(s) appear to lack async/defer attributes (potentially render-blocking).")
    if not soup.find("h1"):
        notes.append("No <h1> heading found on the page.")
    return notes


def _standard_limitations(sensitive_present: list[str]) -> list[str]:
    items = [
        "Only publicly delivered, unauthenticated content was analyzed. Private backend source "
        "code, databases, credentials, and protected/authenticated APIs are never accessible to "
        "this tool and are not claimed to have been recovered.",
        "This version analyzes the raw HTML response only; JavaScript was not executed, so content "
        "injected client-side after page load may not be reflected (see Roadmap Phase 5: Playwright rendering).",
        "Technology fingerprints are probabilistic. A single weak signal is reported at low "
        "confidence rather than treated as certain.",
        "Only a bounded number of CSS/JS assets were downloaded (configurable byte/asset caps); "
        "additional assets are listed but may not be included in the bundle.",
    ]
    if sensitive_present:
        items.append(
            f"The response included sensitive header name(s) ({', '.join(sensitive_present)}); "
            "their values were never stored or displayed in this report."
        )
    return items


def _standard_unknowns() -> list[str]:
    return [
        "Server-side implementation language/framework, database technology, and internal "
        "architecture are UNKNOWN — none of this is exposed by a public HTTP response.",
        "Authentication/authorization logic, internal APIs, and any content behind a login are NOT "
        "accessible and are marked NOT_APPLICABLE / UNKNOWN rather than guessed.",
        "Post-render (JavaScript-executed) DOM state is UNKNOWN in this version; see Roadmap Phase 5.",
    ]


async def _fetch_robots(client: SafeAsyncClient, page_url: str) -> Evidence:
    from urllib.parse import urlparse
    parsed = urlparse(page_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        resp, _final, body = await client.safe_get(robots_url, max_bytes=200_000)
        if resp.status_code == 200 and body:
            text = body.decode("utf-8", errors="replace")
            disallow_count = text.lower().count("disallow:")
            sitemap_lines = [l for l in text.splitlines() if l.lower().startswith("sitemap:")]
            return Evidence(
                OBSERVED,
                f"robots.txt found ({len(text)} bytes, {disallow_count} Disallow rule(s), "
                f"{len(sitemap_lines)} Sitemap directive(s) declared).",
                source=robots_url,
            )
        return Evidence(OBSERVED, f"robots.txt request returned HTTP {resp.status_code}.", source=robots_url)
    except SecurityError as e:
        return Evidence(UNKNOWN, f"Could not fetch robots.txt: {e}", source=robots_url)


async def _fetch_sitemap(client: SafeAsyncClient, page_url: str) -> Evidence:
    from urllib.parse import urlparse
    parsed = urlparse(page_url)
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
    try:
        resp, _final, body = await client.safe_get(sitemap_url, max_bytes=1_000_000)
        if resp.status_code == 200 and body:
            url_count = body.count(b"<loc>")
            return Evidence(
                OBSERVED,
                f"sitemap.xml found ({len(body)} bytes, approximately {url_count} <loc> entries).",
                source=sitemap_url,
            )
        return Evidence(OBSERVED, f"sitemap.xml request returned HTTP {resp.status_code}.", source=sitemap_url)
    except SecurityError as e:
        return Evidence(UNKNOWN, f"Could not fetch sitemap.xml: {e}", source=sitemap_url)


# Serve the minimal static frontend (Section 13: static/index.html)
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
