# Security and Throughput Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin evidence fetches to pre-validated public IPs via httpcore, lock and audit dependencies, and replace per-claim rate-limit storms with cache-first accounting plus a batch endpoint the extension uses.

**Architecture:** A new `backend/app/egress.py` provides a validating `httpcore.AsyncNetworkBackend`; `evidence.fetch_page` drives an httpcore pool instead of httpx. Hash-pinned pip-tools locks and CI audits make installs reproducible. `main.py` extracts a reusable per-claim pipeline, checks the cache before charging rate-limit units, and exposes `POST /api/check/batch`; the extension sends one batch request.

**Tech Stack:** Python 3.12 / FastAPI / httpcore 1.x / pip-tools / pytest; TypeScript / vitest.

**Spec:** `docs/superpowers/specs/2026-09-12-security-throughput-hardening-design.md`

## Global Constraints

- Evidence-first behavior is unchanged: verdicts, citations, tiering, classification, and the deterministic fallback keep their current semantics.
- `httpcore>=1.0,<2` becomes a direct dependency; the private `httpcore._backends.anyio.AnyIOBackend` import is allowed only under that pin.
- `httpx` stays for search providers, the BLS connector, and its existing tests. Only the evidence page fetcher moves.
- `/api/check` stays request/response compatible. Only cache-hit accounting and default rate limits change.
- Batch caps: 1–10 claims per request, same whitespace normalization and 10–500 character rules as `CheckRequest`.
- Auth (`CLARITY_API_TOKEN`) applies unchanged to single and batch endpoints.
- No secrets in logs; no behavior change to LLM providers.
- Tests baseline: `cd backend && python3 -m pytest -q` = 111 passing; `npm test` = 16 passing; `npm run build` green.
- Commit identity: prefix every commit with `GIT_AUTHOR_NAME='Sean Lynch' GIT_AUTHOR_EMAIL='sean.lynch@boanntech.com' GIT_COMMITTER_NAME='Sean Lynch' GIT_COMMITTER_EMAIL='sean.lynch@boanntech.com'` (do not change git config).
- Work on branch `feat/security-throughput-hardening`.

---

### Task 1: Pinned egress module

**Files:**
- Create: `backend/app/egress.py`
- Create: `backend/tests/test_egress.py`

**Interfaces:**
- Produces: `class BlockedHostError(Exception)`
- Produces: `async def resolve_public_ips(host: str, resolver=None) -> list[str]`
- Produces: `class PublicOnlyBackend(httpcore.AsyncNetworkBackend)` with `__init__(self, delegate=None)`, `connect_tcp`, `connect_unix_socket`, `sleep`
- Produces: `def build_pool() -> httpcore.AsyncConnectionPool`

- [ ] **Step 1: Write the failing egress tests** — create `backend/tests/test_egress.py`

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_egress.py -q`
Expected: FAIL — `app.egress` does not exist.

- [ ] **Step 3: Implement `backend/app/egress.py`**

```python
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
from typing import Any, Awaitable, Callable

import httpcore
from httpcore._backends.anyio import AnyIOBackend

logger = logging.getLogger("clarity.egress")

Resolver = Callable[[str], Awaitable[list[tuple[Any, ...]]]]


class BlockedHostError(Exception):
    """Raised when a host cannot be dialled because it is not public."""


async def _default_resolver(host: str) -> list[tuple[Any, ...]]:
    return await asyncio.get_running_loop().getaddrinfo(host, None)


async def resolve_public_ips(host: str, resolver: Resolver | None = None) -> list[str]:
    """Resolve a host once and return its addresses only if all are global."""
    resolve = resolver or _default_resolver
    try:
        infos = await resolve(host)
    except OSError as exc:
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
        self._delegate = delegate or AnyIOBackend()

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
```

- [ ] **Step 4: Run egress tests and the full backend suite**

Run: `cd backend && python3 -m pytest tests/test_egress.py -q && python3 -m pytest -q`
Expected: PASS (new tests + 111 baseline).

- [ ] **Step 5: Commit**

```bash
git add backend/app/egress.py backend/tests/test_egress.py
git commit -m "feat: add pinned-public-IP egress network backend"
```

---

### Task 2: Rewrite `fetch_page` on httpcore

**Files:**
- Modify: `backend/app/evidence.py`
- Create: `backend/tests/fake_http.py`
- Modify: `backend/tests/test_fetch_safety.py`
- Modify: `backend/tests/test_evidence.py`

**Interfaces:**
- Consumes: `build_pool()` from Task 1.
- Produces: `async def _request(pool, url, headers, max_bytes) -> tuple[int, dict[str, str], bytes | None]`
- Keeps: `fetch_page(url) -> FetchedPage | None`, `FetchedPage(html, final_url)`.
- Removes: `httpx.AsyncClient` usage from the fetch path and `host_is_public` from `evidence.py` (now in `egress.py`).

- [ ] **Step 1: Create shared httpcore fakes** — `backend/tests/fake_http.py`

```python
"""httpcore-shaped fakes shared by fetch tests."""


