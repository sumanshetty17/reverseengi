"""
Controlled multi-page crawler.
Discovers pages, routes, navigation links within the same origin.
Works for classic HTML sites and SPAs (Next.js / React) by mining path
strings from HTML + JS, not only <a href>.
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

# Paths that look like real pages (not Next/static assets)
_ASSET_RE = re.compile(
    r"\.(css|js|mjs|map|png|jpe?g|gif|webp|avif|svg|ico|woff2?|ttf|eot|otf|pdf|json|xml|txt|mp4|webm|mp3)(\?|$)",
    re.I,
)
_STATIC_PATH_RE = re.compile(
    r"^/(_next|static|assets|api|graphql|cdn|fonts?|images?|img|media|build|chunks?|webpack)(/|$)",
    re.I,
)
# Quoted path-like strings inside HTML/JS bundles
_PATH_IN_JS_RE = re.compile(
    r"""(?:
        ["'](/(?:[a-zA-Z][a-zA-Z0-9_-]{0,40})(?:/(?:[a-zA-Z0-9_-]{1,40})){0,4}/?)["']
      | (?:pathname|path|href|to|url|route|as)\s*[:=]\s*["'](/(?:[a-zA-Z][a-zA-Z0-9_/-]{0,60}))["']
      | (?:p|pathname)\s*===?\s*["'](/(?:[a-zA-Z][a-zA-Z0-9_/-]{0,60}))["']
      | (?:p|pathname)\.indexOf\(\s*["'](/(?:[a-zA-Z][a-zA-Z0-9_/-]{0,60}))["']
      | href=["'](/(?:[a-zA-Z][a-zA-Z0-9_/-]{0,60}))["']
    )""",
    re.I | re.X,
)
_COMMON_SEEDS = (
    "/about",
    "/contact",
    "/pricing",
    "/features",
    "/product",
    "/products",
    "/services",
    "/blog",
    "/docs",
    "/documentation",
    "/login",
    "/signup",
    "/register",
    "/sign-in",
    "/sign-up",
    "/dashboard",
    "/app",
    "/home",
    "/team",
    "/careers",
    "/jobs",
    "/privacy",
    "/privacy-policy",
    "/terms",
    "/terms-of-service",
    "/faq",
    "/support",
    "/help",
    "/demo",
    "/waitlist",
    "/offer",
    "/pricing",
)


def normalize_url(url: str, base: Optional[str] = None) -> str:
    if base:
        url = urljoin(base, url)
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    netloc = parsed.netloc
    if parsed.port in (80, 443):
        netloc = parsed.hostname or netloc
    path = parsed.path or "/"
    # collapse trailing slash (except site root) so /offer and /offer/ are one page
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    # drop tracking query noise; keep functional query if short
    q = parsed.query or ""
    if q:
        parts = []
        for pair in q.split("&"):
            k = pair.split("=", 1)[0].lower()
            if k.startswith("utm_") or k in ("fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"):
                continue
            parts.append(pair)
        q = "&".join(parts)
    return f"{parsed.scheme}://{netloc}{path}" + (f"?{q}" if q else "")


def same_origin(url_a: str, url_b: str) -> bool:
    a, b = urlparse(url_a), urlparse(url_b)
    return a.scheme == b.scheme and a.netloc.lower() == b.netloc.lower()


def is_asset_url(url: str) -> bool:
    path = urlparse(url).path or "/"
    if _ASSET_RE.search(path):
        return True
    if _STATIC_PATH_RE.search(path):
        return True
    return False


def _looks_like_page_path(path: str) -> bool:
    if not path or not path.startswith("/"):
        return False
    if path in ("/", "//"):
        return True
    if _STATIC_PATH_RE.search(path) or _ASSET_RE.search(path):
        return False
    # reject obvious junk
    if any(x in path.lower() for x in ("javascript:", "mailto:", "tel:", "data:")):
        return False
    if len(path) > 120:
        return False
    # require at least one letter segment
    segs = [s for s in path.split("/") if s]
    if not segs:
        return True
    if not re.search(r"[a-zA-Z]", segs[0]):
        return False
    return True


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
            text = resp.text if "text" in (meta["content_type"] or "") or "json" in (meta["content_type"] or "") or not meta["content_type"] else ""
            if not text and resp.content:
                try:
                    text = resp.content.decode("utf-8", errors="replace")
                except Exception:
                    text = ""
            meta["size"] = len(resp.content or b"")
            meta["sha256"] = hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()
            if resp.status_code >= 400:
                meta["error"] = f"HTTP {resp.status_code}"
                # still return body for soft-404 SPAs that use 404 with shell HTML
                return text if text and text.strip() else None, meta
            return text, meta
        except Exception as e:
            meta["error"] = str(e)
            self.errors.append({"url": url, "error": str(e)})
            return None, meta

    def extract_links(self, html: str, base_url: str) -> List[str]:
        """Collect same-origin page URLs from <a href> AND path strings in HTML/JS."""
        links: List[str] = []
        seen_local: Set[str] = set()

        def add(raw: str) -> None:
            if not raw:
                return
            raw = raw.strip()
            if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
                return
            full = normalize_url(raw, base_url)
            if not same_origin(full, self.start_url):
                return
            if is_asset_url(full):
                return
            path = urlparse(full).path or "/"
            if not _looks_like_page_path(path):
                return
            if full in seen_local:
                return
            seen_local.add(full)
            links.append(full)
            self.links_found.add(full)

        soup = BeautifulSoup(html or "", "lxml")
        for a in soup.find_all("a", href=True):
            add(a["href"])
        # Next.js Link sometimes renders as <link> or data attributes
        for tag in soup.find_all(True):
            for attr in ("href", "data-href", "data-to", "data-url", "data-path"):
                v = tag.get(attr)
                if v and isinstance(v, str) and v.startswith("/"):
                    add(v)

        # Mine path strings from raw HTML / inline scripts (SPA routes)
        for m in _PATH_IN_JS_RE.finditer(html or ""):
            for g in m.groups():
                if g:
                    add(g)

        # Unquoted path patterns like pathname === '/dashboard'
        for m in re.finditer(r"""['"](/(?:[a-zA-Z][a-zA-Z0-9_-]*)(?:/[a-zA-Z0-9_-]+){0,3}/?)['"]""", html or ""):
            add(m.group(1))

        return links

    async def _seed_from_sitemap(self, client: httpx.AsyncClient) -> List[str]:
        seeds: List[str] = []
        for path in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml", "/robots.txt"):
            try:
                html, meta = await self.fetch(client, normalize_url(path, self.origin))
                if not html or (meta.get("status") or 0) >= 400:
                    continue
                if path.endswith("robots.txt"):
                    for line in html.splitlines():
                        if line.lower().startswith("sitemap:"):
                            sm = line.split(":", 1)[1].strip()
                            if sm:
                                sm_html, sm_meta = await self.fetch(client, sm)
                                if sm_html and (sm_meta.get("status") or 0) < 400:
                                    for loc in re.findall(r"<loc>\s*([^<]+)\s*</loc>", sm_html, re.I):
                                        u = normalize_url(loc.strip())
                                        if same_origin(u, self.start_url) and not is_asset_url(u):
                                            seeds.append(u)
                    continue
                # sitemap xml (or HTML shell — still try loc tags)
                for loc in re.findall(r"<loc>\s*([^<]+)\s*</loc>", html, re.I):
                    u = normalize_url(loc.strip())
                    if same_origin(u, self.start_url) and not is_asset_url(u):
                        seeds.append(u)
            except Exception:
                continue
        return seeds

    def _common_seed_urls(self) -> List[str]:
        out: List[str] = []
        for p in _COMMON_SEEDS:
            out.append(normalize_url(p, self.origin))
        return out

    async def crawl(self) -> Dict[str, Any]:
        queue: deque[Tuple[str, int]] = deque([(self.start_url, 0)])
        self.visited.add(self.start_url)

        limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
        headers = browser_headers(USER_AGENT)
        if self.cookie_header:
            headers["Cookie"] = self.cookie_header.split("\n")[0].strip()
            if headers["Cookie"].lower().startswith("cookie:"):
                headers["Cookie"] = headers["Cookie"].split(":", 1)[1].strip()

        client_kwargs = dict(headers=headers, limits=limits, verify=True, follow_redirects=True)
        if self.proxy:
            client_kwargs["proxy"] = self.proxy

        async with httpx.AsyncClient(**client_kwargs) as client:
            # seed sitemap once
            for s in await self._seed_from_sitemap(client):
                if s not in self.visited:
                    self.visited.add(s)
                    queue.append((s, 0))

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
                    "links": [],
                }
                if html:
                    page_record["links"] = self.extract_links(html, meta.get("final_url", url))
                    if current_depth < self.depth:
                        for link in page_record["links"]:
                            if link not in self.visited and len(self.pages) + len(queue) < self.max_pages:
                                self.visited.add(link)
                                queue.append((link, current_depth + 1))
                    # SPA fallback: if almost no <a> links, seed common + mined paths
                    if current_depth == 0 and len(page_record["links"]) < 2:
                        for seed in self._common_seed_urls() + page_record["links"]:
                            if seed not in self.visited and len(self.pages) + len(queue) < self.max_pages:
                                self.visited.add(seed)
                                queue.append((seed, 1))
                self.pages[url] = page_record
                await asyncio.sleep(0.1)

        return {
            "start_url": self.start_url,
            "origin": self.origin,
            "pages": self.pages,
            "pages_crawled": len(self.pages),
            "all_links": sorted(self.links_found),
            "errors": self.errors,
        }

    async def crawl_round(
        self,
        captured: Optional[List[str]] = None,
        queue: Optional[List[str]] = None,
        limit: int = 4,
    ) -> Dict[str, Any]:
        """
        Capture up to `limit` new pages from the durable queue.
        Returns pages for this round + updated captured/queue lists.
        """
        captured_list: List[str] = list(captured or [])
        captured_set: Set[str] = set(captured_list)
        # normalize queue entries
        raw_q = list(queue or [self.start_url])
        q: deque[str] = deque()
        seen: Set[str] = set(captured_set)
        for item in raw_q:
            u = normalize_url(item)
            if u not in seen:
                seen.add(u)
                q.append(u)

        limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
        headers = browser_headers(USER_AGENT)
        if self.cookie_header:
            headers["Cookie"] = self.cookie_header.split("\n")[0].strip()
            if headers["Cookie"].lower().startswith("cookie:"):
                headers["Cookie"] = headers["Cookie"].split(":", 1)[1].strip()
        client_kwargs = dict(headers=headers, limits=limits, verify=True, follow_redirects=True)
        if self.proxy:
            client_kwargs["proxy"] = self.proxy

        this_round: Dict[str, Dict[str, Any]] = {}
        first_page = len(captured_list) == 0

        async with httpx.AsyncClient(**client_kwargs) as client:
            # First round only: seed sitemap + (later) SPA common paths after first page
            if first_page:
                for s in await self._seed_from_sitemap(client):
                    if s not in seen:
                        seen.add(s)
                        q.append(s)

            while q and len(this_round) < max(1, int(limit)):
                url = q.popleft()
                if url in captured_set:
                    continue
                html, meta = await self.fetch(client, url)
                status = meta.get("status") or 0
                # Skip hard failures with no body
                if (status >= 400 and not html) or meta.get("error") and not html:
                    captured_set.add(url)
                    captured_list.append(url)
                    this_round[url] = {
                        "url": url,
                        "final_url": meta.get("final_url", url),
                        "status": status,
                        "headers": {},
                        "content_type": meta.get("content_type"),
                        "size": meta.get("size"),
                        "sha256": meta.get("sha256"),
                        "error": meta.get("error") or f"HTTP {status}",
                        "html": None,
                        "links": [],
                    }
                    continue

                page_record = {
                    "url": url,
                    "final_url": meta.get("final_url", url),
                    "status": status,
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
                    "links": [],
                }
                if html:
                    page_record["links"] = self.extract_links(html, meta.get("final_url", url))
                    for link in page_record["links"]:
                        if link not in seen:
                            seen.add(link)
                            q.append(link)
                    # SPA bootstrap: homepage mined almost no classic links
                    if first_page and len(this_round) == 0 and len(page_record["links"]) < 3:
                        for seed in self._common_seed_urls():
                            if seed not in seen:
                                seen.add(seed)
                                q.append(seed)
                        first_page = False

                this_round[url] = page_record
                captured_set.add(url)
                captured_list.append(url)
                self.pages[url] = page_record
                await asyncio.sleep(0.12)

        # Cap remaining queue so free hosts don't explode
        remaining = list(q)[:5000]

        return {
            "start_url": self.start_url,
            "origin": self.origin,
            "pages": this_round,
            "pages_crawled": len(this_round),
            "captured": captured_list,
            "queue": remaining,
            "complete": len(remaining) == 0,
            "all_links": sorted(self.links_found),
            "errors": self.errors,
        }
