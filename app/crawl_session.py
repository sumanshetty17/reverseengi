"""Durable crawl sessions so each round continues from the last page, with no duplicates."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

SESS_DIR = Path(__file__).resolve().parent.parent / "sessions"
SESS_DIR.mkdir(parents=True, exist_ok=True)


def _path(sid: str) -> Path:
    return SESS_DIR / f"{sid}.json"


def load_session(sid: str) -> Optional[Dict[str, Any]]:
    p = _path(sid)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data.setdefault("captured", [])
        data.setdefault("queue", [])
        data.setdefault("rounds", [])
        data.setdefault("page_map", {})
        data.setdefault("page_seq", 0)
        return data
    except Exception:
        return None


def save_session(s: Dict[str, Any]) -> None:
    s["updated_at"] = datetime.now(timezone.utc).isoformat()
    _path(s["id"]).write_text(json.dumps(s, default=str), encoding="utf-8")


def create_session(start_url: str) -> Dict[str, Any]:
    s: Dict[str, Any] = {
        "id": uuid.uuid4().hex[:10],
        "start_url": start_url,
        "origin": f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}",
        "captured": [],
        "queue": [start_url],
        "rounds": [],
        "page_map": {},
        "page_seq": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    save_session(s)
    return s


def load_or_create(sid: str | None, start_url: str) -> Dict[str, Any]:
    if sid:
        existing = load_session(sid.strip()[:24])
        if existing:
            return existing
    return create_session(start_url)


def page_file_name(url: str, seq: int) -> str:
    path = urlparse(url).path or "/"
    parts = [p for p in path.rstrip("/").split("/") if p]
    slug = "-".join(parts) or "home"
    clean = "".join(c if c.isalnum() or c == "-" else "-" for c in slug).strip("-")[:42] or "page"
    return f"pages/{seq:03d}-{clean.lower()}.html"