class FakeStreamResponse:
    def __init__(self, status_code=200, headers=None, body=b"<html>ok</html>"):
        self.status = status_code
        self.headers = [
            (key.encode("latin-1"), value.encode("latin-1"))
            for key, value in (headers or {"content-type": "text/html"}).items()
        ]
        self._body = body

    async def aiter_stream(self):
        yield self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakePool:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requested = []
        self.headers_seen = []
        self.closed = False

    def stream(self, _method, url, headers=None):
        self.requested.append(str(url))
        self.headers_seen.append(dict(headers or {}))
        return self.responses.pop(0)

    async def aclose(self):
        self.closed = True


def use_pool(monkeypatch, pool):
    from app import evidence

    monkeypatch.setattr(evidence, "build_pool", lambda: pool)
    return pool
```

Then in `backend/tests/test_fetch_safety.py`, import these with `from fake_http import FakePool, FakeStreamResponse, use_pool` (pytest puts the test directory on `sys.path`) and delete the old `FakeStreamResponse`/`FakeAsyncClient` classes and the `_literal_public` helper. Tests that previously patched `evidence.host_is_public` drop that patch: private-IP and redirect targets are now rejected by the curated-tier pre-check or by the pool, and the pinning itself is covered in `test_egress.py`.

Add one pinning-through-fetch test:

```python
def test_fetch_page_returns_none_when_pool_blocks_host(monkeypatch):
    from app import evidence, egress

    class BlockingPool:
        def stream(self, *_args, **_kwargs):
            raise egress.BlockedHostError("rebound")

        async def aclose(self):
            return None

    monkeypatch.setattr(evidence, "build_pool", lambda: BlockingPool())
    assert asyncio.run(evidence.fetch_page("https://www.reuters.com/x")) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_fetch_safety.py -q`
Expected: FAIL — `evidence.build_pool` does not exist yet and fetch_page still uses httpx.

- [ ] **Step 3: Implement the httpcore fetch path in `backend/app/evidence.py`**

Add imports: `from app.egress import build_pool`; remove any now-unused `httpx` import if the search providers no longer need it — they still do, so keep `import httpx`.

Add below the existing helpers:

```python
def _decode_body(body: bytes, headers: dict[str, str]) -> str:
    content_type = headers.get("content-type", "")
    match = re.search(r"charset=([^;\s]+)", content_type, re.IGNORECASE)
    encoding = match.group(1).strip("\"'") if match else "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


async def _request(pool, url: str, headers: dict[str, str], max_bytes: int):
    """One validated hop. Returns (status, headers, body_or_None)."""
    async with pool.stream("GET", url, headers=headers) as response:
        status = response.status
        response_headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in response.headers
        }
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_stream():
            total += len(chunk)
            if total > max_bytes:
                return status, response_headers, None
            chunks.append(chunk)
        return status, response_headers, b"".join(chunks)
```

Replace `_stream_page` and `fetch_page` with:

```python
async def fetch_page(url: str) -> FetchedPage | None:
    """Fetch a curated page, validating every hop against SSRF and tier rules.

    Unknown or excluded domains are never requested. Every connection dials a
    pre-validated public IP (see app.egress). Redirects are followed manually
    (max 5) and every hop must be a public http(s) URL on a curated domain.
    """
    current = url
    pool = build_pool()
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if not is_public_http_url(current):
                return None
            tier = classify_domain(current).tier
            if tier not in CURATED_TIERS:
                return None
            max_bytes = 2_000_000 if tier in {"primary", "fact_check"} else 200_000
            status, headers, body = await _request(
                pool, current, {"User-Agent": settings.user_agent}, max_bytes
            )
            if status in {401, 403, 429}:
                status, headers, body = await _request(pool, current, BROWSER_HEADERS, max_bytes)
            if status in REDIRECT_CODES:
                location = headers.get("location")
                if not location:
                    return None
                current = urljoin(current, location)
                continue
            if status >= 400 or body is None:
                return None
            content_type = headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return None
            if classify_domain(current).tier not in CURATED_TIERS:
                return None
            return FetchedPage(html=_decode_body(body, headers), final_url=current)
    except Exception:
        return None
    finally:
        await pool.aclose()
