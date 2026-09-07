"""
Controlled multi-page crawler.
Discovers pages, routes, navigation links within the same origin.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urldefrag

import httpx
from bs4 import BeautifulSoup

from app.privacy import browser_headers, resolve_proxy, pick_user_agent

USER_AGENT = pick_user_agent(stable=True)


def normalize_url(url: str, base: Optional[str] = None) -> str:
    if base:
        url = urljoin(base, url)
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    # Drop default ports
    netloc = parsed.netloc
    if parsed.port in (80, 443):
        netloc = parsed.hostname or netloc
    path = parsed.path or "/"
    return f"{parsed.scheme}://{netloc}{path}" + (f"?{parsed.query}" if parsed.query else "")


def same_origin(url_a: str, url_b: str) -> bool:
    a, b = urlparse(url_a), urlparse(url_b)
    return a.scheme == b.scheme and a.netloc == b.netloc


def is_asset_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return bool(
        re.search(
            r"\.(css|js|mjs|map|png|jpe?g|gif|webp|svg|ico|woff2?|ttf|eot|otf|pdf|json|xml|txt)(\?|$)",
            path,
        )
    )


class Crawler:
    def __init__(
        self,
        start_url: str,
        max_pages: int = 20,
        depth: int = 2,
        timeout: float = 20.0,
        proxy: str | None = None,
        cookie_header: str | None = None,
    ):
        self.start_url = normalize_url(start_url)
        self.max_pages = max_pages
        self.depth = depth
        self.timeout = timeout
        self.proxy = resolve_proxy(proxy)
        self.cookie_header = cookie_header
        self.origin = f"{urlparse(self.start_url).scheme}://{urlparse(self.start_url).netloc}"
        self.visited: Set[str] = set()
        self.pages: Dict[str, Dict[str, Any]] = {}
        self.links_found: Set[str] = set()
        self.errors: List[Dict[str, str]] = []

    async def fetch(self, client: httpx.AsyncClient, url: str) -> Tuple[Optional[str], Dict[str, Any]]:
        meta: Dict[str, Any] = {"url": url, "status": None, "headers": {}, "error": None}
        try:
            resp = await client.get(url, follow_redirects=True, timeout=self.timeout)
            meta["status"] = resp.status_code
            meta["final_url"] = str(resp.url)
            meta["headers"] = dict(resp.headers)
            meta["content_type"] = resp.headers.get("content-type", "")
            # Prefer decoded text; if still binary (failed br decode), use raw utf-8 replace
            try:
                text = resp.text or ""
            except Exception:
                text = resp.content.decode("utf-8", errors="replace") if resp.content else ""
            # Detect accidental compressed payload treated as text
            if text and ("<html" not in text.lower() and "<!doctype" not in text.lower()):
                # try decompress gzip if magic bytes
                raw = resp.content or b""
                if raw[:2] == b"\x1f\x8b":
                    import gzip
                    try:
                        text = gzip.decompress(raw).decode("utf-8", errors="replace")
                    except Exception:
                        pass
                elif len(raw) > 4 and raw[0:1] == b"\x1b":
                    # likely unsupported br — refetch without br is handled via Accept-Encoding
                    meta["error"] = (meta.get("error") or "") + " possibly_compressed_body"
            meta["size"] = len((text or "").encode("utf-8", errors="replace"))
            meta["sha256"] = hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()
            if resp.status_code >= 400:
                meta["error"] = f"HTTP {resp.status_code}"
                return text if text and text.strip() else None, meta
            return text, meta
        except Exception as e:
            meta["error"] = str(e)
            self.errors.append({"url": url, "error": str(e)})
            return None, meta

    def extract_links(self, html: str, base_url: str) -> List[str]:
        soup = BeautifulSoup(html, "lxml")
        links: List[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            full = normalize_url(href, base_url)
            if same_origin(full, self.start_url) and not is_asset_url(full):
                links.append(full)
                self.links_found.add(full)
        return links

    async def crawl(self) -> Dict[str, Any]:
        queue: deque[Tuple[str, int]] = deque([(self.start_url, 0)])
        self.visited.add(self.start_url)

        limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
        headers = browser_headers(USER_AGENT)
        if self.cookie_header:
            # User-provided session after manual login/CAPTCHA
            headers["Cookie"] = self.cookie_header.split("\\n")[0].strip()
            if headers["Cookie"].lower().startswith("cookie:"):
                headers["Cookie"] = headers["Cookie"].split(":", 1)[1].strip()

        client_kwargs = dict(headers=headers, limits=limits, verify=True, follow_redirects=True)
        if self.proxy:
            client_kwargs["proxy"] = self.proxy

        async with httpx.AsyncClient(**client_kwargs) as client:
            while queue and len(self.pages) < self.max_pages:
                url, current_depth = queue.popleft()
                html, meta = await self.fetch(client, url)
                page_record = {
                    "url": url,
                    "final_url": meta.get("final_url", url),
                    "status": meta.get("status"),
                    "headers": {
                        k: v
                        for k, v in (meta.get("headers") or {}).items()
                        if k.lower()
                        in (
                            "content-type",
                            "server",
                            "x-powered-by",
                            "x-frame-options",
                            "content-security-policy",
                            "set-cookie",
                            "cache-control",
                        )
                    },
                    "content_type": meta.get("content_type"),
                    "size": meta.get("size"),
                    "sha256": meta.get("sha256"),
                    "error": meta.get("error"),
                    "html": html,
                    "depth": current_depth,
                    "links": [],
                }
                if html:
                    page_record["links"] = self.extract_links(html, meta.get("final_url", url))
                    if current_depth < self.depth:
                        for link in page_record["links"]:
                            if link not in self.visited and len(self.pages) + len(queue) < self.max_pages:
                                self.visited.add(link)
                                queue.append((link, current_depth + 1))
                self.pages[url] = page_record
                # polite delay
                await asyncio.sleep(0.15)

        return {
            "start_url": self.start_url,
            "origin": self.origin,
            "pages_crawled": len(self.pages),
            "pages": self.pages,
            "all_links": sorted(self.links_found),
            "errors": self.errors,
        }
