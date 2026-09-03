"""
Download and organize all accessible assets (CSS, JS, images, fonts, etc.).
Maintain resource map: original URL → local path → referencing pages.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse, unquote

import httpx

from app.crawler import USER_AGENT, normalize_url, is_asset_url


def safe_filename(url: str, max_len: int = 120) -> str:
    """Deterministic local filename from URL."""
    parsed = urlparse(url)
    path = unquote(parsed.path)
    name = path.rstrip("/").split("/")[-1] or "index"
    # strip query noise
    name = re.sub(r"[^\w.\-]", "_", name)
    if len(name) > max_len:
        stem, ext = (name.rsplit(".", 1) + [""])[:2]
        name = stem[: max_len - len(ext) - 9] + "_" + hashlib.md5(url.encode()).hexdigest()[:8]
        if ext:
            name = f"{name}.{ext}"
    if not name or name == "_":
        name = hashlib.md5(url.encode()).hexdigest()[:12]
    return name


def guess_type(url: str, content_type: str = "") -> str:
    path = urlparse(url).path.lower()
    ct = (content_type or "").lower()
    if any(path.endswith(e) for e in (".css",)) or "text/css" in ct:
        return "css"
    if any(path.endswith(e) for e in (".js", ".mjs")) or "javascript" in ct:
        return "javascript"
    if any(path.endswith(e) for e in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif")):
        return "image"
    if any(path.endswith(e) for e in (".woff", ".woff2", ".ttf", ".eot", ".otf")):
        return "font"
    if path.endswith(".json") or "application/json" in ct:
        return "json"
    if path.endswith(".map"):
        return "sourcemap"
    if path.endswith((".html", ".htm")):
        return "html"
    return "other"


def local_subdir(asset_type: str) -> str:
    # Everything under public/ so static hosting serves assets at predictable paths
    return {
        "css": "public/css",
        "javascript": "public/js",
        "image": "public/images",
        "font": "public/fonts",
        "json": "public/data",
        "sourcemap": "public/js",
        "html": "public/pages",
        "other": "public/assets",
    }.get(asset_type, "public/assets")


class AssetCollector:
    def __init__(self, base_dir: Path, max_assets: int = 150, timeout: float = 15.0):
        self.base_dir = Path(base_dir)
        self.max_assets = max_assets
        self.timeout = timeout
        self.manifest: List[Dict[str, Any]] = []
        self.url_to_local: Dict[str, str] = {}
        self.downloaded: Set[str] = set()
        self.failed: List[Dict[str, str]] = []

    async def download_one(
        self, client: httpx.AsyncClient, url: str, referenced_by: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        url = normalize_url(url)
        if url in self.downloaded or len(self.manifest) >= self.max_assets:
            return self.url_to_local.get(url) and {
                "original_url": url,
                "local_path": self.url_to_local[url],
                "status": "already_collected",
            }

        try:
            resp = await client.get(url, follow_redirects=True, timeout=self.timeout)
            if resp.status_code >= 400:
                self.failed.append({"url": url, "error": f"HTTP {resp.status_code}"})
                entry = {
                    "original_url": url,
                    "local_path": None,
                    "type": guess_type(url),
                    "referenced_by": referenced_by or [],
                    "status": "failed",
                    "error": f"HTTP {resp.status_code}",
                }
                self.manifest.append(entry)
                return entry

            content = resp.content
            content_type = resp.headers.get("content-type", "")
            asset_type = guess_type(url, content_type)
            subdir = local_subdir(asset_type)
            filename = safe_filename(url)
            # ensure unique
            dest_dir = self.base_dir / subdir
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / filename
            counter = 1
            while dest.exists():
                stem = dest.stem
                dest = dest_dir / f"{stem}_{counter}{dest.suffix}"
                counter += 1

            dest.write_bytes(content)
            local_rel = str(dest.relative_to(self.base_dir)).replace("\\", "/")
            sha = hashlib.sha256(content).hexdigest()

            entry = {
                "original_url": url,
                "local_path": local_rel,
                "type": asset_type,
                "size": len(content),
                "content_type": content_type,
                "referenced_by": referenced_by or [],
                "status": "collected",
                "sha256": sha,
            }
            self.manifest.append(entry)
            self.url_to_local[url] = local_rel
            self.downloaded.add(url)
            return entry
        except Exception as e:
            self.failed.append({"url": url, "error": str(e)})
            entry = {
                "original_url": url,
                "local_path": None,
                "type": guess_type(url),
                "referenced_by": referenced_by or [],
                "status": "failed",
                "error": str(e),
            }
            self.manifest.append(entry)
            return entry

    async def collect_many(
        self, urls: List[str], referenced_by: Optional[Dict[str, List[str]]] = None
    ) -> List[Dict[str, Any]]:
        referenced_by = referenced_by or {}
        unique = list(dict.fromkeys(urls))[: self.max_assets]
        headers = {"User-Agent": USER_AGENT}
        results = []
        async with httpx.AsyncClient(headers=headers, verify=True) as client:
            for u in unique:
                refs = referenced_by.get(u, [])
                r = await self.download_one(client, u, refs)
                if r:
                    results.append(r)
        return results

    def get_manifest(self) -> List[Dict[str, Any]]:
        return self.manifest