```

Delete `_stream_page` and the old httpx-based `fetch_page`. `host_is_public` is no longer referenced in `evidence.py`.

- [ ] **Step 4: Migrate `backend/tests/test_evidence.py` fetch tests**

Replace the fetch-related `Client`/`Response` classes with the `FakePool`/`FakeStreamResponse` helpers imported from `test_fetch_safety` (or duplicated locally). Keep `search_ddg`/`search_bing_rss` tests unchanged (they still mock `httpx.AsyncClient`). The two fetch tests become:

```python
def test_fetch_page_accepts_large_primary_source_html(monkeypatch):
    from app import evidence
    from fake_http import FakePool, FakeStreamResponse, use_pool

    body = ("<html><body><article>" + ("CPI evidence. " * 30_000) + "</article></body></html>").encode()
    pool = FakePool([FakeStreamResponse(body=body)])
    use_pool(monkeypatch, pool)

    fetched = asyncio.run(evidence.fetch_page("https://www.bls.gov/news.release/cpi.htm"))

    assert fetched is not None
    assert "CPI evidence" in fetched.html


def test_fetch_page_retries_curated_source_with_browser_user_agent(monkeypatch):
    from app import evidence
    from fake_http import FakePool, FakeStreamResponse, use_pool

    pool = FakePool([
        FakeStreamResponse(status_code=403, body=b"blocked"),
        FakeStreamResponse(body=b"<html><body>Official CPI release</body></html>"),
    ])
    use_pool(monkeypatch, pool)

    fetched = asyncio.run(evidence.fetch_page("https://www.bls.gov/news.release/cpi.htm"))

    assert fetched is not None
    assert "Official CPI release" in fetched.html
    assert len(pool.headers_seen) == 2
    assert "Mozilla/5.0" in pool.headers_seen[1]["User-Agent"]
```

Delete `test_fetch_page_rejects_large_untrusted_html`: unknown-tier URLs are now rejected by the curated-tier pre-check before any request, so that test no longer exercises the size rule; `test_fetch_page_rejects_oversize_body` covers the cap against a curated secondary URL.

- [ ] **Step 5: Run the fetch tests and the full backend suite**

Run: `cd backend && python3 -m pytest tests/test_fetch_safety.py tests/test_evidence.py -q && python3 -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/evidence.py backend/tests/test_fetch_safety.py backend/tests/test_evidence.py
git commit -m "fix: pin evidence fetches to validated public IPs via httpcore"
```

---

### Task 3: Hash-pinned dependency locks and CI audits

**Files:**
- Create: `backend/requirements.in`
- Modify: `backend/requirements.txt` (generated)
- Create: `backend/requirements-dev.in`
- Create: `backend/requirements-dev.txt` (generated)
- Modify: `backend/Dockerfile`
- Modify: `.github/workflows/test.yml`
- Modify: `README.md`

**Interfaces:** none (build/CI/docs).

- [ ] **Step 1: Write the `.in` sources**

`backend/requirements.in`:

```text
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
httpx>=0.28.0
httpcore>=1.0,<2
pydantic>=2.10.0
pydantic-settings>=2.6.0
openai>=1.55.0
defusedxml>=0.7.1
```

`backend/requirements-dev.in`:

```text
-r requirements.in
pytest>=8.0
pip-tools>=7.4
pip-audit>=2.7
```

- [ ] **Step 2: Generate the hash-pinned locks**

```bash
python3 -m pip install --user --break-system-packages 'pip-tools>=7.4'
cd backend
python3 -m piptools compile --generate-hashes --python-version 3.12 --output-file requirements.txt requirements.in
python3 -m piptools compile --generate-hashes --python-version 3.12 --output-file requirements-dev.txt requirements-dev.in
head -5 requirements.txt
```

Expected: both files contain `--generate-hashes` output — pinned `package==version` lines each followed by `--hash=sha256:...` entries. If pip-compile cannot run under Python 3.14 because of a resolver incompatibility, run it with `--python-version 3.12` anyway and report the exact failure rather than hand-writing the lock.

- [ ] **Step 3: Verify the locks install cleanly in a temporary venv-like target**

```bash
python3 -m pip install --user --break-system-packages --dry-run --require-hashes -r backend/requirements.txt
```

Expected: resolution succeeds with hash checking. (The `--dry-run` avoids disturbing the environment.) Record the output.

- [ ] **Step 4: Update `backend/Dockerfile`**

Change the install line to:

```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt \
    && addgroup --system clarity \
    && adduser --system --ingroup clarity clarity
```

Everything else stays as-is (`COPY app`, non-root user, CMD).

- [ ] **Step 5: Update `.github/workflows/test.yml`**

Backend job steps become:

```yaml
      - run: pip install --require-hashes -r requirements-dev.txt
      - run: pip-audit -r requirements.txt
      - run: python -m pytest -q
```

Extension job already runs `npm run build`; add after it:

```yaml
      - run: npm audit --audit-level=high
