"""
reporting.py
------------
Turns the raw analysis result (a dict assembled in main.py's job runner)
into:
  1. A canonical JSON report (Section 11: "The JSON report should be the
     canonical source for HTML rendering").
  2. A human-readable HTML report rendered FROM that JSON.
  3. A public-resource bundle (zip) containing whatever public HTML/CSS/JS
     assets were actually downloaded, plus a manifest.

No network calls happen in this module — it is pure presentation over data
that analyzer.py already produced.
"""
from __future__ import annotations

import html as html_escape_mod
import json
import zipfile
from pathlib import Path
from typing import Any


def build_json_report(data: dict) -> dict:
    """
    data is the raw internal analysis dict. This function's job is mostly to
    make sure the shape is stable/canonical and to strip anything that must
    never appear in a report (defense in depth on top of security.py's
    header scrubbing).
    """
    report = {
        "sitescope_report_version": "1.0",
        "job_id": data["job_id"],
        "target_url": data["target_url"],
        "final_url": data["final_url"],
        "timestamp_utc": data["timestamp_utc"],
        "executive_summary": data["executive_summary"],
        "identity": data["identity"],
        "purpose": data["purpose"],
        "motto": data["motto"],
        "technology_stack": data["technology_stack"],
        "frontend_architecture": data["frontend_architecture"],
        "html_css_js_inventory": data["html_css_js_inventory"],
        "public_source_inventory": data["public_source_inventory"],
        "assets": data["assets"],
        "forms": data["forms"],
        "links_and_routes": data["links_and_routes"],
        "third_party_services": data["third_party_services"],
        "seo_and_structured_data": data["seo_and_structured_data"],
        "http_headers": data["http_headers"],
        "security_observations": data["security_observations"],
        "robots_txt": data["robots_txt"],
        "sitemap_xml": data["sitemap_xml"],
        "performance_and_accessibility_notes": data["performance_and_accessibility_notes"],
        "unknown_or_private_components": data["unknown_or_private_components"],
        "limitations": data["limitations"],
        "errors": data.get("errors", []),
    }
    # Defense in depth: never let a raw cookie/authorization value leak
    # through even if some upstream code forgot to scrub it.
    _scrub_recursive(report)
    return report


_FORBIDDEN_KEY_FRAGMENTS = ("authorization", "set-cookie", "proxy-authenticate", "api-key", "x-api-key")


def _scrub_recursive(obj: Any):
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            if any(f in k.lower() for f in _FORBIDDEN_KEY_FRAGMENTS):
                obj[k] = "[REDACTED — never stored in reports]"
            else:
                _scrub_recursive(obj[k])
    elif isinstance(obj, list):
        for item in obj:
            _scrub_recursive(item)


def _esc(val: Any) -> str:
    return html_escape_mod.escape(str(val)) if val is not None else "<span class=\"unknown\">Unknown</span>"


def _badge(status: str) -> str:
    cls = {
        "OBSERVED": "badge observed",
        "INFERRED": "badge inferred",
        "UNKNOWN": "badge unknown",
        "NOT_APPLICABLE": "badge na",
    }.get(status, "badge unknown")
    return f'<span class="{cls}">{status}</span>'


