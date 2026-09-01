import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import reporting  # noqa: E402


def _minimal_report_input(job_id="testjob0000000"):
    return {
        "job_id": job_id,
        "target_url": "https://example.com",
        "final_url": "https://example.com/",
        "timestamp_utc": "2026-01-01T00:00:00+00:00",
        "executive_summary": "A test summary.",
        "identity": {"title": "Example", "description": "desc", "canonical_url": None,
                     "language": "en", "generator": None},
        "purpose": "INFERRED test purpose.",
        "motto": {"status": "UNKNOWN", "detail": "No motto found.", "source": None},
        "technology_stack": [{"name": "WordPress", "category": "CMS", "confidence": 0.9, "evidence": ["test"]}],
        "frontend_architecture": "Server-rendered, no framework markers.",
        "html_css_js_inventory": {"css_files_found": 1, "js_files_found": 1, "images_found": 0,
                                   "fonts_found": 0, "icons_found": 0},
        "public_source_inventory": {"summary": "1 file downloaded."},
        "assets": [{"kind": "css", "source_url": "https://example.com/style.css", "local_filename": "0_css.css",
                    "size_bytes": 123, "sha256": "abc", "fetched": True, "note": None}],
        "forms": [],
        "links_and_routes": {"internal": [], "external": [], "internal_count_total": 0, "external_count_total": 0},
        "third_party_services": [],
        "seo_and_structured_data": {"open_graph": {}, "twitter_card": {}, "json_ld": []},
        "http_headers": {"Server": "nginx", "Authorization": "should-be-redacted", "Set-Cookie": "should-be-redacted"},
        "security_observations": {"headers": {"present": {}, "missing": [], "note": "n/a"},
                                   "sensitive_header_names_seen_but_redacted": ["Set-Cookie"]},
        "robots_txt": {"status": "OBSERVED", "detail": "found", "source": "https://example.com/robots.txt"},
        "sitemap_xml": {"status": "UNKNOWN", "detail": "not found", "source": None},
        "performance_and_accessibility_notes": [],
        "unknown_or_private_components": ["Server-side stack is unknown."],
        "limitations": ["Only public content analyzed."],
        "errors": [],
    }


def test_json_report_redacts_sensitive_header_values():
    report = reporting.build_json_report(_minimal_report_input())
    assert report["http_headers"]["Authorization"] == "[REDACTED — never stored in reports]"
    assert report["http_headers"]["Set-Cookie"] == "[REDACTED — never stored in reports]"
    assert report["http_headers"]["Server"] == "nginx"


def test_html_report_renders_without_raw_secret_leaking():
    report = reporting.build_json_report(_minimal_report_input())
    html_out = reporting.render_html_report(report)
    assert "should-be-redacted" not in html_out
    assert "WordPress" in html_out
    assert "Example" in html_out


def test_bundle_contains_report_json_html_and_manifest(tmp_path):
    report = reporting.build_json_report(_minimal_report_input(job_id="bundletest0001"))
    downloaded = tmp_path / "0_css.css"
    downloaded.write_text("body { color: red; }")
    bundle_path = reporting.write_bundle(tmp_path, report, [downloaded])
    assert bundle_path.exists()

    with zipfile.ZipFile(bundle_path) as zf:
        names = set(zf.namelist())
        assert "report.json" in names
        assert "report.html" in names
        assert "manifest.json" in names
        assert "downloads/0_css.css" in names

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["job_id"] == "bundletest0001"
        assert "0_css.css" in manifest["files"]

        json_report = json.loads(zf.read("report.json"))
        assert json_report["job_id"] == "bundletest0001"
        # bundle's JSON report must match what render_html_report was built from
        assert json_report["identity"]["title"] == report["identity"]["title"]
