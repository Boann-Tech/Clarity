import asyncio
import ipaddress

import httpcore
import pytest

from app import egress


def _infos(*addresses):
    return [(None, None, None, None, (address, 0)) for address in addresses]


async def _resolver(mapping):
    async def resolve(host):
        if host not in mapping:
            raise OSError("no such host")
        return mapping[host]
    return resolve


def test_resolves_all_global_addresses():
    resolver = asyncio.run(_resolver({"example.com": _infos("93.184.216.34", "2606:2800:220:1::1")}))
    result = asyncio.run(egress.resolve_public_ips("example.com", resolver=resolver))
    assert result == ["93.184.216.34", "2606:2800:220:1::1"]


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "fe80::1"])
def test_rejects_non_global_addresses(address):
    resolver = asyncio.run(_resolver({"example.com": _infos(address)}))
    with pytest.raises(egress.BlockedHostError):
        asyncio.run(egress.resolve_public_ips("example.com", resolver=resolver))


def test_rejects_mixed_public_and_private_answers():
    resolver = asyncio.run(_resolver({"example.com": _infos("93.184.216.34", "10.0.0.5")}))
    with pytest.raises(egress.BlockedHostError):
        asyncio.run(egress.resolve_public_ips("example.com", resolver=resolver))


def test_rejects_empty_and_failed_resolution():
    empty = asyncio.run(_resolver({"example.com": []}))
    with pytest.raises(egress.BlockedHostError):
        asyncio.run(egress.resolve_public_ips("example.com", resolver=empty))
    failed = asyncio.run(_resolver({}))
    with pytest.raises(egress.BlockedHostError):
        asyncio.run(egress.resolve_public_ips("example.com", resolver=failed))


class FakeStream:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


class FakeDelegate:
    def __init__(self, failures=0):
        self.dialled = []
        self.failures = failures

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.dialled.append((host, port))
        if len(self.dialled) <= self.failures:
            raise httpcore.ConnectError("refused")
        return FakeStream()

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise AssertionError("unix socket must not be delegated")

    async def sleep(self, seconds):
        return None


def test_backend_dials_resolved_ip_not_hostname(monkeypatch):
    async def fake_resolve(host):
        return ["93.184.216.34"]

    monkeypatch.setattr(egress, "resolve_public_ips", fake_resolve)
    delegate = FakeDelegate()
    backend = egress.PublicOnlyBackend(delegate=delegate)
    stream = asyncio.run(backend.connect_tcp("example.com", 443))
    assert isinstance(stream, FakeStream)
    assert delegate.dialled == [("93.184.216.34", 443)]


def test_backend_falls_back_across_validated_addresses(monkeypatch):
    async def fake_resolve(host):
        return ["93.184.216.34", "93.184.216.35"]

    monkeypatch.setattr(egress, "resolve_public_ips", fake_resolve)
    delegate = FakeDelegate(failures=1)
    backend = egress.PublicOnlyBackend(delegate=delegate)
    asyncio.run(backend.connect_tcp("example.com", 443))
    assert delegate.dialled == [("93.184.216.34", 443), ("93.184.216.35", 443)]


def test_backend_raises_when_all_addresses_fail(monkeypatch):
    async def fake_resolve(host):
        return ["93.184.216.34"]

    monkeypatch.setattr(egress, "resolve_public_ips", fake_resolve)
    backend = egress.PublicOnlyBackend(delegate=FakeDelegate(failures=99))
    with pytest.raises(egress.BlockedHostError):
        asyncio.run(backend.connect_tcp("example.com", 443))


def test_backend_refuses_unix_sockets():
    backend = egress.PublicOnlyBackend(delegate=FakeDelegate())
    with pytest.raises(egress.BlockedHostError):
        asyncio.run(backend.connect_unix_socket("/tmp/socket"))


def test_build_pool_uses_validating_backend():
    pool = egress.build_pool()
    assert isinstance(pool, httpcore.AsyncConnectionPool)
    assert isinstance(pool._network_backend, egress.PublicOnlyBackend)
