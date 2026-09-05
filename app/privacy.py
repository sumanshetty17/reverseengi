"""
Privacy controls for outbound requests.

IMPORTANT:
  - Your home PC IP is never used when the job runs on Render (server IP is used).
  - To avoid exposing even the server IP to the target, you MUST set a proxy.
  - There is no way to hide IP with zero infrastructure: a proxy/VPN you control is required.
"""

from __future__ import annotations

import os
import random
from typing import Any, Dict, Optional

_BROWSER_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]


def pick_user_agent(stable: bool = True) -> str:
    if stable:
        return _BROWSER_UAS[0]
    return random.choice(_BROWSER_UAS)


def browser_headers(user_agent: Optional[str] = None) -> Dict[str, str]:
    ua = user_agent or pick_user_agent(True)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


def resolve_proxy(explicit: Optional[str] = None) -> Optional[str]:
    for candidate in (
        explicit,
        os.environ.get("CRAWLER_PROXY"),
        os.environ.get("HTTPS_PROXY"),
        os.environ.get("HTTP_PROXY"),
        os.environ.get("ALL_PROXY"),
    ):
        if candidate and str(candidate).strip():
            p = str(candidate).strip()
            # Reject obvious placeholders
            low = p.lower()
            if "proxy-hos" in low or "proxy-host" in low or "example.com" in low:
                continue
            return p
    return None


def require_proxy_enabled() -> bool:
    """Env PRIVATE_MODE=1 or REQUIRE_PROXY=1 forces proxy for every job."""
    v = (os.environ.get("PRIVATE_MODE") or os.environ.get("REQUIRE_PROXY") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def privacy_summary(proxy_used: bool, strict: bool = False) -> Dict[str, Any]:
    return {
        "browser_like_headers": True,
        "project_name_in_user_agent": False,
        "proxy_configured": proxy_used,
        "strict_private_mode": strict,
        "home_ip_used": False,
        "note": (
            "Home/device IP is not used (jobs run on the server). "
            "Target sees proxy IP when proxy is set; otherwise server (e.g. Render) IP. "
            "Secrets are not written into reconstruction ZIPs."
        ),
    }
