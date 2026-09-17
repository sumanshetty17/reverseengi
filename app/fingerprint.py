"""
Technology detection using multiple observable signals + evidence.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set


# (name, list of regex patterns that indicate the tech)
TECH_RULES: List[tuple] = [
    ("WordPress", [r"/wp-content/", r"/wp-includes/", r"wp-json", r"wordpress"]),
    ("Next.js", [r"/_next/", r"__next_f", r"__NEXT_DATA__", r"next/dist"]),
    ("Nuxt.js", [r"/_nuxt/", r"__NUXT__"]),
    ("Shopify", [r"cdn\.shopify\.com", r"myshopify\.com", r"Shopify\.theme"]),
    ("React", [r"react(?:\.production|\.development)?(?:\.min)?\.js", r"data-reactroot", r"__REACT_DEVTOOLS"]),
    ("Vue.js", [r"vue(?:\.runtime)?(?:\.min)?\.js", r"data-v-[a-f0-9]", r"__VUE__"]),
    ("Angular", [r"ng-version", r"angular(?:\.min)?\.js", r"ng-app"]),
    ("jQuery", [r"jquery(?:-\d|\.min)?\.js", r"jQuery"]),
    ("Bootstrap", [r"bootstrap(?:\.min)?\.(?:css|js)", r"data-bs-"]),
    ("Tailwind CSS", [r"tailwindcss", r"cdn\.tailwindcss\.com"]),
    ("Google Analytics", [r"google-analytics\.com", r"gtag\(", r"UA-\d+-\d+", r"G-[A-Z0-9]+"]),
    ("Google Tag Manager", [r"googletagmanager\.com", r"GTM-[A-Z0-9]+"]),
    ("Cloudflare", [r"cloudflare", r"cf-ray", r"__cfduid"]),
    ("Vercel", [r"vercel", r"x-vercel"]),
    ("Netlify", [r"netlify", r"x-nf-"]),
    ("Wix", [r"wix\.com", r"wixstatic\.com", r"_wix_browser_sess"]),
    ("Squarespace", [r"squarespace\.com", r"static\.squarespace"]),
    ("Drupal", [r"drupal", r"/sites/default/files"]),
    ("Joomla", [r"joomla", r"/media/jui/"]),
    ("Laravel", [r"laravel", r"csrf-token"]),
    ("Django", [r"csrfmiddlewaretoken", r"django"]),
    ("Express", [r"express", r"x-powered-by:\s*express"]),
    ("PHP", [r"\.php(\?|$)", r"x-powered-by:\s*php"]),
    ("ASP.NET", [r"__VIEWSTATE", r"aspnet", r"x-aspnet"]),
    ("Font Awesome", [r"font-awesome", r"fontawesome"]),
    ("Google Fonts", [r"fonts\.googleapis\.com", r"fonts\.gstatic\.com"]),
    ("Stripe", [r"js\.stripe\.com", r"stripe\.com"]),
    ("PayPal", [r"paypal\.com", r"paypalobjects"]),
    ("Hotjar", [r"hotjar\.com", r"static\.hotjar"]),
    ("Intercom", [r"intercom\.io", r"widget\.intercom"]),
    ("HubSpot", [r"hs-scripts\.com", r"hubspot"]),
    ("Segment", [r"cdn\.segment\.com", r"analytics\.js"]),
    ("Sentry", [r"sentry\.io", r"browser\.sentry-cdn"]),
    ("Webpack", [r"webpack", r"webpackJsonp"]),
    ("Vite", [r"/@vite/", r"vite/client"]),
    ("Parcel", [r"parcel"]),
    ("Gatsby", [r"gatsby", r"/page-data/"]),
    ("Hugo", [r"hugo"]),
    ("Jekyll", [r"jekyll"]),
]


def detect_technologies(
    html_sources: List[str],
    headers_list: List[Dict[str, str]],
    loaded_urls: List[str],
    extra_text: str = "",
) -> List[Dict[str, Any]]:
    """
    Scan all available text (HTML, headers, loaded URLs) for technology fingerprints.
    Returns list of {name, confidence, evidence}.
    """
    # Combine all searchable text
    blobs: List[str] = []
    for h in html_sources:
        if h:
            blobs.append(h)
    for hdrs in headers_list:
        for k, v in (hdrs or {}).items():
            blobs.append(f"{k}: {v}")
    blobs.extend(loaded_urls or [])
    if extra_text:
        blobs.append(extra_text)

    combined = "\n".join(blobs)
    found: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for name, patterns in TECH_RULES:
        hits = []
        for pat in patterns:
            if re.search(pat, combined, re.I):
                hits.append(pat)
        if hits and name not in seen:
            seen.add(name)
            conf = "high" if len(hits) >= 2 else "medium"
            # bump to high if very distinctive single hit
            if any(p in ("/wp-content/", "/_next/", "cdn.shopify.com", "__NEXT_DATA__") for p in hits):
                conf = "high"
            found.append(
                {
                    "name": name,
                    "confidence": conf,
                    "evidence": hits[:5],
                }
            )

    # Sort: high confidence first, then alphabetical
    found.sort(key=lambda x: (0 if x["confidence"] == "high" else 1, x["name"]))
    return found


def detect_from_headers(headers: Dict[str, str]) -> List[str]:
    """Quick header-only signals."""
    signals = []
    server = (headers.get("server") or headers.get("Server") or "").lower()
    powered = (headers.get("x-powered-by") or headers.get("X-Powered-By") or "").lower()
    if "cloudflare" in server:
        signals.append("Cloudflare")
    if "nginx" in server:
        signals.append("Nginx")
    if "apache" in server:
        signals.append("Apache")
    if "php" in powered:
        signals.append("PHP")
    if "express" in powered:
        signals.append("Express")
    if "asp.net" in powered:
        signals.append("ASP.NET")
    return signals