def render_html_report(report: dict) -> str:
    """Render the canonical JSON report into a standalone HTML document."""
    tech_rows = "".join(
        f"""<tr>
              <td>{_esc(t['name'])}</td>
              <td>{_esc(t['category'])}</td>
              <td>{t['confidence']*100:.0f}%</td>
              <td class="evidence-cell">{"<br>".join(_esc(e) for e in t['evidence'])}</td>
            </tr>"""
        for t in report["technology_stack"]
    ) or '<tr><td colspan="4" class="muted">No technologies fingerprinted with sufficient confidence.</td></tr>'

    forms_html = "".join(
        f"""<div class="card">
              <div><strong>Action:</strong> {_esc(f['action'])} &nbsp; <strong>Method:</strong> {_esc(f['method'])}</div>
              <ul>{"".join(f"<li>{_esc(fd.get('name') or '(unnamed)')} — {_esc(fd.get('type'))}{' (required)' if fd.get('required') else ''}</li>" for fd in f['fields'])}</ul>
            </div>"""
        for f in report["forms"]
    ) or '<p class="muted">No forms observed.</p>'

    assets = report["assets"]
    asset_rows = "".join(
        f"<tr><td>{_esc(a['kind'])}</td><td class='url-cell'>{_esc(a['source_url'])}</td>"
        f"<td>{_esc(a['size_bytes']) if a['size_bytes'] is not None else '—'}</td>"
        f"<td>{'yes' if a['fetched'] else 'no'}</td></tr>"
        for a in assets[:200]
    ) or '<tr><td colspan="4" class="muted">No assets recorded.</td></tr>'

    internal_links = report["links_and_routes"]["internal"]
    external_links = report["links_and_routes"]["external"]

    sec_headers = report["security_observations"]["headers"]
    sec_present = "".join(f"<li><code>{_esc(k)}</code>: {_esc(v)}</li>" for k, v in sec_headers["present"].items()) or "<li class='muted'>None observed</li>"
    sec_missing = "".join(f"<li><code>{_esc(m)}</code></li>" for m in sec_headers["missing"]) or "<li class='muted'>None</li>"

    third_party = "".join(f"<li>{_esc(s)}</li>" for s in report["third_party_services"]) or "<li class='muted'>None detected</li>"

    json_ld_block = json.dumps(report["seo_and_structured_data"].get("json_ld", []), indent=2)[:4000]

    limitations = "".join(f"<li>{_esc(l)}</li>" for l in report["limitations"])
    unknowns = "".join(f"<li>{_esc(u)}</li>" for u in report["unknown_or_private_components"])
    errors = "".join(f"<li>{_esc(e)}</li>" for e in report.get("errors", [])) or "<li class='muted'>None</li>"

    motto = report["motto"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SiteScope Report — {_esc(report['final_url'])}</title>
<style>
  :root {{
    --ink: #1b1f23; --paper: #fbfaf7; --line: #d8d3c8; --accent: #2f5d50;
    --observed: #2f5d50; --inferred: #8a6d1f; --unknown: #8a3b2f; --na: #6b6b6b;
    --mono: 'IBM Plex Mono', 'SF Mono', Consolas, monospace;
    --serif: 'Iowan Old Style', 'Georgia', serif;
    --sans: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink); font-family:var(--sans); line-height:1.5; }}
  header {{ padding:2.5rem 2rem 1.5rem; border-bottom:1px solid var(--line); }}
  header h1 {{ font-family:var(--serif); font-size:1.9rem; margin:0 0 .25rem; }}
  header .meta {{ color:#555; font-size:.9rem; }}
  main {{ max-width:1000px; margin:0 auto; padding:2rem; }}
  section {{ margin-bottom:2.5rem; }}
  h2 {{ font-family:var(--serif); font-size:1.3rem; border-bottom:1px solid var(--line); padding-bottom:.4rem; }}
  table {{ width:100%; border-collapse:collapse; font-size:.88rem; }}
  th, td {{ text-align:left; padding:.5rem .6rem; border-bottom:1px solid #ece8dd; vertical-align:top; }}
  th {{ font-size:.75rem; text-transform:uppercase; letter-spacing:.03em; color:#666; }}
  .url-cell {{ word-break:break-all; font-family:var(--mono); font-size:.78rem; }}
  .evidence-cell {{ font-size:.8rem; color:#444; }}
  .muted {{ color:#888; font-style:italic; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:6px; padding:1rem; margin-bottom:.75rem; }}
  .badge {{ display:inline-block; padding:.15rem .55rem; border-radius:99px; font-size:.72rem; font-weight:600; color:#fff; }}
  .badge.observed {{ background:var(--observed); }}
  .badge.inferred {{ background:var(--inferred); }}
  .badge.unknown {{ background:var(--unknown); }}
  .badge.na {{ background:var(--na); }}
  code {{ font-family:var(--mono); background:#efece2; padding:.1rem .3rem; border-radius:3px; font-size:.85em; }}
  pre {{ background:#20241f; color:#e7e4d8; padding:1rem; border-radius:6px; overflow-x:auto; font-size:.78rem; }}
  ul {{ margin:.3rem 0; padding-left:1.3rem; }}
  .cols {{ display:grid; grid-template-columns:1fr 1fr; gap:1.5rem; }}
  .exec-summary {{ font-size:1.02rem; }}
  footer {{ padding:2rem; text-align:center; color:#888; font-size:.8rem; border-top:1px solid var(--line); }}
</style>
</head>
<body>
<header>
  <h1>SiteScope Report</h1>
  <div class="meta">
    Target: <code>{_esc(report['target_url'])}</code> &nbsp;·&nbsp;
    Final URL: <code>{_esc(report['final_url'])}</code> &nbsp;·&nbsp;
    Generated: {_esc(report['timestamp_utc'])}
  </div>
</header>
<main>

  <section>
    <h2>Executive Summary</h2>
    <p class="exec-summary">{_esc(report['executive_summary'])}</p>
  </section>

  <section>
    <h2>Identity &amp; Purpose</h2>
    <div class="cols">
      <div>
        <p><strong>Title:</strong> {_esc(report['identity'].get('title'))}</p>
        <p><strong>Description:</strong> {_esc(report['identity'].get('description'))}</p>
        <p><strong>Canonical URL:</strong> {_esc(report['identity'].get('canonical_url'))}</p>
        <p><strong>Language:</strong> {_esc(report['identity'].get('language'))}</p>
        <p><strong>Declared generator:</strong> {_esc(report['identity'].get('generator'))}</p>
      </div>
      <div>
        <p><strong>Purpose / audience (inferred):</strong><br>{_esc(report['purpose'])}</p>
        <p><strong>Motto:</strong> {_badge(motto['status'])}<br>{_esc(motto['detail'])}</p>
      </div>
    </div>
  </section>

  <section>
    <h2>Technology Stack</h2>
    <table>
      <thead><tr><th>Technology</th><th>Category</th><th>Confidence</th><th>Evidence</th></tr></thead>
      <tbody>{tech_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>Frontend Architecture</h2>
    <p>{_esc(report['frontend_architecture'])}</p>
  </section>

  <section>
    <h2>Public Source &amp; Asset Inventory</h2>
    <p class="muted">{_esc(report['public_source_inventory'].get('summary'))}</p>
    <table>
      <thead><tr><th>Kind</th><th>Source URL</th><th>Size (bytes)</th><th>Downloaded</th></tr></thead>
      <tbody>{asset_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>Forms</h2>
    {forms_html}
  </section>

  <section>
    <h2>Links &amp; Routes</h2>
    <div class="cols">
      <div>
        <p><strong>Internal links</strong> ({report['links_and_routes']['internal_count_total']} total, showing up to {len(internal_links)})</p>
        <ul>{''.join(f'<li class="url-cell">{_esc(l)}</li>' for l in internal_links[:40])}</ul>
      </div>
      <div>
        <p><strong>External links</strong> ({report['links_and_routes']['external_count_total']} total, showing up to {len(external_links)})</p>
        <ul>{''.join(f'<li class="url-cell">{_esc(l)}</li>' for l in external_links[:40])}</ul>
      </div>
    </div>
  </section>

  <section>
    <h2>Third-Party Services</h2>
    <ul>{third_party}</ul>
  </section>

  <section>
    <h2>SEO &amp; Structured Data</h2>
    <p><strong>Open Graph:</strong> {_esc(json.dumps(report['seo_and_structured_data'].get('open_graph', {})))}</p>
    <p><strong>Twitter Card:</strong> {_esc(json.dumps(report['seo_and_structured_data'].get('twitter_card', {})))}</p>
    <p><strong>JSON-LD (truncated):</strong></p>
    <pre>{_esc(json_ld_block)}</pre>
  </section>

  <section>
    <h2>HTTP &amp; Security Headers</h2>
    <div class="cols">
      <div><p><strong>Security headers present</strong></p><ul>{sec_present}</ul></div>
      <div><p><strong>Security headers missing</strong></p><ul>{sec_missing}</ul></div>
    </div>
    <p class="muted">{_esc(sec_headers['note'])}</p>
  </section>

  <section>
    <h2>robots.txt &amp; sitemap.xml</h2>
    <p><strong>robots.txt:</strong> {_badge(report['robots_txt']['status'])} — {_esc(report['robots_txt']['detail'])}</p>
    <p><strong>sitemap.xml:</strong> {_badge(report['sitemap_xml']['status'])} — {_esc(report['sitemap_xml']['detail'])}</p>
  </section>

  <section>
    <h2>Performance &amp; Accessibility Notes</h2>
    <ul>{''.join(f"<li>{_esc(n)}</li>" for n in report['performance_and_accessibility_notes']) or '<li class="muted">None recorded.</li>'}</ul>
  </section>

  <section>
    <h2>Unknown / Private Components</h2>
    <ul>{unknowns or '<li class="muted">None flagged.</li>'}</ul>
  </section>

  <section>
    <h2>Limitations</h2>
    <ul>{limitations}</ul>
  </section>

  <section>
    <h2>Errors Encountered</h2>
    <ul>{errors}</ul>
  </section>

</main>
<footer>
  Generated by SiteScope — evidence-driven public website analysis. Not a source-code extractor;
  never claims to recover private backend logic, databases, or credentials.
</footer>
</body>
</html>"""


def write_bundle(job_dir: Path, report: dict, downloaded_files: list[Path]) -> Path:
    """
    Create the downloadable bundle: report.json, report.html, manifest.json,
    and any actually-downloaded public assets under downloads/.
    """
    bundle_path = job_dir / f"{report['job_id']}_bundle.zip"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("report.json", json.dumps(report, indent=2))
        zf.writestr("report.html", render_html_report(report))
        manifest = {
            "job_id": report["job_id"],
            "target_url": report["target_url"],
            "final_url": report["final_url"],
            "files": [f.name for f in downloaded_files],
            "note": (
                "Only publicly delivered resources that were actually downloaded "
                "are included here. No private backend source is present."
            ),
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        for f in downloaded_files:
            if f.exists():
                zf.write(f, arcname=f"downloads/{f.name}")
    return bundle_path
