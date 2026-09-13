"""Pinned egress: every TCP connection dials a pre-validated public IP.

DNS rebinding is closed by resolving the host once, rejecting any answer that
contains a non-global address, and handing the literal IP to the delegate
network backend so nothing re-resolves the hostname. httpcore derives TLS SNI
and certificate verification from the origin URL host independently of the
dialled address.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from typing import Any, Awaitable, Callable

import httpcore

logger = logging.getLogger("clarity.egress")

Resolver = Callable[[str], Awaitable[list[tuple[Any, ...]]]]


class BlockedHostError(Exception):
    """Raised when a host cannot be dialled because it is not public."""


async def _default_resolver(host: str) -> list[tuple[Any, ...]]:
    return await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)


async def resolve_public_ips(host: str, resolver: Resolver | None = None) -> list[str]:
    """Resolve a host once and return its addresses only if all are global."""
    resolve = resolver or _default_resolver
    try:
        infos = await resolve(host)
    except (OSError, UnicodeError) as exc:
        raise BlockedHostError(f"DNS resolution failed for {host}") from exc

    addresses: list[str] = []
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except (IndexError, ValueError) as exc:
            raise BlockedHostError(f"unparseable DNS answer for {host}") from exc
        if not address.is_global:
            raise BlockedHostError(f"non-public DNS answer for {host}")
        addresses.append(str(address))
    if not addresses:
        raise BlockedHostError(f"no DNS answers for {host}")
    return addresses


class PublicOnlyBackend(httpcore.AsyncNetworkBackend):
    """Network backend that only dials validated public IP literals."""

    def __init__(self, delegate: httpcore.AsyncNetworkBackend | None = None) -> None:
        self._delegate = delegate or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        addresses = await resolve_public_ips(host)
        last_error: Exception | None = None
        for address in addresses:
            try:
                return await self._delegate.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as exc:  # noqa: BLE001 - reported as BlockedHostError
                last_error = exc
        raise BlockedHostError(f"could not connect to any public address for {host}") from last_error

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        raise BlockedHostError("unix sockets are not permitted")

    async def sleep(self, seconds: float) -> None:
        await self._delegate.sleep(seconds)


def build_pool() -> httpcore.AsyncConnectionPool:
    return httpcore.AsyncConnectionPool(network_backend=PublicOnlyBackend())