```

Before committing, run `npm audit --audit-level=high` locally and record the result. If it fails on dev-only advisories that cannot be fixed without a major bump, keep the step but raise the level to the strictest level that passes and document the exact advisories in the report and README; do not silently drop the audit.

- [ ] **Step 6: Document lock regeneration in `README.md`**

In the backend section, add:

````markdown
**Locked dependencies:** `requirements.in` and `requirements-dev.in` hold top-level dependencies; `requirements.txt` and `requirements-dev.txt` are hash-pinned locks generated with pip-tools. After editing a `.in` file, regenerate with Python 3.12:

```bash
cd backend
python3 -m piptools compile --generate-hashes --python-version 3.12 --output-file requirements.txt requirements.in
python3 -m piptools compile --generate-hashes --python-version 3.12 --output-file requirements-dev.txt requirements-dev.in
```

Docker and CI install only the lock files with `--require-hashes`, and CI runs `pip-audit` and `npm audit`.
````

- [ ] **Step 7: Verify Docker build and both suites**

```bash
docker build -t clarity-backend-test ./backend
docker run --rm clarity-backend-test python -c "import app.main"
cd backend && python3 -m pytest -q
npm test && npm run build
```

Expected: image builds with `--require-hashes`, import succeeds, suites green. If Docker cannot reach PyPI, record the failure verbatim.

- [ ] **Step 8: Commit**

```bash
git add backend/requirements.in backend/requirements.txt backend/requirements-dev.in backend/requirements-dev.txt backend/Dockerfile .github/workflows/test.yml README.md
git commit -m "chore: lock Python dependencies with hashes and audit in CI"
```

---

### Task 4: Cache-first rate limiting

**Files:**
- Modify: `backend/app/ratelimit.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Modify: `backend/tests/test_api_ops.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `async def allow_many(self, key: str, count: int, per_minute: int, per_hour: int) -> bool` on `SlidingWindowLimiter` (atomic; never partially consumes).
- Changes: `/api/check` checks the cache before charging one unit; auth remains a dependency; `_enforce_limits(request, count)` becomes a helper, not a dependency.
- Changes defaults: `CLARITY_RATE_LIMIT=60`, `CLARITY_RATE_LIMIT_HOUR=500`.

- [ ] **Step 1: Write failing tests** — update `backend/tests/test_api_ops.py`

Replace `test_rate_limit_returns_429` with two distinct claims, and add:

```python
def test_rate_limit_returns_429(monkeypatch):
    monkeypatch.setattr(config.settings, "rate_limit_per_minute", 1)
    monkeypatch.setattr(config.settings, "rate_limit_per_hour", 100)
    monkeypatch.setattr(config.settings, "api_token", None)
    client = TestClient(app)
    first = {"claim": "Inflation fell to 2 percent in 2024."}
    second = {"claim": "Unemployment rose to 9 percent in 2024."}
    assert client.post("/api/check", json=first).status_code == 200
    assert client.post("/api/check", json=second).status_code == 429


def test_cache_hit_does_not_consume_rate_limit(monkeypatch):
    monkeypatch.setattr(config.settings, "rate_limit_per_minute", 1)
    monkeypatch.setattr(config.settings, "rate_limit_per_hour", 100)
    monkeypatch.setattr(config.settings, "api_token", None)
    client = TestClient(app)
    payload = {"claim": "Inflation fell to 2 percent in 2024."}
    assert client.post("/api/check", json=payload).status_code == 200
    assert client.post("/api/check", json=payload).status_code == 200
    assert client.post("/api/check", json=payload).status_code == 200


def test_rejected_request_does_not_consume(monkeypatch):
    from app import main

    monkeypatch.setattr(config.settings, "rate_limit_per_minute", 1)
    monkeypatch.setattr(config.settings, "rate_limit_per_hour", 100)
    monkeypatch.setattr(config.settings, "api_token", None)
    client = TestClient(app)
    assert client.post("/api/check", json={"claim": "Inflation fell to 2 percent in 2024."}).status_code == 200
    assert client.post("/api/check", json={"claim": "Unemployment rose to 9 percent in 2024."}).status_code == 429
    events = sum(len(queue) for queue in main._rate_limiter._events.values())
    assert events == 1


