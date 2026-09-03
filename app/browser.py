"""
Browser rendering with Playwright for dynamic content & resource discovery.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Set

# Playwright is optional at import time so the rest of the system can run without it
try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    async_playwright = None  # type: ignore


async def render_page(
    url: str,
    wait_until: str = "networkidle",
    timeout_ms: int = 30000,
    collect_requests: bool = True,
) -> Dict[str, Any]:
    """
    Launch Chromium, navigate to URL, wait for network idle,
    capture rendered HTML and all network requests.
    """
    result: Dict[str, Any] = {
        "url": url,
        "rendered_html": None,
        "title": None,
        "loaded_urls": [],
        "api_candidates": [],
        "error": None,
        "playwright_available": PLAYWRIGHT_AVAILABLE,
    }

    if not PLAYWRIGHT_AVAILABLE:
        result["error"] = "Playwright not installed. Run: playwright install chromium"
        return result

    loaded: List[str] = []
    api_candidates: List[Dict[str, str]] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 720},
            )
            page = await context.new_page()

            if collect_requests:
                def on_request(request):
                    u = request.url
                    loaded.append(u)
                    # Heuristic: XHR/fetch JSON endpoints
                    rtype = request.resource_type
                    if rtype in ("xhr", "fetch"):
                        api_candidates.append(
                            {
                                "url": u,
                                "method": request.method,
                                "resource_type": rtype,
                            }
                        )

                page.on("request", on_request)

            try:
                await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            except Exception as nav_err:
                # Still try to get whatever content is available
                result["error"] = f"Navigation warning: {nav_err}"

            # Small extra wait for late resources
            await asyncio.sleep(1.0)

            result["rendered_html"] = await page.content()
            result["title"] = await page.title()
            result["loaded_urls"] = list(dict.fromkeys(loaded))  # preserve order, unique
            result["api_candidates"] = api_candidates

            # Capture some browser-visible state
            try:
                result["viewport"] = await page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")
                result["location"] = await page.evaluate("() => window.location.href")
            except Exception:
                pass

            await browser.close()
    except Exception as e:
        result["error"] = str(e)

    return result


async def render_multiple(urls: List[str], max_concurrent: int = 2) -> Dict[str, Dict[str, Any]]:
    """Render several pages with limited concurrency."""
    sem = asyncio.Semaphore(max_concurrent)
    results: Dict[str, Dict[str, Any]] = {}

    async def _one(u: str):
        async with sem:
            results[u] = await render_page(u)

    await asyncio.gather(*[_one(u) for u in urls])
    return results
