"""
Privacy / identity controls for outbound requests.

- Default: look like a normal browser (no project name in User-Agent).
- Optional HTTP(S)/SOCKS proxy so the target sees the proxy IP, not yours/Render's.
- Credentials and proxy URLs are not written into public reports.

True anonymity is impossible without a proxy/VPN you control.
"""

from __future__ import annotations

import os
import random
from typing import Any, Dict, Optional

# Common desktop browser UAs — no project fingerprint
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
    """
    Proxy URL examples:
      http://user:pass@host:8080
      https://host:8443
      socks5://host:1080
    Env fallback: CRAWLER_PROXY or HTTPS_PROXY or HTTP_PROXY
    """
    for candidate in (
        explicit,
        os.environ.get("CRAWLER_PROXY"),
        os.environ.get("HTTPS_PROXY"),
        os.environ.get("HTTP_PROXY"),
        os.environ.get("ALL_PROXY"),
    ):
        if candidate and candidate.strip():
            return candidate.strip()
    return None


def httpx_proxy_mounts(proxy_url: Optional[str]) -> Optional[str]:
    """httpx accepts proxy= as a single URL string for all schemes."""
    return proxy_url


def privacy_summary(proxy_used: bool) -> Dict[str, Any]:
    return {
        "browser_like_headers": True,
        "project_name_in_user_agent": False,
        "proxy_configured": proxy_used,
        "note": (
            "Target sees proxy IP when proxy is set; otherwise it sees this server's IP (e.g. Render). "
            "Password/proxy secrets are not stored in reports."
        ),
    }