def test_allow_many_is_atomic():
    from app.ratelimit import SlidingWindowLimiter

    limiter = SlidingWindowLimiter()

    async def run():
        assert await limiter.allow_many("k", 3, 10, 100) is True
        assert await limiter.allow_many("k", 8, 10, 100) is False
        assert await limiter.allow_many("k", 0, 10, 100) is True
        return len(limiter._events["k"])

    assert asyncio.run(run()) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_api_ops.py -q`
Expected: FAIL — `allow_many` missing; same-claim test now passes twice without 429 (cache-first not implemented).

- [ ] **Step 3: Add `allow_many` to `backend/app/ratelimit.py`**

```python
    async def allow_many(self, key: str, count: int, per_minute: int, per_hour: int) -> bool:
        """Check capacity for `count` events and append them atomically."""
        if count <= 0:
            return True
        now = time.monotonic()
        async with self._lock:
            self._evict_stale(now)
            events = self._events.get(key)
            if events is None:
                events = deque()
                if len(self._events) >= self.max_keys:
                    self._events.popitem(last=False)
                self._events[key] = events
            else:
                self._events.move_to_end(key)
            while events and now - events[0] > 3600:
                events.popleft()
            minute_count = sum(1 for ts in events if now - ts <= 60)
            if minute_count + count > per_minute or len(events) + count > per_hour:
                if not events:
                    self._events.pop(key, None)
                return False
            events.extend([now] * count)
            return True

    async def allow(self, key: str, per_minute: int, per_hour: int) -> bool:
        return await self.allow_many(key, 1, per_minute, per_hour)
```

Keep `reset()` and the `_evict_stale` helper as they are; ensure `allow` now delegates so existing behavior is preserved.

- [ ] **Step 4: Rewire `main.py`**

- Remove `_enforce_limits` from the `check_claim` dependency list; keep `_require_token`.
- Change `_enforce_limits` signature to `async def _enforce_limits(request: Request, count: int = 1) -> None` and call `allow_many(client_key, count, ...)`.
- In `check_claim`, after the cache lookup and before `llm_available`:

```python
    await _enforce_limits(request, 1)
```

`check_claim` needs `request: Request` added to its signature (FastAPI injects it).

- [ ] **Step 5: Raise defaults and document**

`backend/app/config.py`: `rate_limit_per_minute` default `"60"`, `rate_limit_per_hour` default `"500"`.
`backend/.env.example` and README API-security section note: cache hits are free; a 10-claim first scan costs 10 units; defaults sized for it.

- [ ] **Step 6: Run the ops tests and full backend suite**

Run: `cd backend && python3 -m pytest tests/test_api_ops.py -q && python3 -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/ratelimit.py backend/app/main.py backend/app/config.py backend/.env.example backend/tests/test_api_ops.py README.md
git commit -m "fix: charge rate limits only for uncached claims"
```

---

### Task 5: Batch endpoint

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_api_batch.py`

**Interfaces:**
- Produces: `BatchCheckRequest(claims: list[str])`, `BatchCheckResponse(request_id: str, results: list[CheckResponse])`.
- Produces: `async def _check_normalized(req, normalized_claim, llm_available, request_id, now) -> CheckResponse` (extracted from `check_claim`).
- Produces: `POST /api/check/batch`.

- [ ] **Step 1: Write failing batch tests** — create `backend/tests/test_api_batch.py`

