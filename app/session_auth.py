"""
Human-in-the-loop session support.

User logs in (and solves CAPTCHA/2FA) in their own browser, then pastes
cookies / Playwright storage state into the tool. We never bypass CAPTCHA;
we reuse the session the human already completed.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


def parse_cookie_header(raw: str, default_domain: str = "") -> List[Dict[str, Any]]:
    """Parse 'a=1; b=2' or line-based cookies into Playwright cookie dicts."""
    raw = (raw or "").strip()
    if not raw:
        return []
    cookies: List[Dict[str, Any]] = []
    domain = default_domain
    if domain.startswith("http"):
        domain = urlparse(domain).hostname or ""
    if domain and not domain.startswith("."):
        # host-only; Playwright accepts domain without leading dot
        pass

    # JSON array?
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            for c in data:
                if not isinstance(c, dict) or "name" not in c or "value" not in c:
                    continue
                entry = {
                    "name": str(c["name"]),
                    "value": str(c["value"]),
                    "domain": c.get("domain") or domain or "localhost",
                    "path": c.get("path") or "/",
                }
                if c.get("httpOnly") is not None:
                    entry["httpOnly"] = bool(c["httpOnly"])
                if c.get("secure") is not None:
                    entry["secure"] = bool(c["secure"])
                cookies.append(entry)
            return cookies
        except Exception:
            pass

    # storage_state style {"cookies":[...]}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "cookies" in data:
                return parse_cookie_header(json.dumps(data["cookies"]), default_domain)
        except Exception:
            pass

    # Header style name=value; name2=value2
    parts = re.split(r";\s*", raw.replace("\n", "; "))
    for part in parts:
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name or name.lower() in ("path", "domain", "expires", "max-age", "secure", "httponly", "samesite"):
            continue
        cookies.append({
            "name": name,
            "value": value,
            "domain": domain or "localhost",
            "path": "/",
        })
    return cookies


def parse_storage_state(raw: str) -> Optional[Dict[str, Any]]:
    """Full Playwright storage_state JSON if provided."""
    raw = (raw or "").strip()
    if not raw.startswith("{"):
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and ("cookies" in data or "origins" in data):
            return data
    except Exception:
        return None
    return None
