"""
Orchestrator: crawl → parse → fingerprint → browser → assets → architecture → report → reconstruction.
"""

from __future__ import annotations

import asyncio
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.asset_collector import AssetCollector
from app.browser import render_page, PLAYWRIGHT_AVAILABLE
from app.crawler import Crawler
from app.data_analyzer import (
    analyze_architecture,
    extract_api_endpoints,
    find_json_blobs,
)
from app.fingerprint import detect_technologies
from app.parser import guess_purpose, parse_html
from app.reconstruction import build_reconstruction as make_reconstruction_zip
from app.reporting import build_report, save_reports

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"
RECONSTRUCTIONS_DIR = BASE_DIR / "reconstructions"
DOWNLOADS_DIR = BASE_DIR / "downloads"

# In-memory job store (sufficient for demo / single-process)
_JOBS: Dict[str, Dict[str, Any]] = {}


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    return _JOBS.get(job_id)


def list_jobs() -> List[Dict[str, Any]]:
    return [
        {
            "job_id": jid,
            "status": j.get("status"),
            "url": j.get("url"),
            "created_at": j.get("created_at"),
            "pages_crawled": j.get("report", {}).get("pages_crawled") if j.get("report") else None,
        }
        for jid, j in sorted(_JOBS.items(), key=lambda x: x[1].get("created_at", ""), reverse=True)
    ]