```python
from fastapi.testclient import TestClient

from app import config, main
from app.main import app


def _client():
    return TestClient(app, raise_server_exceptions=False)


async def _fake_retrieve(claim, max_sources=8, use_llm=False):
    return [{
        "title": "Reuters fact check",
        "publisher": "reuters.com",
        "url": "https://reuters.com/x",
        "snippet": "Passage text.",
        "tier": "fact_check",
        "accessed_at": "2024-01-01T00:00:00Z",
        "relevance_score": 1.0,
        "retrieval_status": "ok",
        "relation": "supports",
    }]


def _stub_llm(monkeypatch):
    import app.llm as llm

    monkeypatch.setattr(llm, "normalize_claim", lambda claim: {
        "normalized_claim": claim, "checkable": True, "search_queries": [claim]
    })
    monkeypatch.setattr(llm, "synthesize_verdict", lambda claim, passages: {
        "verdict": "supported", "confidence": 0.9, "explanation": "ok", "limitations": [],
    })


def test_batch_preserves_order_and_charges_uncached(monkeypatch, llm_enabled):
    monkeypatch.setattr(config.settings, "rate_limit_per_minute", 10)
    monkeypatch.setattr(config.settings, "rate_limit_per_hour", 100)
    monkeypatch.setattr(config.settings, "api_token", None)
    monkeypatch.setattr(config.settings, "cache_ttl_seconds", 60)
    monkeypatch.setattr(main, "retrieve_evidence", _fake_retrieve)
    _stub_llm(monkeypatch)

    claims = [
        "Inflation fell to 2 percent in 2024.",
        "Unemployment rose to 9 percent in 2024.",
        "GDP grew by 1 percent in 2024.",
    ]
    body = _client().post("/api/check/batch", json={"claims": claims}).json()

    assert [result["claim"] for result in body["results"]] == claims
    assert all(result["assessment"]["verdict"] == "supported" for result in body["results"])


def test_batch_cache_hits_are_free_and_skip_retrieval(monkeypatch, llm_enabled):
    monkeypatch.setattr(config.settings, "rate_limit_per_minute", 1)
    monkeypatch.setattr(config.settings, "rate_limit_per_hour", 100)
    monkeypatch.setattr(config.settings, "api_token", None)
    monkeypatch.setattr(config.settings, "cache_ttl_seconds", 60)

    calls = {"retrieve": 0}

    async def counting_retrieve(*_args, **_kwargs):
        calls["retrieve"] += 1
        return []

    monkeypatch.setattr(main, "retrieve_evidence", counting_retrieve)
    _stub_llm(monkeypatch)

    payload = {"claims": ["Inflation fell to 2 percent in 2024."]}
    first = _client().post("/api/check/batch", json=payload)
    second = _client().post("/api/check/batch", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls["retrieve"] == 1


def test_batch_over_budget_returns_429(monkeypatch, llm_enabled):
    monkeypatch.setattr(config.settings, "rate_limit_per_minute", 2)
    monkeypatch.setattr(config.settings, "rate_limit_per_hour", 100)
    monkeypatch.setattr(config.settings, "api_token", None)
    monkeypatch.setattr(main, "retrieve_evidence", _fake_retrieve)
    _stub_llm(monkeypatch)

    payload = {"claims": [
        "Inflation fell to 2 percent in 2024.",
        "Unemployment rose to 9 percent in 2024.",
        "GDP grew by 1 percent in 2024.",
    ]}
    assert _client().post("/api/check/batch", json=payload).status_code == 429


def test_batch_rejects_too_many_or_invalid_claims(monkeypatch):
    monkeypatch.setattr(config.settings, "api_token", None)
    too_many = {"claims": [f"Claim number {index} says something." for index in range(11)]}
    assert _client().post("/api/check/batch", json=too_many).status_code == 422
    short = {"claims": ["too short"]}
    assert _client().post("/api/check/batch", json=short).status_code == 422


def test_batch_requires_token(monkeypatch):
    monkeypatch.setattr(config.settings, "api_token", "secret")
    body = {"claims": ["Inflation fell to 2 percent in 2024."]}
    assert _client().post("/api/check/batch", json=body).status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_api_batch.py -q`
Expected: FAIL — 404 on the batch route.

- [ ] **Step 3: Add the models**

In `backend/app/models.py`:

```python
class BatchCheckRequest(BaseModel):
    claims: list[str] = Field(..., min_length=1, max_length=10)

    @field_validator("claims")
    @classmethod
    def validate_claims(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for claim in value:
            claim = " ".join(claim.split())
            if len(claim) < 10 or len(claim) > 500:
                raise ValueError("each claim must be between 10 and 500 characters")
            normalized.append(claim)
        return normalized


class BatchCheckResponse(BaseModel):
    request_id: str
    results: list[CheckResponse]
```

- [ ] **Step 4: Extract `_check_normalized` and add the batch route in `main.py`**

Move the body of `check_claim` from the line `# Step 1b: Optional LLM claim normalisation for better search queries` through the final `return _finish(CheckResponse(...))` into a new module-level async function with this exact signature:

```python
async def _check_normalized(
    req: CheckRequest,
    normalized_claim: str,
    llm_available: bool,
    request_id: str,
    now: str,
) -> CheckResponse:
```

Inside it, replace every `return _finish(response)` with:

```python
    _response_cache.set(normalized_claim, response.model_dump())
    return response
```

and construct the response as a local named `response` before those returns. Delete the now-unused nested `_finish` helper.

The single endpoint becomes:

```python
@app.post("/api/check")
async def check_claim(
    req: CheckRequest,
    request: Request,
    _: None = Depends(_require_token),
) -> CheckResponse:
    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    normalized_claim = " ".join(req.claim.split())

    cached = _response_cache.get(normalized_claim)
    if cached is not None:
        return CheckResponse.model_validate(cached)

    await _enforce_limits(request, 1)
    return await _check_normalized(req, normalized_claim, get_llm_config().enabled, request_id, now)
```

Add the batch endpoint:

```python
@app.post("/api/check/batch")
async def check_batch(
    req: BatchCheckRequest,
    request: Request,
    _: None = Depends(_require_token),
) -> BatchCheckResponse:
    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    llm_available = get_llm_config().enabled

    results: list[CheckResponse | None] = [None] * len(req.claims)
    pending: list[tuple[int, str]] = []
    for index, claim in enumerate(req.claims):
        cached = _response_cache.get(claim)
        if cached is not None:
            results[index] = CheckResponse.model_validate(cached)
        else:
            pending.append((index, claim))

    await _enforce_limits(request, len(pending))

    semaphore = asyncio.Semaphore(3)

    async def run(index: int, claim: str) -> None:
        async with semaphore:
            single = CheckRequest(claim=claim)
            results[index] = await _check_normalized(
                single, claim, llm_available, str(uuid.uuid4()), now
            )

    await asyncio.gather(*(run(index, claim) for index, claim in pending))
    return BatchCheckResponse(request_id=request_id, results=[r for r in results if r is not None])
```

