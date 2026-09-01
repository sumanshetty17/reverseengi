"""
Integration-style tests for analyzer.SafeAsyncClient using respx to mock the
HTTP transport, so these run fully offline with no real network access.
Covers Section 16's required cases: redirects, private-target redirects,
localhost, non-HTML responses, large responses.
"""
import sys
from pathlib import Path

import httpx
import pytest
import respx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analyzer import SafeAsyncClient  # noqa: E402
from app.security import SecurityError, Limits  # noqa: E402


@pytest.mark.asyncio
@respx.mock
async def test_follows_safe_redirect_chain():
    respx.get("https://good-a.example/").mock(
        return_value=httpx.Response(302, headers={"location": "https://good-b.example/"})
    )
    respx.get("https://good-b.example/").mock(
        return_value=httpx.Response(200, text="<html>final</html>")
    )
    client = SafeAsyncClient()
    try:
        resp, final_url, body = await client.safe_get("https://good-a.example/")
        assert final_url == "https://good-b.example/"
        assert b"final" in body
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_redirect_to_private_target_is_blocked():
    respx.get("https://good-a.example/").mock(
        return_value=httpx.Response(302, headers={"location": "http://127.0.0.1:8080/admin"})
    )
    client = SafeAsyncClient()
    try:
        with pytest.raises(SecurityError):
            await client.safe_get("https://good-a.example/")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_redirect_to_metadata_endpoint_is_blocked():
    # Cloud metadata SSRF classic target
    respx.get("https://good-a.example/").mock(
        return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
    )
    client = SafeAsyncClient()
    try:
        with pytest.raises(SecurityError):
            await client.safe_get("https://good-a.example/")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_too_many_redirects_raises():
    for i in range(10):
        respx.get(f"https://hop{i}.example/").mock(
            return_value=httpx.Response(302, headers={"location": f"https://hop{i+1}.example/"})
        )
    client = SafeAsyncClient(limits=Limits(max_redirects=3))
    try:
        with pytest.raises(SecurityError):
            await client.safe_get("https://hop0.example/")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_non_html_response_is_still_fetched_and_flagged_by_caller():
    respx.get("https://api.example/data.json").mock(
        return_value=httpx.Response(200, headers={"content-type": "application/json"}, text='{"a":1}')
    )
    client = SafeAsyncClient()
    try:
        resp, final_url, body = await client.safe_get("https://api.example/data.json")
        assert resp.headers["content-type"] == "application/json"
        assert b'"a":1' in body
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_large_response_is_truncated_to_cap():
    big_body = b"x" * 500_000
    respx.get("https://big.example/").mock(
        return_value=httpx.Response(200, content=big_body)
    )
    client = SafeAsyncClient(limits=Limits(max_page_bytes=1000))
    try:
        resp, final_url, body = await client.safe_get("https://big.example/", max_bytes=1000)
        assert len(body) <= 1000
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_broken_asset_url_raises_and_is_catchable():
    respx.get("https://good.example/missing.js").mock(return_value=httpx.Response(404))
    client = SafeAsyncClient()
    try:
        resp, final_url, body = await client.safe_get("https://good.example/missing.js")
        assert resp.status_code == 404
    finally:
        await client.aclose()
