"""
Generate JSON + HTML technical reports and report bundles.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def build_report(
    job_id: str,
    original_url: str,
    crawl_result: Dict,
    parsed_pages: Dict[str, Any],
    technologies: List[Dict],
    purpose: Dict,
    architecture: Dict,
    asset_manifest: List[Dict],
    endpoints: List[Dict],
    browser_findings: Dict,
    missing: List[str],
) -> Dict[str, Any]:
    pages_summary = []
    for url, p in (parsed_pages or {}).items():
        pages_summary.append(
            {
                "url": url,
                "title": p.get("title"),
                "description": (p.get("description") or "")[:200],
                "forms": len(p.get("forms") or []),
                "images": len(p.get("images") or []),
                "scripts": len(p.get("scripts") or []),
            }
        )

    report = {
        "job_id": job_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "website_url": original_url,
        "final_url": crawl_result.get("start_url"),
        "executive_summary": (
            f"Analyzed {crawl_result.get('pages_crawled', 0)} page(s) from {original_url}. "
            f"Detected {len(technologies)} technology signal(s). "
            f"Collected {sum(1 for a in asset_manifest if a.get('status')=='collected')} assets. "
            f"Purpose inferred as: {purpose.get('inferred_positioning', 'N/A')}."
        ),
        "purpose": purpose,
        "technologies": technologies,
        "frontend_architecture": architecture,
        "backend_architecture": {
            "note": "Backend material is included only when authorized/supplied. "
            "Below are client-visible endpoints only.",
            "client_visible_endpoints": endpoints,
        },
        "pages_and_routes": pages_summary,
        "pages_crawled": crawl_result.get("pages_crawled", 0),
        "html_css_js_inventory": {
            "pages": list((parsed_pages or {}).keys()),
            "asset_types": {},
        },
        "images_and_assets": [
            {
                "url": a.get("original_url"),
                "local": a.get("local_path"),
                "type": a.get("type"),
                "status": a.get("status"),
            }
            for a in asset_manifest
        ],
        "api_endpoints": endpoints,
        "third_party_services": [t for t in technologies if t.get("name") in (
            "Google Analytics", "Google Tag Manager", "Cloudflare", "Stripe",
            "PayPal", "Hotjar", "Intercom", "HubSpot", "Segment", "Sentry",
            "Google Fonts", "Font Awesome",
        )],
        "metadata_and_structured_data": {
            url: {
                "title": p.get("title"),
                "open_graph": p.get("open_graph"),
                "json_ld": p.get("json_ld"),
            }
            for url, p in (parsed_pages or {}).items()
        },
        "browser_rendered_findings": browser_findings,
        "resource_relationship_map": [
            {
                "original_url": a.get("original_url"),
                "local_path": a.get("local_path"),
                "referenced_by": a.get("referenced_by"),
                "status": a.get("status"),
            }
            for a in asset_manifest
        ],
        "collected_file_manifest": asset_manifest,
        "reconstruction_status": {
            "assets_collected": sum(1 for a in asset_manifest if a.get("status") == "collected"),
            "assets_failed": sum(1 for a in asset_manifest if a.get("status") == "failed"),
            "missing_resources": missing,
        },
        "deployment_instructions": (
            "1. Unzip the reconstruction package.\n"
            "2. Run `npm install` if package.json lists dependencies.\n"
            "3. Copy `.env.example` → `.env` and fill required values.\n"
            "4. Serve static files (`npx serve public` or open HTML pages).\n"
            "5. Review deployment/deployment.md for missing services."
        ),
        "evidence_and_confidence": {
            "tech_detection": "Pattern matching on HTML, headers, and network URLs with confidence levels.",
            "purpose": "Inferred from title, description, headings, and structured data; explicit motto only when found.",
        },
        "asset_manifest": asset_manifest,
        "architecture": architecture,
    }

    # fill asset type counts
    counts: Dict[str, int] = {}
    for a in asset_manifest:
        t = a.get("type", "other")
        counts[t] = counts.get(t, 0) + 1
    report["html_css_js_inventory"]["asset_types"] = counts
    return report


def render_html_report(report: Dict[str, Any]) -> str:
    techs = report.get("technologies") or []
    tech_rows = "".join(
        f"<tr><td>{t.get('name')}</td><td>{t.get('confidence')}</td>"
        f"<td><code>{', '.join(t.get('evidence') or [])}</code></td></tr>"
        for t in techs
    )
    pages = report.get("pages_and_routes") or []
    page_rows = "".join(
        f"<tr><td><a href='{p.get('url')}'>{p.get('url')}</a></td>"
        f"<td>{p.get('title') or ''}</td><td>{p.get('forms', 0)}</td>"
        f"<td>{p.get('images', 0)}</td></tr>"
        for p in pages
    )
    purpose = report.get("purpose") or {}
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Reverse Engineering Report — {report.get('website_url')}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
    h1, h2 {{ color: #0f172a; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
    th, td {{ border: 1px solid #e2e8f0; padding: 0.5rem 0.75rem; text-align: left; }}
    th {{ background: #f1f5f9; }}
    code {{ background: #f1f5f9; padding: 0.1rem 0.3rem; border-radius: 3px; font-size: 0.9em; }}
    .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 999px; background: #dbeafe; color: #1e40af; font-size: 0.85em; }}
    .summary {{ background: #f8fafc; border-left: 4px solid #3b82f6; padding: 1rem; margin: 1rem 0; }}
  </style>
</head>
<body>
  <h1>Website Reverse Engineering Report</h1>
  <p><strong>URL:</strong> <a href="{report.get('website_url')}">{report.get('website_url')}</a></p>
  <p><strong>Generated:</strong> {report.get('generated_at')}</p>
  <p><span class="badge">Job {report.get('job_id')}</span></p>

  <div class="summary">
    <h2>Executive Summary</h2>
    <p>{report.get('executive_summary')}</p>
  </div>

  <h2>Purpose &amp; Motto</h2>
  <ul>
    <li><strong>Title:</strong> {purpose.get('title') or '—'}</li>
    <li><strong>Description:</strong> {purpose.get('description') or '—'}</li>
    <li><strong>Explicit motto/slogan:</strong> {purpose.get('explicit_motto_or_slogan') or '(none found)'}</li>
    <li><strong>Inferred positioning:</strong> {purpose.get('inferred_positioning') or '—'}</li>
  </ul>

  <h2>Technology Stack</h2>
  <table>
    <thead><tr><th>Name</th><th>Confidence</th><th>Evidence</th></tr></thead>
    <tbody>{tech_rows or '<tr><td colspan="3">None detected</td></tr>'}</tbody>
  </table>

  <h2>Pages &amp; Routes</h2>
  <table>
    <thead><tr><th>URL</th><th>Title</th><th>Forms</th><th>Images</th></tr></thead>
    <tbody>{page_rows or '<tr><td colspan="4">None</td></tr>'}</tbody>
  </table>

  <h2>Assets</h2>
  <p>Collected: {report.get('reconstruction_status', {}).get('assets_collected', 0)} ·
     Failed: {report.get('reconstruction_status', {}).get('assets_failed', 0)}</p>

  <h2>API Endpoints (client-visible)</h2>
  <ul>
    {''.join(f"<li><code>{e.get('url')}</code> ({e.get('source')})</li>" for e in (report.get('api_endpoints') or [])[:30]) or '<li>None discovered</li>'}
  </ul>

  <h2>Deployment</h2>
  <pre>{report.get('deployment_instructions')}</pre>

  <hr/>
  <p style="color:#64748b;font-size:0.9em;">Generated by Website Reverse Engineering platform · College Project / Expo</p>
</body>
</html>"""


def save_reports(report_dir: Path, report: Dict[str, Any]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (report_dir / "report.html").write_text(render_html_report(report), encoding="utf-8")

    # Bundle
    bundle = report_dir / "report_bundle.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(report_dir / "report.json", "report.json")
        zf.write(report_dir / "report.html", "report.html")
        if (report_dir / "manifests").exists():
            for f in (report_dir / "manifests").glob("*.json"):
                zf.write(f, f"manifests/{f.name}")
