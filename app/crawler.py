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


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)


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
    ):
        self.start_url = normalize_url(start_url)
        self.max_pages = max_pages
        self.depth = depth
        self.timeout = timeout
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
            text = resp.text or ""
            meta["size"] = len(text.encode("utf-8", errors="replace"))
            meta["sha256"] = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
            # Keep body even on error pages / challenges — better than empty ZIP
            if resp.status_code >= 400:
                meta["error"] = f"HTTP {resp.status_code}"
                return text if text.strip() else None, meta
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
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}

        async with httpx.AsyncClient(headers=headers, limits=limits, verify=True) as client:
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
