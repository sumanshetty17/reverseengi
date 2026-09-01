"""
analyzer.py
-----------
The fetching, parsing, and inference engine.

Design principle (Section 2 of the spec): every fact this module produces is
tagged as one of:
    OBSERVED  - directly present in publicly delivered bytes (HTML, headers,
                robots.txt, sitemap.xml, ...)
    INFERRED  - a conclusion drawn from observed signals (e.g. "likely
                Next.js" from a __NEXT_DATA__ script tag)
    UNKNOWN   - we could not determine this from what was publicly served
    NOT_APPLICABLE - doesn't apply to this target (e.g. no forms present)

Nothing in this module ever claims to have recovered private backend source,
databases, credentials, or protected APIs. It only ever reasons about bytes
that a public, unauthenticated client actually received.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from . import security
from .security import DEFAULT_LIMITS, Limits, SecurityError


# ---------------------------------------------------------------------------
# Evidence primitives
# ---------------------------------------------------------------------------
OBSERVED = "OBSERVED"
INFERRED = "INFERRED"
UNKNOWN = "UNKNOWN"
NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass
class Evidence:
    status: str                    # OBSERVED | INFERRED | UNKNOWN | NOT_APPLICABLE
    detail: str                    # human-readable evidence / reasoning
    source: Optional[str] = None   # e.g. "meta[name=generator]", "HTTP header Server"

    def to_dict(self) -> dict:
        return {"status": self.status, "detail": self.detail, "source": self.source}


@dataclass
class TechFinding:
    name: str
    category: str                  # e.g. "CMS", "Framework", "CDN/Hosting", "Analytics"
    confidence: float              # 0.0 - 1.0
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence,
        }


@dataclass
class ResourceRecord:
    kind: str            # html | css | js | image | font | icon | other
    source_url: str
    local_filename: Optional[str] = None
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None
    fetched: bool = False
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "source_url": self.source_url,
            "local_filename": self.local_filename,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "fetched": self.fetched,
            "note": self.note,
        }


class SafeAsyncClient:
    """
    httpx.AsyncClient wrapper that re-validates every redirect hop against
    security.py before following it, enforces byte caps while streaming, and
    never forwards sensitive headers.
    """

    def __init__(self, limits: Limits = DEFAULT_LIMITS):
        self.limits = limits
        self._client = httpx.AsyncClient(
            follow_redirects=False,   # we handle redirects manually to re-check each hop
            timeout=httpx.Timeout(
                connect=limits.connect_timeout_s,
                read=limits.read_timeout_s,
                write=limits.read_timeout_s,
                pool=limits.total_timeout_s,
            ),
            headers={"User-Agent": limits.user_agent},
        )

    async def aclose(self):
        await self._client.aclose()

    async def safe_get(self, url: str, max_bytes: Optional[int] = None) -> tuple[httpx.Response, str, bytes]:
        """
        Perform a GET with manual, re-validated redirect following.
        Returns (final_response, final_url, body_bytes_truncated_if_needed).
        Raises SecurityError if any hop fails validation.
        """
        limits = self.limits
        cap = max_bytes or limits.max_page_bytes
        current_url = url
        for hop in range(limits.max_redirects + 1):
            security.validate_url(current_url)  # re-check EVERY hop, including the first
            req_headers = security.scrub_request_headers({})
            async with self._client.stream("GET", current_url, headers=req_headers) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise SecurityError("Redirect response missing Location header.")
                    current_url = urljoin(current_url, location)
                    continue
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > cap:
                        break
                # materialize response body for downstream use
                return resp, current_url, bytes(body[:cap])
        raise SecurityError(f"Too many redirects (> {limits.max_redirects}).")


# ---------------------------------------------------------------------------
# Technology fingerprinting signals (Section 7)
# ---------------------------------------------------------------------------
def fingerprint_technologies(html: str, headers: dict, final_url: str) -> list[TechFinding]:
    findings: dict[str, TechFinding] = {}

    def add(name: str, category: str, confidence: float, evidence: str):
        if name in findings:
            f = findings[name]
            f.confidence = min(1.0, f.confidence + confidence * 0.4)  # corroboration bump
            f.evidence.append(evidence)
        else:
            findings[name] = TechFinding(name=name, category=category, confidence=confidence, evidence=[evidence])

    lower_html = html.lower()
    server_header = headers.get("server", "")
    powered_by = headers.get("x-powered-by", "")

    # --- Server / infra headers ---
    if server_header:
        add(server_header.split("/")[0].strip(), "Server/Infra", 0.6, f"HTTP header Server: {server_header}")
    if powered_by:
        add(powered_by, "Server/Infra", 0.6, f"HTTP header X-Powered-By: {powered_by}")
    if "cf-ray" in headers or "cf-cache-status" in headers:
        add("Cloudflare", "CDN/Hosting", 0.7, "Cloudflare-specific response headers present")
    if "x-vercel-id" in headers or "x-vercel-cache" in headers:
        add("Vercel", "CDN/Hosting", 0.7, "Vercel-specific response headers present")
    if "x-amz-cf-id" in headers:
        add("Amazon CloudFront", "CDN/Hosting", 0.7, "X-Amz-Cf-Id header present")
    if "x-github-request-id" in headers:
        add("GitHub Pages", "CDN/Hosting", 0.5, "X-GitHub-Request-Id header present")

    # --- CMS / platform markers ---
    if "/wp-content/" in lower_html or "/wp-includes/" in lower_html:
        add("WordPress", "CMS", 0.85, "wp-content/wp-includes paths found in HTML")
    if re.search(r'name=["\']generator["\']\s+content=["\']wordpress', lower_html):
        add("WordPress", "CMS", 0.9, "generator meta tag mentions WordPress")
    if "cdn.shopify.com" in lower_html or "shopify" in lower_html:
        add("Shopify", "E-commerce/CMS", 0.8, "Shopify CDN reference or literal mention found")
    if re.search(r'name=["\']generator["\']\s+content=["\']wix', lower_html):
        add("Wix", "CMS", 0.85, "generator meta tag mentions Wix")
    if "cdn.squarespace.com" in lower_html or "squarespace" in lower_html:
        add("Squarespace", "CMS", 0.75, "Squarespace CDN or literal mention found")
    if "webflow.com" in lower_html or "wf-" in lower_html and "webflow" in lower_html:
        add("Webflow", "CMS", 0.6, "Webflow reference found")
    if "duda" in lower_html and "dmbody" in lower_html:
        add("Duda", "CMS", 0.6, "Duda-specific DOM markers found")

    # --- JS frameworks ---
    if "__next_data__" in lower_html or "/_next/static/" in lower_html:
        add("Next.js", "Framework", 0.85, "__NEXT_DATA__ script or /_next/static/ path found")
    if "data-reactroot" in lower_html or "react-dom" in lower_html:
        add("React", "Framework", 0.6, "React-specific DOM markers or bundle references found")
    if "ng-version" in lower_html or "__nghost" in lower_html:
        add("Angular", "Framework", 0.75, "Angular-specific DOM markers found")
    if "data-v-app" in lower_html or "__nuxt" in lower_html:
        add("Vue.js / Nuxt", "Framework", 0.7, "Vue/Nuxt-specific DOM markers found")
    if "__gatsby" in lower_html or "gatsby-" in lower_html:
        add("Gatsby", "Framework", 0.7, "Gatsby-specific DOM markers found")
    if "svelte-" in lower_html:
        add("Svelte", "Framework", 0.5, "Svelte-style scoped class names found")

    # --- Analytics / third-party SDKs ---
    third_party_map = {
        "www.google-analytics.com": ("Google Analytics", "Analytics"),
        "googletagmanager.com": ("Google Tag Manager", "Analytics"),
        "connect.facebook.net": ("Meta Pixel", "Analytics"),
        "cdn.segment.com": ("Segment", "Analytics"),
        "hotjar.com": ("Hotjar", "Analytics"),
        "js.stripe.com": ("Stripe", "Payments"),
        "js.intercomcdn.com": ("Intercom", "Customer Support"),
        "widget.intercom.io": ("Intercom", "Customer Support"),
        "cdn.jsdelivr.net": ("jsDelivr CDN", "CDN/Hosting"),
        "cdnjs.cloudflare.com": ("cdnjs", "CDN/Hosting"),
        "fonts.googleapis.com": ("Google Fonts", "Fonts"),
        "use.typekit.net": ("Adobe Fonts (Typekit)", "Fonts"),
        "recaptcha": ("Google reCAPTCHA", "Security/Bot-protection"),
        "sentry.io": ("Sentry", "Error Monitoring"),
        "cdn.optimizely.com": ("Optimizely", "A/B Testing"),
    }
    for needle, (name, category) in third_party_map.items():
        if needle in lower_html:
            add(name, category, 0.5, f"Reference to '{needle}' found in page HTML/scripts")

    # --- generator meta (generic) ---
    m = re.search(r'name=["\']generator["\']\s+content=["\']([^"\']+)', lower_html)
    if m:
        gen_value = m.group(1).strip()[:60]
        # If this generator value names a platform we already detected via a
        # stronger signal (e.g. WordPress path markers), fold it in as
        # corroborating evidence instead of creating a near-duplicate entry.
        merged = False
        for existing_name in list(findings.keys()):
            if existing_name.lower() in gen_value.lower():
                add(existing_name, findings[existing_name].category, 0.3,
                    f"meta[name=generator] content confirms: '{gen_value}'")
                merged = True
                break
        if not merged:
            add(gen_value.title(), "Declared Generator", 0.9, "meta[name=generator] content attribute")

    # De-duplicate against the same host claiming both a CDN and its own name
    return sorted(findings.values(), key=lambda f: (-f.confidence, f.name.lower()))


# ---------------------------------------------------------------------------
# Metadata / purpose / motto extraction (Section 8)
# ---------------------------------------------------------------------------
def extract_metadata(soup: BeautifulSoup) -> dict:
    def meta(name=None, prop=None):
        if name:
            tag = soup.find("meta", attrs={"name": re.compile(f"^{re.escape(name)}$", re.I)})
        else:
            tag = soup.find("meta", attrs={"property": re.compile(f"^{re.escape(prop)}$", re.I)})
        return tag.get("content").strip() if tag and tag.get("content") else None

    title_tag = soup.find("title")
    canonical_tag = soup.find("link", rel=lambda v: v and "canonical" in v.lower() if v else False)
    html_tag = soup.find("html")

    og = {
        "title": meta(prop="og:title"),
        "description": meta(prop="og:description"),
        "type": meta(prop="og:type"),
        "site_name": meta(prop="og:site_name"),
        "image": meta(prop="og:image"),
    }
    twitter = {
        "card": meta(name="twitter:card"),
        "title": meta(name="twitter:title"),
        "description": meta(name="twitter:description"),
    }

    headings = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2"])][:15]
    nav_labels = [a.get_text(strip=True) for a in soup.select("nav a") if a.get_text(strip=True)][:25]

    json_ld_blocks = []
    for script in soup.find_all("script", type=re.compile("application/ld\\+json", re.I)):
        try:
            json_ld_blocks.append(json.loads(script.string or "{}"))
        except (json.JSONDecodeError, TypeError):
            json_ld_blocks.append({"_parse_error": True, "raw_snippet": (script.string or "")[:200]})

    return {
        "title": title_tag.get_text(strip=True) if title_tag else None,
        "description": meta(name="description"),
        "canonical_url": canonical_tag.get("href").strip() if canonical_tag and canonical_tag.get("href") else None,
        "language": html_tag.get("lang") if html_tag and html_tag.get("lang") else None,
        "generator": meta(name="generator"),
        "open_graph": og,
        "twitter_card": twitter,
        "json_ld": json_ld_blocks,
        "headings_sample": headings,
        "nav_labels_sample": nav_labels,
    }


MOTTO_PATTERNS = [
    re.compile(r'class=["\'][^"\']*(?:tagline|slogan|motto)[^"\']*["\']', re.I),
]


def detect_motto(soup: BeautifulSoup, metadata: dict) -> Evidence:
    for pat in MOTTO_PATTERNS:
        tag = soup.find(attrs={"class": pat}) if False else None  # placeholder, refined below
    # Refined approach: look for elements whose class/id literally contains
    # tagline/slogan/motto keywords.
    for el in soup.find_all(True):
        classes = " ".join(el.get("class", [])) if el.get("class") else ""
        el_id = el.get("id", "") or ""
        haystack = f"{classes} {el_id}".lower()
        if any(k in haystack for k in ("tagline", "slogan", "motto")):
            text = el.get_text(strip=True)
            if text and 2 <= len(text) <= 200:
                return Evidence(
                    OBSERVED,
                    f'Element with class/id suggesting a tagline contains: "{text}"',
                    source="HTML element class/id match",
                )
    og_desc = (metadata.get("open_graph") or {}).get("description")
    if metadata.get("description") and len(metadata["description"]) <= 120:
        return Evidence(
            INFERRED,
            f'No explicit tagline element found. The meta description reads short enough to '
            f'plausibly function as a positioning statement: "{metadata["description"]}". '
            "This is an inference, not a confirmed official slogan.",
            source="meta[name=description] (INFERRED positioning only)",
        )
    return Evidence(
        UNKNOWN,
        "No explicit motto/tagline element or short positioning meta description was found. "
        "No slogan is claimed for this site.",
        source=None,
    )


# ---------------------------------------------------------------------------
# Forms / links / routes (Section 3, 6)
# ---------------------------------------------------------------------------
def extract_forms(soup: BeautifulSoup, base_url: str) -> list[dict]:
    forms = []
    for form in soup.find_all("form"):
        fields = []
        for field_tag in form.find_all(["input", "select", "textarea"]):
            fields.append({
                "tag": field_tag.name,
                "type": field_tag.get("type", "text" if field_tag.name == "input" else field_tag.name),
                "name": field_tag.get("name"),
                "required": field_tag.has_attr("required"),
            })
        forms.append({
            "action": urljoin(base_url, form.get("action")) if form.get("action") else base_url,
            "method": (form.get("method") or "GET").upper(),
            "fields": fields,
        })
    return forms


def extract_links(soup: BeautifulSoup, base_url: str) -> dict:
    base_host = urlparse(base_url).netloc
    internal, external = set(), set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        full = urljoin(base_url, href)
        host = urlparse(full).netloc
        (internal if host == base_host else external).add(full)
    return {
        "internal": sorted(internal)[:300],
        "external": sorted(external)[:150],
        "internal_count_total": len(internal),
        "external_count_total": len(external),
    }


def extract_assets(soup: BeautifulSoup, base_url: str) -> list[ResourceRecord]:
    records: list[ResourceRecord] = []

    def add(kind: str, url: Optional[str], note: Optional[str] = None):
        if not url:
            return
        records.append(ResourceRecord(kind=kind, source_url=urljoin(base_url, url), note=note))

    for link in soup.find_all("link"):
        rels = " ".join(link.get("rel", [])).lower()
        href = link.get("href")
        if "stylesheet" in rels:
            add("css", href)
        elif "icon" in rels:
            add("icon", href)
        elif "preload" in rels and link.get("as") == "font":
            add("font", href)

    for script in soup.find_all("script", src=True):
        add("js", script["src"])

    for img in soup.find_all("img", src=True):
        add("image", img["src"])
    for source in soup.find_all("source", src=True):
        add("image", source["src"])

    for style in soup.find_all("style"):
        for m in re.finditer(r'url\((["\']?)([^)\'"]+)\1\)', style.get_text() or ""):
            add("other", m.group(2), note="referenced from inline <style>")

    return records


# ---------------------------------------------------------------------------
# Headers / robots.txt / sitemap.xml (Sections 3, 10, 14)
# ---------------------------------------------------------------------------
SECURITY_HEADER_NAMES = [
    "content-security-policy",
    "strict-transport-security",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
    "x-xss-protection",
]


def summarize_security_headers(headers: dict) -> dict:
    lower = {k.lower(): v for k, v in headers.items()}
    present = {h: lower[h] for h in SECURITY_HEADER_NAMES if h in lower}
    missing = [h for h in SECURITY_HEADER_NAMES if h not in lower]
    return {
        "present": present,
        "missing": missing,
        "note": (
            "This is a non-invasive observation of which common security-related "
            "response headers were present on the fetched page. It is not a "
            "penetration test or vulnerability assessment."
        ),
    }


async def fetch_text_best_effort(client: SafeAsyncClient, url: str, max_bytes: int) -> Optional[str]:
    try:
        resp, _final_url, body = await client.safe_get(url, max_bytes=max_bytes)
        if resp.status_code != 200:
            return None
        return body.decode(resp.encoding or "utf-8", errors="replace")
    except (SecurityError, httpx.HTTPError, asyncio.TimeoutError):
        return None


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
