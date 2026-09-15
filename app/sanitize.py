"""
Strip private secrets from collected HTML/JS before writing reconstruction.
Public publishable keys can be replaced with env placeholders for the user to fill.
"""

from __future__ import annotations

import re
from typing import List, Tuple

# Patterns that must never ship in a reconstruction (private secrets)
_SECRET_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"sk_live_[A-Za-z0-9]+"), "YOUR_SECRET_KEY_NOT_INCLUDED"),
    (re.compile(r"sk_test_[A-Za-z0-9]+"), "YOUR_SECRET_KEY_NOT_INCLUDED"),
    (re.compile(r"rk_live_[A-Za-z0-9]+"), "YOUR_SECRET_KEY_NOT_INCLUDED"),
    (re.compile(r"rk_test_[A-Za-z0-9]+"), "YOUR_SECRET_KEY_NOT_INCLUDED"),
    (re.compile(r"whsec_[A-Za-z0-9]+"), "YOUR_WEBHOOK_SECRET_NOT_INCLUDED"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]+"), "YOUR_SLACK_TOKEN_NOT_INCLUDED"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "YOUR_GITHUB_TOKEN_NOT_INCLUDED"),
    (re.compile(r"github_pat_[A-Za-z0-9_]+"), "YOUR_GITHUB_TOKEN_NOT_INCLUDED"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "YOUR_AWS_KEY_NOT_INCLUDED"),
    (re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"][^'\"]+['\"]"), "aws_secret_access_key=YOUR_SECRET_NOT_INCLUDED"),
    (re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC )?PRIVATE KEY-----"), "/* PRIVATE KEY REMOVED */"),
    (re.compile(r"(?i)(api[_-]?secret|client_secret|private[_-]?key|secret[_-]?key)\s*[=:]\s*['\"][^'\"]{8,}['\"]"), r"\1=YOUR_SECRET_NOT_INCLUDED"),
]

# Publishable / frontend keys → placeholder so user plugs their own
_PUBLIC_REPLACE: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"pk_live_[A-Za-z0-9]+"), "pk_live_YOUR_PUBLISHABLE_KEY"),
    (re.compile(r"pk_test_[A-Za-z0-9]+"), "pk_test_YOUR_PUBLISHABLE_KEY"),
    (re.compile(r"AIza[0-9A-Za-z\-_]{30,}"), "YOUR_GOOGLE_BROWSER_KEY"),
]


def sanitize_content(text: str) -> str:
    if not text:
        return text
    out = text
    for pat, repl in _SECRET_PATTERNS:
        out = pat.sub(repl, out)
    for pat, repl in _PUBLIC_REPLACE:
        out = pat.sub(repl, out)
    return out


def env_example_lines(detected_public_services: List[str] | None = None) -> str:
    lines = [
        "# Add YOUR own keys later. Private keys from the original site are never stored.",
        "PORT=3000",
        "NODE_ENV=production",
        "",
        "# Auth (e.g. Clerk) — create your own application and paste keys here",
        "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_YOUR_KEY",
        "CLERK_SECRET_KEY=sk_test_YOUR_KEY",
        "",
        "# Your product API (if you rebuild backend)",
        "ORBIT_API_KEY=YOUR_API_KEY",
        "API_BASE_URL=https://your-backend.example.com",
        "",
        "# Analytics (optional)",
        "NEXT_PUBLIC_GA_ID=",
        "",
    ]
    if detected_public_services:
        lines.append("# Detected services on source site (for your reference):")
        for s in detected_public_services:
            lines.append(f"# - {s}")
    return "\n".join(lines) + "\n"
