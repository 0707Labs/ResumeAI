"""The production server's options, and which client IP the app sees behind the proxies.

Browser -> Railway edge (adds the visitor's address to X-Forwarded-For) -> Next.js (passes
the header through unchanged) -> us over the private network. Run through uvicorn's own
proxy-headers middleware with the options app.serve passes it."""

import asyncio

import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.serve import PRIVATE_NETWORKS, options


def client_seen(peer: str, forwarded_for: str | None, trusted: str = PRIVATE_NETWORKS) -> str:
    seen = {}

    async def app(scope, receive, send):
        seen["client"] = scope["client"][0]

    headers = [(b"x-forwarded-for", forwarded_for.encode())] if forwarded_for else []
    scope = {"type": "http", "client": (peer, 40000), "headers": headers, "scheme": "http"}
    asyncio.run(ProxyHeadersMiddleware(app, trusted_hosts=trusted)(scope, None, None))
    return seen["client"]


def test_options_from_env():
    assert options({}) | {"forwarded_allow_ips": "-"} == {
        "host": "::", "port": 8000, "proxy_headers": True, "forwarded_allow_ips": "-",
        "server_header": False, "timeout_graceful_shutdown": 20}
    assert options({"PORT": "8080", "FORWARDED_ALLOW_IPS": "10.1.0.0/16"})["port"] == 8080
    assert options({"FORWARDED_ALLOW_IPS": "10.1.0.0/16"})["forwarded_allow_ips"] == "10.1.0.0/16"


@pytest.mark.parametrize("peer", ["10.4.0.7", "::ffff:10.4.0.7", "fd12:3456::7", "100.64.1.2", "127.0.0.1"])
def test_the_visitor_address_comes_through_a_private_proxy(peer):
    assert client_seen(peer, "203.0.113.9") == "203.0.113.9"


def test_a_forged_address_before_the_edges_is_ignored():
    # The visitor sent X-Forwarded-For: 198.51.100.1 themselves; the edge appended what it saw.
    assert client_seen("fd12:3456::7", "198.51.100.1, 203.0.113.9") == "203.0.113.9"


@pytest.mark.parametrize("peer", ["203.0.113.50", "::ffff:203.0.113.50", "2001:db8::50"])
def test_a_public_peer_cannot_choose_its_address(peer):
    assert client_seen(peer, "198.51.100.1") == peer


def test_without_the_header_the_peer_is_the_client():
    assert client_seen("10.4.0.7", None) == "10.4.0.7"