async def analyze(
    job_id: str,
    url: str,
    max_pages: int = 20,
    max_assets: int = 150,
    browser_mode: bool = True,
    build_reconstruction: bool = True,
    depth: int = 2,
) -> Dict[str, Any]:
    """Full pipeline. Updates _JOBS and writes artifacts to disk."""
    created = datetime.now(timezone.utc).isoformat()
    _JOBS[job_id] = {
        "job_id": job_id,
        "status": "running",
        "url": url,
        "created_at": created,
        "message": "Starting analysis…",
        "progress": 0,
        "report": None,
    }

    job_downloads = DOWNLOADS_DIR / job_id
    job_reports = REPORTS_DIR / job_id
    job_recon = RECONSTRUCTIONS_DIR / job_id
    for d in (job_downloads, job_reports, job_recon):
        d.mkdir(parents=True, exist_ok=True)

    try:
        # ── 1. Crawl ──────────────────────────────────────────────
        _JOBS[job_id]["message"] = "Crawling pages…"
        _JOBS[job_id]["progress"] = 10
        crawler = Crawler(url, max_pages=max_pages, depth=depth)
        crawl_result = await crawler.crawl()
        pages = crawl_result.get("pages") or {}

        # ── 2. Parse each page ────────────────────────────────────
        _JOBS[job_id]["message"] = "Parsing HTML & extracting metadata…"
        _JOBS[job_id]["progress"] = 25
        parsed_pages: Dict[str, Any] = {}
        all_html: List[str] = []
        all_headers: List[Dict] = []
        asset_urls: List[str] = []
        ref_map: Dict[str, List[str]] = {}

        for page_url, pdata in pages.items():
            html = pdata.get("html") or ""
            all_html.append(html)
            all_headers.append(pdata.get("headers") or {})
            parsed = parse_html(html, page_url)
            pdata["parsed"] = parsed
            parsed_pages[page_url] = parsed

            # Collect referenced assets
            for img in parsed.get("images") or []:
                u = img.get("url")
                if u:
                    asset_urls.append(u)
                    ref_map.setdefault(u, []).append(page_url)
            for bg in parsed.get("background_images") or []:
                asset_urls.append(bg)
                ref_map.setdefault(bg, []).append(page_url)
            for ss in parsed.get("stylesheets") or []:
                if isinstance(ss, str):
                    asset_urls.append(ss)
                    ref_map.setdefault(ss, []).append(page_url)
            for sc in parsed.get("scripts") or []:
                if sc.get("type") == "external" and sc.get("url"):
                    asset_urls.append(sc["url"])
                    ref_map.setdefault(sc["url"], []).append(page_url)

        # ── 3. Browser rendering (optional) ───────────────────────
        browser_findings: Dict[str, Any] = {"enabled": browser_mode, "playwright_available": PLAYWRIGHT_AVAILABLE}
        loaded_urls: List[str] = []
        if browser_mode:
            _JOBS[job_id]["message"] = "Rendering with browser engine…"
            _JOBS[job_id]["progress"] = 40
            primary = list(pages.keys())[:3]  # render top pages
            for pu in primary:
                br = await render_page(pu)
                browser_findings[pu] = {
                    "title": br.get("title"),
                    "error": br.get("error"),
                    "loaded_count": len(br.get("loaded_urls") or []),
                    "api_candidates": br.get("api_candidates"),
                }
                loaded_urls.extend(br.get("loaded_urls") or [])
                if br.get("rendered_html") and pu in pages:
                    pages[pu]["rendered_html"] = br["rendered_html"]
                    # Re-parse rendered if richer
                    if len(br["rendered_html"] or "") > len(pages[pu].get("html") or ""):
                        parsed_pages[pu] = parse_html(br["rendered_html"], pu)
                # Extra assets from network
                for u in br.get("loaded_urls") or []:
                    if any(u.lower().endswith(ext) for ext in (
                        ".css", ".js", ".mjs", ".png", ".jpg", ".jpeg", ".gif",
                        ".webp", ".svg", ".ico", ".woff", ".woff2", ".ttf",
                    )):
                        asset_urls.append(u)
                        ref_map.setdefault(u, []).append(pu)

        # ── 4. Technology fingerprint ─────────────────────────────
        _JOBS[job_id]["message"] = "Detecting technologies…"
        _JOBS[job_id]["progress"] = 55
        technologies = detect_technologies(all_html, all_headers, loaded_urls)

        # ── 5. Purpose / motto ────────────────────────────────────
        primary_parsed = next(iter(parsed_pages.values()), {})
        purpose = guess_purpose(primary_parsed, technologies)

        # ── 6. APIs & data ────────────────────────────────────────
        _JOBS[job_id]["message"] = "Analyzing APIs & application data…"
        _JOBS[job_id]["progress"] = 65
        combined_html = "\n".join(all_html)
        endpoints = extract_api_endpoints(loaded_urls, combined_html)
        for pu, br in browser_findings.items():
            if isinstance(br, dict):
                for cand in br.get("api_candidates") or []:
                    endpoints.append(cand)
        # de-dupe endpoints
        seen_ep = set()
        unique_eps = []
        for e in endpoints:
            key = e.get("url")
            if key and key not in seen_ep:
                seen_ep.add(key)
                unique_eps.append(e)
        endpoints = unique_eps

        # ── 7. Asset collection ───────────────────────────────────
        _JOBS[job_id]["message"] = "Downloading assets…"
        _JOBS[job_id]["progress"] = 75
        collector = AssetCollector(job_downloads, max_assets=max_assets)
        await collector.collect_many(asset_urls, ref_map)

        # Second pass: extract url() references from downloaded CSS
        from app.parser import extract_css_urls
        extra_from_css = []
        for entry in list(collector.get_manifest()):
            if entry.get("status") != "collected" or entry.get("type") != "css":
                continue
            lp = entry.get("local_path")
            if not lp:
                continue
            css_path = job_downloads / lp
            if css_path.exists():
                try:
                    css_text = css_path.read_text(encoding="utf-8", errors="replace")
                    for u in extract_css_urls(css_text, entry.get("original_url") or url):
                        extra_from_css.append(u)
                        ref_map.setdefault(u, []).append(entry["original_url"])
                except Exception:
                    pass
        if extra_from_css:
            await collector.collect_many(extra_from_css, ref_map)

        asset_manifest = collector.get_manifest()
        url_to_local = collector.url_to_local

        # ── 8. Architecture ───────────────────────────────────────
        architecture = analyze_architecture(pages, asset_manifest, technologies, endpoints)

        # ── 9. Build report ───────────────────────────────────────
        _JOBS[job_id]["message"] = "Generating reports…"
        _JOBS[job_id]["progress"] = 85
        missing = [a["original_url"] for a in asset_manifest if a.get("status") != "collected"]
        report = build_report(
            job_id=job_id,
            original_url=url,
            crawl_result=crawl_result,
            parsed_pages=parsed_pages,
            technologies=technologies,
            purpose=purpose,
            architecture=architecture,
            asset_manifest=asset_manifest,
            endpoints=endpoints,
            browser_findings=browser_findings,
            missing=missing,
        )
        save_reports(job_reports, report)

        # ── 10. Reconstruction ZIP ────────────────────────────────
        zip_path = None
        if build_reconstruction:
            _JOBS[job_id]["message"] = "Building reconstruction project…"
            _JOBS[job_id]["progress"] = 92
            zip_path = make_reconstruction_zip(
                job_dir=job_recon,
                report=report,
                pages=pages,
                url_to_local=url_to_local,
                asset_manifest=asset_manifest,
                original_url=url,
                downloads_dir=job_downloads,
            )
            report["reconstruction_zip"] = str(zip_path)

        # ── Done ──────────────────────────────────────────────────
        _JOBS[job_id].update(
            {
                "status": "completed",
                "message": "Analysis complete",
                "progress": 100,
                "report": report,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "reconstruction_zip": str(zip_path) if zip_path else None,
            }
        )
        # Persist job summary
        (job_reports / "job.json").write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    "status": "completed",
                    "url": url,
                    "pages_crawled": report.get("pages_crawled"),
                    "assets_collected": report.get("reconstruction_status", {}).get("assets_collected"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return _JOBS[job_id]

    except Exception as e:
        tb = traceback.format_exc()
        _JOBS[job_id].update(
            {
                "status": "failed",
                "message": str(e),
                "error": tb,
                "progress": _JOBS[job_id].get("progress", 0),
            }
        )
        (job_reports / "error.txt").write_text(tb, encoding="utf-8")
        return _JOBS[job_id]
