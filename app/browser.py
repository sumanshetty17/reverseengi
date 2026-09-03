"""
Browser rendering with Playwright — dynamic content + optional authorized login.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    async_playwright = None  # type: ignore


async def _try_login(page, login_url: str, username: str, password: str,
                     username_selector: str = "", password_selector: str = "",
                     submit_selector: str = "") -> Dict[str, Any]:
    """
    Attempt form login on login_url using provided credentials.
    Only for accounts the operator is authorized to use.
    """
    info: Dict[str, Any] = {"ok": False, "error": None, "final_url": None}
    try:
        await page.goto(login_url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(1.2)

        user_sels = [s for s in [
            username_selector,
            'input[type="email"]',
            'input[name="email"]',
            'input[name="username"]',
            'input[name="user"]',
            'input[name="login"]',
            'input[autocomplete="username"]',
            'input[autocomplete="email"]',
            'input[type="text"]',
        ] if s]
        pass_sels = [s for s in [
            password_selector,
            'input[type="password"]',
            'input[name="password"]',
            'input[autocomplete="current-password"]',
        ] if s]
        submit_sels = [s for s in [
            submit_selector,
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Log in")',
            'button:has-text("Login")',
            'button:has-text("Sign in")',
            'button:has-text("Sign In")',
            'button:has-text("Continue")',
        ] if s]

        user_el = None
        for sel in user_sels:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    user_el = loc
                    break
            except Exception:
                continue
        pass_el = None
        for sel in pass_sels:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    pass_el = loc
                    break
            except Exception:
                continue

        if not user_el or not pass_el:
            info["error"] = "Could not find username/password fields on login page"
            return info

        await user_el.fill(username)
        await pass_el.fill(password)
        await asyncio.sleep(0.3)

        clicked = False
        for sel in submit_sels:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click()
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            await pass_el.press("Enter")

        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            await asyncio.sleep(3.0)

        info["final_url"] = page.url
        # Heuristic: still on login path → maybe failed
        low = (page.url or "").lower()
        if any(x in low for x in ("/login", "/signin", "/sign-in", "/auth")):
            # might still be 2FA or wrong password
            info["error"] = "Still on a login/auth URL after submit — check credentials or 2FA"
            info["ok"] = False
        else:
            info["ok"] = True
            info["error"] = None
    except Exception as e:
        info["error"] = str(e)
    return info


async def render_page(
    url: str,
    wait_until: str = "networkidle",
    timeout_ms: int = 45000,
    collect_requests: bool = True,
    login: Optional[Dict[str, str]] = None,
    context=None,
    page=None,
) -> Dict[str, Any]:
    """
    Render a page. Optional login dict:
      {login_url, username, password, username_selector?, password_selector?, submit_selector?}
    If context/page provided, reuse authenticated session.
    """
    result: Dict[str, Any] = {
        "url": url,
        "rendered_html": None,
        "title": None,
        "loaded_urls": [],
        "api_candidates": [],
        "error": None,
        "login": None,
        "playwright_available": PLAYWRIGHT_AVAILABLE,
    }

    if not PLAYWRIGHT_AVAILABLE:
        result["error"] = "Playwright not installed. Run: playwright install chromium"
        return result

    loaded: List[str] = []
    api_candidates: List[Dict[str, str]] = []
    own_browser = context is None

    try:
        if own_browser:
            p = await async_playwright().start()
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/121.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
                locale="en-US",
                java_script_enabled=True,
            )
            page = await context.new_page()
        else:
            p = None
            browser = None
            page = page or await context.new_page()

        if collect_requests:
            def on_request(request):
                u = request.url
                loaded.append(u)
                rtype = request.resource_type
                if rtype in ("xhr", "fetch"):
                    api_candidates.append(
                        {"url": u, "method": request.method, "resource_type": rtype}
                    )

            page.on("request", on_request)

        # Authorized login (credentials supplied by operator)
        if login and login.get("username") and login.get("password"):
            login_url = login.get("login_url") or url
            result["login"] = await _try_login(
                page,
                login_url=login_url,
                username=login["username"],
                password=login["password"],
                username_selector=login.get("username_selector") or "",
                password_selector=login.get("password_selector") or "",
                submit_selector=login.get("submit_selector") or "",
            )

        for strategy in (wait_until, "domcontentloaded", "load"):
            try:
                await page.goto(url, wait_until=strategy, timeout=timeout_ms)
                break
            except Exception as nav_err:
                result["error"] = f"Navigation ({strategy}): {nav_err}"

        await asyncio.sleep(2.5)
        try:
            for _ in range(4):
                await page.evaluate("window.scrollBy(0, document.body.scrollHeight / 3)")
                await asyncio.sleep(0.5)
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.4)
        except Exception:
            pass

        try:
            result["rendered_html"] = await page.content()
            result["title"] = await page.title()
        except Exception as e:
            result["error"] = (result.get("error") or "") + f"; content: {e}"

        result["loaded_urls"] = list(dict.fromkeys(loaded))
        result["api_candidates"] = api_candidates
        try:
            result["location"] = await page.evaluate("() => window.location.href")
            result["body_text_len"] = await page.evaluate(
                "() => (document.body && document.body.innerText || '').length"
            )
        except Exception:
            pass

        if own_browser:
            await browser.close()
            await p.stop()
    except Exception as e:
        result["error"] = str(e)

    return result


async def render_with_session(
    urls: List[str],
    login: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    One browser session: optional login once, then render many URLs
    while keeping cookies/storage (authenticated crawl).
    """
    results: Dict[str, Dict[str, Any]] = {}
    if not PLAYWRIGHT_AVAILABLE:
        for u in urls:
            results[u] = {
                "url": u,
                "error": "Playwright not installed",
                "playwright_available": False,
            }
        return results

    loaded_global: List[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        page = await context.new_page()

        def on_request(request):
            loaded_global.append(request.url)

        page.on("request", on_request)

        login_info = None
        if login and login.get("username") and login.get("password"):
            login_info = await _try_login(
                page,
                login_url=login.get("login_url") or (urls[0] if urls else ""),
                username=login["username"],
                password=login["password"],
                username_selector=login.get("username_selector") or "",
                password_selector=login.get("password_selector") or "",
                submit_selector=login.get("submit_selector") or "",
            )

        for u in urls:
            entry: Dict[str, Any] = {
                "url": u,
                "rendered_html": None,
                "title": None,
                "loaded_urls": [],
                "api_candidates": [],
                "error": None,
                "login": login_info,
                "playwright_available": True,
            }
            loaded_before = len(loaded_global)
            try:
                for strategy in ("networkidle", "domcontentloaded"):
                    try:
                        await page.goto(u, wait_until=strategy, timeout=45000)
                        break
                    except Exception as e:
                        entry["error"] = str(e)
                await asyncio.sleep(2.0)
                try:
                    for _ in range(3):
                        await page.evaluate("window.scrollBy(0, document.body.scrollHeight / 3)")
                        await asyncio.sleep(0.4)
                except Exception:
                    pass
                entry["rendered_html"] = await page.content()
                entry["title"] = await page.title()
                entry["loaded_urls"] = list(dict.fromkeys(loaded_global[loaded_before:]))
                entry["location"] = page.url
            except Exception as e:
                entry["error"] = str(e)
            results[u] = entry

        await browser.close()
    return results
