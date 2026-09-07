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



def infer_backend_from_frontend(
    html: str,
    endpoints: List[Dict],
    technologies: List[Dict],
    purpose: Dict[str, Any],
    pages: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Infer likely backend shape, data domains, and business logic
    from public frontend evidence only (not private server source).
    """
    tech_names = [t.get("name", "") for t in (technologies or [])]
    html_l = (html or "").lower()

    # Hosting / runtime hints
    hosting = []
    if any(x in tech_names for x in ("Vercel", "Next.js")):
        hosting.append("Likely Node.js serverless / Next.js API routes or external APIs (Vercel-style hosting)")
    if "clerk" in html_l or "clerk." in html_l:
        hosting.append("Auth likely delegated to Clerk (hosted auth service)")
    if "supabase" in html_l:
        hosting.append("Possible Supabase (Postgres + auth + APIs)")
    if "firebase" in html_l:
        hosting.append("Possible Firebase backend")
    if "graphql" in html_l or any("graphql" in (e.get("url") or "").lower() for e in endpoints or []):
        hosting.append("GraphQL API may be used")
    if any("/api/" in (e.get("url") or "") for e in endpoints or []):
        hosting.append("REST-style /api/ paths visible from the client")

    # Data domains from UI vocabulary + paths
    vocab_map = {
        "users / accounts": ["sign-in", "sign-up", "login", "signup", "user", "account", "profile", "clerk"],
        "billing / plans": ["pricing", "checkout", "subscription", "billing", "plan", "stripe"],
        "product feedback / signals": ["signal", "feedback", "intercom", "slack", "gong"],
        "roadmap / opportunities": ["roadmap", "opportunit", "backlog", "impact", "prd"],
        "integrations": ["integration", "webhook", "linear", "slack", "intercom"],
        "workspaces / teams": ["workspace", "team", "organization", "org"],
        "analytics": ["google-analytics", "gtag", "segment", "mixpanel"],
    }
    data_domains = []
    for name, keys in vocab_map.items():
        if any(k in html_l for k in keys):
            data_domains.append(name)

    # Business logic hypotheses (from marketing + UI flows)
    logic = []
    if purpose:
        if purpose.get("title"):
            logic.append(f"Product positioning from title: {purpose.get('title')}")
        if purpose.get("description"):
            logic.append(f"Stated problem/value: {purpose.get('description')}")
    if "sign-up" in html_l or "sign-in" in html_l:
        logic.append("Access control: public marketing pages + authenticated app area after sign-in/sign-up")
    if any(k in html_l for k in ("rank", "impact", "score", "priorit")):
        logic.append("Core logic (claimed): score/rank customer signals or opportunities by business impact")
    if any(k in html_l for k in ("ingest", "webhook", "integrat")):
        logic.append("Ingestion logic (claimed): pull or receive events from third-party tools")
    if "prd" in html_l:
        logic.append("Output logic (claimed): generate PRD / tickets from approved opportunities")

    # Entity guesses from paths and words
    entities = []
    for e in endpoints or []:
        path = (e.get("url") or "").lower()
        for ent in ("user", "workspace", "project", "signal", "opportunity", "integration", "billing", "session"):
            if ent in path and ent not in entities:
                entities.append(ent)
    for ent, keys in [
        ("User", ["sign-in", "sign-up", "account"]),
        ("Workspace", ["workspace"]),
        ("Signal", ["signal"]),
        ("Opportunity", ["opportunit"]),
        ("Integration", ["integration", "slack", "linear", "intercom"]),
    ]:
        if any(k in html_l for k in keys) and ent.lower() not in [x.lower() for x in entities]:
            entities.append(ent)

    ep_list = [{"url": e.get("url"), "source": e.get("source")} for e in (endpoints or [])[:40]]

    observed = extract_observed_data_shapes(html, endpoints)
    # Prefer entities from observed UI words
    for w in observed.get("string_entities") or []:
        if w.title() not in entities and w not in [x.lower() for x in entities]:
            entities.append(w.title())

    return {
        "disclaimer": (
            "Inferred only from public frontend (HTML/JS/UI). "
            "This is not the private server source code or database."
        ),
        "likely_backend_style": hosting or ["Unknown — few server hints in public assets"],
        "client_visible_api_endpoints": ep_list,
        "inferred_data_domains": data_domains or ["Not enough UI vocabulary to infer domains"],
        "inferred_entities": entities or ["User (typical for sites with auth pages)"],
        "inferred_business_logic": logic or ["See page copy in HTML report; limited logic signals in frontend"],
        "observed_from_frontend": observed,
        "pages_modeled": [
            {"url": u, "has_forms": bool((pdata.get("html") or "").lower().count("<form"))}
            for u, pdata in list((pages or {}).items())[:20]
        ],
    }



def extract_observed_data_shapes(html: str, endpoints: List[Dict]) -> Dict[str, Any]:
    """
    Mine public HTML/JS for real structures the frontend expects:
    __NEXT_DATA__, embedded JSON, form field names, API path segments.
    Used to build a closer synthetic backend/db.
    """
    observed: Dict[str, Any] = {
        "json_blobs": [],
        "form_fields": [],
        "api_paths": [],
        "string_entities": [],
        "next_data_keys": [],
    }
    if not html:
        return observed

    # __NEXT_DATA__ full keys + shallow sample
    for m in re.finditer(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.I,
    ):
        try:
            data = json.loads(m.group(1))
            observed["next_data_keys"] = list(data.keys()) if isinstance(data, dict) else []
            # shallow props
            props = data.get("props") if isinstance(data, dict) else None
            if isinstance(props, dict):
                observed["json_blobs"].append(
                    {
                        "source": "__NEXT_DATA__.props",
                        "keys": list(props.keys())[:40],
                        "sample": _shallow(props, depth=2),
                    }
                )
        except Exception:
            pass

    # Other JSON blobs already partially handled by find_json_blobs — merge light
    for blob in find_json_blobs(html)[:15]:
        observed["json_blobs"].append(blob)

    # Form fields
    for m in re.finditer(r'<input[^>]+name=["\']([^"\']+)["\']', html, re.I):
        observed["form_fields"].append(m.group(1))
    for m in re.finditer(r'<select[^>]+name=["\']([^"\']+)["\']', html, re.I):
        observed["form_fields"].append(m.group(1))
    observed["form_fields"] = list(dict.fromkeys(observed["form_fields"]))[:40]

    # API paths
    for e in endpoints or []:
        u = e.get("url") or ""
        path = urlparse(u).path if "://" in u else u
        if path:
            observed["api_paths"].append(path)
    for m in re.finditer(r'["\'](/(?:api|v\d)/[a-zA-Z0-9_/\-{}]+)["\']', html):
        observed["api_paths"].append(m.group(1))
    observed["api_paths"] = list(dict.fromkeys(observed["api_paths"]))[:60]

    # Entity-like words in UI
    for word in (
        "workspace", "signal", "opportunity", "integration", "roadmap",
        "project", "team", "user", "plan", "billing", "webhook", "ticket",
    ):
        if re.search(rf"\b{word}s?\b", html, re.I):
            observed["string_entities"].append(word)

    return observed


def _shallow(obj: Any, depth: int = 2) -> Any:
    if depth <= 0:
        return type(obj).__name__
    if isinstance(obj, dict):
        out = {}
        for i, (k, v) in enumerate(obj.items()):
            if i >= 25:
                out["…"] = f"{len(obj)-25} more keys"
                break
            out[str(k)] = _shallow(v, depth - 1)
        return out
    if isinstance(obj, list):
        if not obj:
            return []
        return [_shallow(obj[0], depth - 1), f"…{len(obj)} items"]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(type(obj).__name__)
