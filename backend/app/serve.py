"""Production entry point: `python -m app.serve`, the Docker image's command.

Listens on $PORT (Railway sets it; 8000 otherwise) on every IPv6 and IPv4 address: the
frontend reaches us over Railway's private network (IPv6), the edge and health checks may
use either. asyncio would bind "::" as IPv6-only, so the socket is made here, dual-stack.

Client IPs (rate limits, the admin audit log) come from X-Forwarded-For only when the
connection itself comes from a trusted proxy. By default that's private and loopback
addresses: the Next.js server calls us over the private network, and nobody on the
internet can connect from those addresses, so a forged X-Forwarded-For sent straight to our
public domain is ignored. Of the forwarded addresses, uvicorn takes the rightmost one that
isn't trusted, i.e. the one Railway's edge saw. FORWARDED_ALLOW_IPS replaces the list
(comma-separated addresses and CIDRs) if a platform needs something else.

One worker on purpose: rate limits live in process memory (app/auth/ratelimit.py)."""

import ipaddress
import os
import socket
from collections.abc import Mapping

import uvicorn

_PRIVATE_V4 = ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")
_PRIVATE_V6 = ("::1/128", "fc00::/7")


def _mapped(net: str) -> str:
    """The same IPv4 network as seen on a dual-stack socket: ::ffff:10.0.0.0/104."""
    v4 = ipaddress.ip_network(net)
    return f"::ffff:{v4.network_address}/{96 + v4.prefixlen}"


PRIVATE_NETWORKS = ",".join([*_PRIVATE_V4, *map(_mapped, _PRIVATE_V4), *_PRIVATE_V6])


def options(env: Mapping[str, str] = os.environ) -> dict:
    return {
        "host": env.get("HOST") or "::",
        "port": int(env.get("PORT") or 8000),
        "proxy_headers": True,
        "forwarded_allow_ips": env.get("FORWARDED_ALLOW_IPS") or PRIVATE_NETWORKS,
        "server_header": False,
        # Railway sends SIGTERM, then SIGKILL after the service's draining time.
        "timeout_graceful_shutdown": 20,
    }


def dual_stack_socket(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.bind(("::", port))
    return sock


def main() -> None:
    opts = options()
    server = uvicorn.Server(uvicorn.Config("app.main:app", **opts))
    server.run(sockets=[dual_stack_socket(opts["port"])] if opts["host"] == "::" else None)


if __name__ == "__main__":
    main()
