import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import analyzer  # noqa: E402


WP_HTML = """
<html><head>
<meta name="generator" content="WordPress 6.4">
<link rel="stylesheet" href="/wp-content/themes/mytheme/style.css">
</head><body><script src="/wp-includes/js/jquery/jquery.js"></script></body></html>
"""

NEXT_HTML = """
<html><head></head><body>
<script id="__NEXT_DATA__" type="application/json">{"props":{}}</script>
<script src="/_next/static/chunks/main.js"></script>
</body></html>
"""

WEAK_HTML = "<html><head></head><body><p>Just a plain page with no special markers.</p></body></html>"


def test_strong_fingerprint_wordpress():
    findings = analyzer.fingerprint_technologies(WP_HTML, {}, "https://example.com")
    names = [f.name for f in findings]
    assert "WordPress" in names
    wp = next(f for f in findings if f.name == "WordPress")
    assert wp.confidence >= 0.7  # multiple corroborating signals -> high confidence


def test_strong_fingerprint_nextjs():
    findings = analyzer.fingerprint_technologies(NEXT_HTML, {}, "https://example.com")
    names = [f.name for f in findings]
    assert "Next.js" in names


def test_weak_or_absent_fingerprint_on_plain_page():
    findings = analyzer.fingerprint_technologies(WEAK_HTML, {}, "https://example.com")
    # A plain page with no markers should not produce confident false positives
    assert all(f.confidence < 0.9 for f in findings) or len(findings) == 0


def test_header_based_fingerprint_cloudflare():
    findings = analyzer.fingerprint_technologies("<html></html>", {"cf-ray": "abc123"}, "https://example.com")
    names = [f.name for f in findings]
    assert "Cloudflare" in names


def test_metadata_extraction_basic():
    html = """
    <html lang="en"><head>
      <title>Example Site</title>
      <meta name="description" content="A short description.">
      <meta property="og:title" content="Example OG Title">
      <link rel="canonical" href="https://example.com/">
    </head><body><h1>Welcome</h1></body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    meta = analyzer.extract_metadata(soup)
    assert meta["title"] == "Example Site"
    assert meta["description"] == "A short description."
    assert meta["open_graph"]["title"] == "Example OG Title"
    assert meta["canonical_url"] == "https://example.com/"
    assert meta["language"] == "en"
    assert "Welcome" in meta["headings_sample"]


def test_malformed_json_ld_does_not_crash():
    html = """
    <html><head>
      <script type="application/ld+json">{ this is not valid json </script>
    </head><body></body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    meta = analyzer.extract_metadata(soup)
    assert len(meta["json_ld"]) == 1
    assert meta["json_ld"][0].get("_parse_error") is True


def test_motto_detected_from_tagline_class():
    html = '<html><body><div class="site-tagline">Great things, simply made.</div></body></html>'
    soup = BeautifulSoup(html, "lxml")
    meta = analyzer.extract_metadata(soup)
    ev = analyzer.detect_motto(soup, meta)
    assert ev.status == analyzer.OBSERVED
    assert "Great things, simply made." in ev.detail


def test_missing_motto_reports_unknown_or_inferred():
    html = "<html><head></head><body><p>No slogan here at all, just regular long-form text.</p></body></html>"
    soup = BeautifulSoup(html, "lxml")
    meta = analyzer.extract_metadata(soup)
    ev = analyzer.detect_motto(soup, meta)
    assert ev.status in (analyzer.UNKNOWN, analyzer.INFERRED)
    assert "fabricate" not in ev.detail.lower()  # sanity: we never claim a fake slogan


def test_forms_extraction():
    html = """
    <form action="/subscribe" method="post">
      <input type="email" name="email" required>
      <input type="submit" value="Go">
    </form>
    """
    soup = BeautifulSoup(html, "lxml")
    forms = analyzer.extract_forms(soup, "https://example.com/page")
    assert len(forms) == 1
    assert forms[0]["method"] == "POST"
    assert forms[0]["action"] == "https://example.com/subscribe"
    email_field = next(f for f in forms[0]["fields"] if f["name"] == "email")
    assert email_field["required"] is True


def test_links_split_internal_external():
    html = """
    <a href="/about">About</a>
    <a href="https://external.example/page">External</a>
    <a href="javascript:void(0)">JS link (ignored)</a>
    <a href="#section">Anchor (ignored)</a>
    """
    soup = BeautifulSoup(html, "lxml")
    links = analyzer.extract_links(soup, "https://example.com/")
    assert "https://example.com/about" in links["internal"]
    assert "https://external.example/page" in links["external"]
    assert links["internal_count_total"] == 1
    assert links["external_count_total"] == 1


def test_security_header_summary_present_and_missing():
    headers = {"content-security-policy": "default-src 'self'", "server": "nginx"}
    summary = analyzer.summarize_security_headers(headers)
    assert "content-security-policy" in summary["present"]
    assert "strict-transport-security" in summary["missing"]
