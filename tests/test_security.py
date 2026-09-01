"""
Tests for security.py — SSRF guard, scheme validation, header scrubbing.
These run entirely offline: they either use literal IPs/hostnames that
resolve locally (localhost, 127.0.0.1) or test pure functions.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import security  # noqa: E402


def test_rejects_non_http_scheme():
    with pytest.raises(security.SecurityError):
        security.validate_scheme_and_host("ftp://example.com/file")


def test_rejects_missing_host():
    with pytest.raises(security.SecurityError):
        security.validate_scheme_and_host("http:///path")


def test_rejects_embedded_credentials():
    with pytest.raises(security.SecurityError):
        security.validate_scheme_and_host("http://user:pass@example.com")


def test_blocks_localhost_hostname():
    with pytest.raises(security.SecurityError):
        security.validate_url("http://localhost:8000/")


def test_blocks_loopback_ip_literal():
    with pytest.raises(security.SecurityError):
        security.validate_url("http://127.0.0.1/")


def test_blocks_private_ip_literal():
    with pytest.raises(security.SecurityError):
        security.validate_url("http://10.0.0.5/")
    with pytest.raises(security.SecurityError):
        security.validate_url("http://192.168.1.1/")
    with pytest.raises(security.SecurityError):
        security.validate_url("http://172.16.0.1/")


def test_blocks_link_local():
    with pytest.raises(security.SecurityError):
        security.validate_url("http://169.254.169.254/")  # cloud metadata endpoint


def test_blocks_unspecified_address():
    with pytest.raises(security.SecurityError):
        security.validate_url("http://0.0.0.0/")


def test_is_blocked_ip_helper_directly():
    import ipaddress
    assert security._is_blocked_ip(ipaddress.ip_address("127.0.0.1"))
    assert security._is_blocked_ip(ipaddress.ip_address("10.1.2.3"))
    assert security._is_blocked_ip(ipaddress.ip_address("::1"))
    assert not security._is_blocked_ip(ipaddress.ip_address("8.8.8.8"))


def test_scrub_request_headers_strips_sensitive():
    headers = {"Authorization": "Bearer xyz", "Cookie": "a=b", "X-Custom": "keep-me"}
    scrubbed = security.scrub_request_headers(headers)
    assert "Authorization" not in scrubbed
    assert "Cookie" not in scrubbed
    assert scrubbed["X-Custom"] == "keep-me"


def test_scrub_response_headers_strips_set_cookie_and_auth():
    headers = {"Set-Cookie": "session=abc123", "Server": "nginx", "WWW-Authenticate": "Basic"}
    scrubbed = security.scrub_response_headers(headers)
    assert "Set-Cookie" not in scrubbed
    assert "WWW-Authenticate" not in scrubbed
    assert scrubbed["Server"] == "nginx"


def test_sensitive_response_header_names_present_reports_names_not_values():
    headers = {"Set-Cookie": "session=super-secret-value"}
    names = security.sensitive_response_header_names_present(headers)
    assert names == ["Set-Cookie"] or names == ["set-cookie"]
    # Ensure the raw secret value never appears in the returned names list
    joined = " ".join(names)
    assert "super-secret-value" not in joined