Keep `limitations`/`policy_version` handling unchanged inside `_check_normalized`; the boundary enforcement and cache write move with it. Ensure `_finish` helper usage is folded into `_check_normalized`'s two return paths (normal and not-checkable).

- [ ] **Step 5: Run the batch tests and the full suite**

Run: `cd backend && python3 -m pytest tests/test_api_batch.py -q && python3 -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/app/main.py backend/tests/test_api_batch.py
git commit -m "feat: add bounded batch claim-check endpoint"
```

---

### Task 6: Extension batch client and docs

**Files:**
- Modify: `src/shared/protocol.ts`
- Modify: `src/background/worker.ts`
- Modify: `src/shared/settings.test.ts`
- Modify: `README.md`

**Interfaces:**
- Produces: `fetchBatchAssessments(claims, settings, fetchFn?)` in `protocol.ts`.
- Changes: `worker.handlePageCheck` performs one batch request for uncached claims; `searchEvidence`/`verifySingleClaim` are replaced.

- [ ] **Step 1: Write the failing batch client tests** — append to `src/shared/settings.test.ts`

```ts
import { DEFAULT_SETTINGS, fetchBatchAssessments } from "./protocol"

describe("fetchBatchAssessments", () => {
  it("posts claims to the batch route with auth and returns results", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = []
    const fakeFetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init: init ?? {} })
      return new Response(JSON.stringify({ results: [{ claim: "A" }] }), { status: 200 })
    }) as typeof fetch

    const outcome = await fetchBatchAssessments(
      ["Inflation fell to 2 percent in 2024."],
      { ...DEFAULT_SETTINGS, backendUrl: "http://localhost:8080", backendToken: "tok" },
      fakeFetch,
    )

    expect(calls).toHaveLength(1)
    expect(calls[0].url).toBe("http://localhost:8080/api/check/batch")
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ claims: ["Inflation fell to 2 percent in 2024."] })
    expect((calls[0].init.headers as Record<string, string>).Authorization).toBe("Bearer tok")
    expect(outcome).toEqual({ results: [{ claim: "A" }] })
  })

  it("maps non-ok responses to an error marker", async () => {
    const fakeFetch = (async () => new Response("nope", { status: 500 })) as typeof fetch
    expect(await fetchBatchAssessments(["A claim long enough."], DEFAULT_SETTINGS, fakeFetch)).toEqual({ error: "HTTP 500" })
  })

  it("maps network failures to null", async () => {
    const fakeFetch = (async () => { throw new Error("down") }) as typeof fetch
    expect(await fetchBatchAssessments(["A claim long enough."], DEFAULT_SETTINGS, fakeFetch)).toBeNull()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test`
Expected: FAIL — `fetchBatchAssessments` is not exported.

- [ ] **Step 3: Add `fetchBatchAssessments` to `protocol.ts`**

```ts
export interface BatchCheckResponse {
  results: Array<{
    claim?: string
    assessment?: { verdict?: string; confidence?: number; explanation?: string }
    citations?: Array<Record<string, unknown>>
    checked_at?: string
  }>
}

export async function fetchBatchAssessments(
  claims: string[],
  settings: AppSettings,
  fetchFn: typeof fetch = fetch,
): Promise<BatchCheckResponse | { error: string } | null> {
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (settings.backendToken) headers.Authorization = `Bearer ${settings.backendToken}`
  try {
    const response = await fetchFn(`${normalizeBackendUrl(settings.backendUrl)}/api/check/batch`, {
      method: "POST",
      headers,
      body: JSON.stringify({ claims }),
      signal: AbortSignal.timeout(120000),
    })
    if (!response.ok) return { error: `HTTP ${response.status}` }
    return await response.json() as BatchCheckResponse
  } catch {
    return null
  }
}
```

- [ ] **Step 4: Rewire `worker.ts`**

Replace `searchEvidence` + `verifySingleClaim` with a batch flow:

