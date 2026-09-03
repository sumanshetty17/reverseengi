"""
Analyze accessible application data, client-visible APIs, configuration.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


def find_json_blobs(html: str) -> List[Dict[str, Any]]:
    """Extract embedded JSON / config objects from HTML/JS."""
    found = []
    # __NEXT_DATA__, window.__INITIAL_STATE__, etc.
    patterns = [
        r"<script[^>]*id=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>",
        r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});",
        r"window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});",
        r"window\.__DATA__\s*=\s*(\{.*?\});",
        r"__NUXT__\s*=\s*(\{.*?\});",
    ]
    for pat in patterns:
        for m in re.finditer(pat, html or "", re.DOTALL | re.I):
            try:
                data = json.loads(m.group(1))
                found.append({"source": pat[:40], "data_keys": list(data.keys()) if isinstance(data, dict) else type(data).__name__, "preview": str(data)[:500]})
            except Exception:
                found.append({"source": pat[:40], "raw_preview": m.group(1)[:300]})
    return found


def extract_api_endpoints(loaded_urls: List[str], html: str = "") -> List[Dict[str, Any]]:
    """Heuristic discovery of client-visible API endpoints."""
    endpoints = []
    seen = set()

    # From network requests
    for u in loaded_urls or []:
        path = urlparse(u).path.lower()
        if any(
            seg in path
            for seg in ("/api/", "/v1/", "/v2/", "/graphql", "/rest/", "/.json", "/wp-json/")
        ):
            if u not in seen:
                seen.add(u)
                endpoints.append({"url": u, "source": "network", "method": "GET"})

    # From HTML / inline scripts
    for m in re.finditer(
        r"""['"`](https?://[^'"`\s]+/(?:api|v\d|graphql|rest)[^'"`\s]*)['"`]""",
        html or "",
        re.I,
    ):
        u = m.group(1)
        if u not in seen:
            seen.add(u)
            endpoints.append({"url": u, "source": "inline", "method": "unknown"})

    # Relative API paths
    for m in re.finditer(r"""['"`](/(?:api|v\d)/[a-zA-Z0-9_/\-]+)['"`]""", html or ""):
        path = m.group(1)
        if path not in seen:
            seen.add(path)
            endpoints.append({"url": path, "source": "relative", "method": "unknown"})

    return endpoints[:80]


def analyze_architecture(
    pages: Dict[str, Any],
    assets_manifest: List[Dict],
    technologies: List[Dict],
    endpoints: List[Dict],
) -> Dict[str, Any]:
    """Build a high-level architecture map."""
    page_list = []
    for url, pdata in (pages or {}).items():
        page_list.append(
            {
                "url": url,
                "title": (pdata.get("parsed") or {}).get("title"),
                "status": pdata.get("status"),
                "scripts_count": len((pdata.get("parsed") or {}).get("scripts") or []),
                "styles_count": len((pdata.get("parsed") or {}).get("stylesheets") or []),
                "images_count": len((pdata.get("parsed") or {}).get("images") or []),
            }
        )

    asset_summary = {}
    for a in assets_manifest or []:
        t = a.get("type", "other")
        asset_summary[t] = asset_summary.get(t, 0) + 1

    return {
        "pages": page_list,
        "total_pages": len(page_list),
        "asset_counts_by_type": asset_summary,
        "technologies": [t["name"] for t in technologies],
        "api_endpoints_discovered": len(endpoints),
        "frontend_backend_links": [
            {"endpoint": e["url"], "note": "Client-visible; backend implementation not retrieved unless authorized"}
            for e in endpoints[:20]
        ],
        "notes": [
            "Architecture is reconstructed from publicly observable frontend material only.",
            "Backend source is included only when explicitly supplied or authorized.",
        ],
    }
