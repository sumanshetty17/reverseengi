"""
Shared test fixtures.

security.py deliberately does a real socket.getaddrinfo() lookup as part of
its SSRF guard (Section 10: re-check redirect destinations, resolve and
inspect the actual IP). That's correct behavior in production, but it means
tests using fake hostnames like "good-a.example" need DNS mocked out so the
test suite runs fully offline and deterministically.

Any literal IP address in a test URL (e.g. http://127.0.0.1/, or
http://169.254.169.254/) is unaffected by this fixture — ipaddress parsing
of a literal doesn't go through getaddrinfo's hostname-resolution path in a
way that changes the outcome, and blocked-range literals must still be
blocked regardless of DNS.
"""
import socket

import pytest

_REAL_GETADDRINFO = socket.getaddrinfo
_PUBLIC_TEST_IP = "93.184.216.34"  # example.com's long-standing public IP


def _fake_getaddrinfo(host, *args, **kwargs):
    # Let literal IP addresses resolve exactly as given (so blocked-IP tests
    # still correctly exercise the blocking logic).
    try:
        socket.inet_aton(host)
        return _REAL_GETADDRINFO(host, *args, **kwargs)
    except OSError:
        pass
    if host in ("localhost",):
        return _REAL_GETADDRINFO(host, *args, **kwargs)
    # Any other test hostname (the *.example ones used in these tests)
    # resolves to a fixed public IP so the SSRF guard passes and the
    # (respx-mocked) HTTP layer takes over.
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_PUBLIC_TEST_IP, 0))]


@pytest.fixture(autouse=True)
def mock_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    yield