```ts
async function handlePageCheck(payload: PagePayload, maxClaims = 10): Promise<{ claims: ClaimCheck[]; error?: string }> {
  const candidates = extractCandidates(payload)
  const limit = Math.min(Math.max(maxClaims, 1), 20)
  const checkableClaims = selectCheckableClaims(candidates, limit)

  if (checkableClaims.length === 0) {
    return { claims: [] }
  }

  const resolved = new Map<string, ClaimCheck>()
  const pending: string[] = []
  for (const claim of checkableClaims) {
    const cached = claimCache.get(claim)
    if (cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
      resolved.set(claim, cached.result)
    } else {
      pending.push(claim)
    }
  }

  if (pending.length > 0) {
    const settings = await getSettings()
    const outcome = await fetchBatchAssessments(pending, settings)
    if (outcome && "results" in outcome) {
      pending.forEach((claim, index) => {
        const raw = outcome.results[index]
        const result = assessmentFromResponse({
          claim: String(raw?.claim ?? claim),
          verdict: String(raw?.assessment?.verdict ?? "unverified"),
          confidence: Number(raw?.assessment?.confidence ?? 0),
          explanation: String(raw?.assessment?.explanation ?? "No validated citations could be retrieved for this claim."),
          citations: mapBackendCitations(raw?.citations ?? []),
          checkedAt: String(raw?.checked_at ?? new Date().toISOString()),
        })
        claimCache.set(claim, { result, timestamp: Date.now() })
        resolved.set(claim, result)
      })
    } else {
      const explanation = outcome && "error" in outcome
        ? `The Clarity backend rejected the request (${outcome.error}). Check the backend URL/token in Settings.`
        : "Offline — the Clarity backend could not be reached. Check your connection or backend URL in Settings."
      for (const claim of pending) {
        const result = assessmentFromResponse({
          claim,
          verdict: "unverified",
          confidence: 0,
          explanation,
          citations: [],
          checkedAt: new Date().toISOString(),
        })
        claimCache.set(claim, { result, timestamp: Date.now() })
        resolved.set(claim, result)
      }
    }
  }

  return { claims: checkableClaims.map((claim) => resolved.get(claim)!) }
}
```

Import `fetchBatchAssessments` in `worker.ts`; delete `searchEvidence`, `verifySingleClaim`, the `SearchOutcome` type, and the now-unused `BackendCheckResponse` type. `mapBackendCitations` stays, and `getSettings` stays.

- [ ] **Step 5: Run extension tests and build**

Run: `npm test && npm run build`
Expected: PASS; `dist/background/worker.js` contains no references to the removed functions.

- [ ] **Step 6: Update `README.md`**

- API-security section: cache hits are free; batch endpoint `POST /api/check/batch` (1–10 claims, bearer token, 429 per uncached claim).
- Endpoints list: add `/api/check/batch`.
- Deploy note: extension and backend should deploy together; a new extension against a backend without the batch route reports a per-claim HTTP 404 error (no fabrication).
- After running both suites, update the test badge and quickstart counts to the actual totals (backend 111 is the pre-task baseline; this program adds tests).

- [ ] **Step 7: Run everything once more and commit**

```bash
cd backend && python3 -m pytest -q
cd .. && npm test && npm run build
git add src/shared/protocol.ts src/background/worker.ts src/shared/settings.test.ts README.md
git commit -m "feat: check claims in one batch request from the extension"
```

---

## Review-Findings Coverage

| Requirement | Task |
|---|---|
| Resolve once, validate all addresses, dial literal IP | 1 |
| Refuse unix sockets, mixed/private/empty DNS | 1 |
| fetch_page on httpcore with per-hop validation, caps, retries | 2 |
| Hash-pinned locks, `--require-hashes`, pip-audit, npm audit | 3 |
| Cache hits free; rejected requests free; atomic multi-charge | 4 |
| Rate-limit defaults sized for 10-claim pages | 4 |
| Batch endpoint: validation, auth, per-uncached charging, bounded concurrency, order | 5 |
| Extension one-request batch with 120s budget and offline/error mapping | 6 |
| Deploy compatibility notes | 6 |

## Self-Review Notes

- Interface consistency: `build_pool` (Task 1) is patched by Task 2's tests; `_request` is Task 2-internal; `allow_many` is used only by Task 4/5 code; `_check_normalized` is Task 5's refactor target after Task 4's endpoint changes.
- Task ordering: Tasks 1–2 (fetch path), 3 (build), 4 (limiter), 5 (batch), 6 (extension). Task 4 touches `main.py` before Task 5 extracts the pipeline; Task 5 therefore performs the extraction against the post-Task-4 file.
- Known risk: Task 3's `npm audit` and `pip-audit` steps can fail on advisories; the plan mandates recording exact findings rather than silently dropping the steps.
- Known risk: pip-compile under Python 3.14 may resolve differently than 3.12; `--python-version 3.12` is mandatory, and failures are reported, not hand-waved.
- Test counts will change; the implementer records actual totals and Task 6 updates README counts if the badge/quickstart become stale.
