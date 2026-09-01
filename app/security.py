"""
security.py
------------
Security boundary for SiteScope. Every outbound fetch — including redirect
hops — must be validated here before a byte is requested.

Responsibilities:
  - Only allow http:// and https:// URLs.
  - Resolve hostnames and reject anything that points at loopback, private,
    link-local, multicast, reserved, or unspecified address space (SSRF
    guard), including after a DNS lookup ("DNS rebinding" style checks).
  - Re-validate every redirect target the same way, not just the original URL.
  - Centralize the configurable limits (timeouts, byte caps, asset caps,
    crawl depth/page caps).
  - Provide a scrub_headers() helper so cookies / Authorization / API keys
    from a target site are never persisted into a report by accident.

This module intentionally does NOT perform any fetching itself — that is
analyzer.py's job. Keeping the two separate means the crawler can never
"forget" to call the security checks, because it has no other way to get
permission to fetch.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse


class SecurityError(Exception):
    """Raised when a URL fails the SSRF / scheme / policy checks."""


# ---------------------------------------------------------------------------
# Configurable limits (Section 10 of the spec: "Enforce timeouts, byte/asset/
# page/crawl limits").
# ---------------------------------------------------------------------------
@dataclass
class Limits:
    connect_timeout_s: float = 8.0
    read_timeout_s: float = 15.0
    total_timeout_s: float = 25.0
    max_redirects: int = 5
    max_page_bytes: int = 3_000_000        # cap on the main HTML document
    max_asset_bytes: int = 5_000_000       # cap per individual asset
    max_assets_per_page: int = 60          # how many assets we'll fetch/list
    max_pages_per_crawl: int = 25          # Phase 6 controlled crawl cap
    max_crawl_depth: int = 2
    user_agent: str = (
        "SiteScopeBot/1.0 (+https://example.invalid/sitescope; "
        "public-website-analysis; respects robots.txt)"
    )


DEFAULT_LIMITS = Limits()

ALLOWED_SCHEMES = {"http", "https"}

# Headers that must never be forwarded to the target, and never stored in a
# report if somehow echoed back (Section 10 / 16).
SENSITIVE_REQUEST_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "x-api-key",
}
SENSITIVE_RESPONSE_HEADERS = {
    "set-cookie",
    "authorization",
    "proxy-authenticate",
    "www-authenticate",
}


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    """True if this address must never be contacted (SSRF guard)."""
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or getattr(ip, "is_site_local", False)
    )


def validate_scheme_and_host(url: str) -> str:
    """
    Basic structural validation: scheme must be http/https, host must be
    present. Returns the normalized hostname. Raises SecurityError otherwise.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise SecurityError(f"Scheme '{parsed.scheme}' is not allowed (only http/https).")
    if not parsed.hostname:
        raise SecurityError("URL has no hostname.")
    if parsed.username or parsed.password:
        raise SecurityError("URLs containing embedded credentials are not allowed.")
    return parsed.hostname


def resolve_and_check(hostname: str) -> list[str]:
    """
    Resolve hostname to IP addresses and ensure NONE of them fall into
    blocked ranges. Returns the list of resolved IPs (str) if safe.

    We check every resolved address (A and AAAA), not just the first one,
    since a hostname can round-robin between a public IP and a private one.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise SecurityError(f"Could not resolve host '{hostname}': {e}") from e

    ips: list[str] = []
    for family, _, _, _, sockaddr in infos:
        raw_ip = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        if _is_blocked_ip(ip_obj):
            raise SecurityError(
                f"Host '{hostname}' resolves to a disallowed address ({raw_ip}). "
                "Internal, private, loopback, and link-local targets are blocked."
            )
        ips.append(raw_ip)

    if not ips:
        raise SecurityError(f"Host '{hostname}' did not resolve to any usable address.")
    return ips


def validate_url(url: str) -> str:
    """
    Full pre-flight validation used before the *initial* request and again
    before *every* redirect hop. Returns the hostname on success.
    """
    hostname = validate_scheme_and_host(url)
    resolve_and_check(hostname)
    return hostname


def scrub_request_headers(headers: dict) -> dict:
    """Strip anything we must never forward to a third-party site."""
    return {k: v for k, v in headers.items() if k.lower() not in SENSITIVE_REQUEST_HEADERS}


def scrub_response_headers(headers: dict) -> dict:
    """
    Strip anything we must never persist into a report (Section 10:
    'Never expose cookies, Authorization headers or API keys in reports').
    The *presence* of a security-relevant header (e.g. Set-Cookie existed)
    can still be recorded as a boolean observation elsewhere; this function
    only guards the raw value.
    """
    return {k: v for k, v in headers.items() if k.lower() not in SENSITIVE_RESPONSE_HEADERS}


def sensitive_response_header_names_present(headers: dict) -> list[str]:
    """Non-invasive observation: which sensitive header *names* were seen."""
    return sorted({k for k in headers if k.lower() in SENSITIVE_RESPONSE_HEADERS})
