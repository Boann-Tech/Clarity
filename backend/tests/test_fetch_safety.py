import asyncio

from app import evidence
from fake_http import FakePool, FakeStreamResponse, use_pool


def _run(coro):
    return asyncio.run(coro)


def test_fetch_page_rejects_private_ip_literal(monkeypatch):
    pool = use_pool(monkeypatch, FakePool([FakeStreamResponse()]))
    assert _run(evidence.fetch_page("http://127.0.0.1:8081/secret")) is None
    assert pool.requested == []


def test_fetch_page_rejects_non_http_scheme():
    assert _run(evidence.fetch_page("file:///etc/passwd")) is None
    assert _run(evidence.fetch_page("ftp://reuters.com/x")) is None


def test_fetch_page_rejects_redirect_to_private_ip(monkeypatch):
    redirect = FakeStreamResponse(status_code=302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
    pool = use_pool(monkeypatch, FakePool([redirect]))
    assert _run(evidence.fetch_page("https://www.reuters.com/redirect")) is None
    assert pool.requested == ["https://www.reuters.com/redirect"]


def test_fetch_page_rejects_redirect_to_untrusted_domain(monkeypatch):
    redirect = FakeStreamResponse(status_code=302, headers={"location": "https://evil.example/phish"})
    pool = use_pool(monkeypatch, FakePool([redirect]))
    assert _run(evidence.fetch_page("https://www.reuters.com/redirect")) is None
    assert pool.requested == ["https://www.reuters.com/redirect"]


def test_fetch_page_returns_final_url_after_trusted_redirect(monkeypatch):
    redirect = FakeStreamResponse(status_code=302, headers={"location": "https://www.bbc.com/news/story"})
    page = FakeStreamResponse(body=b"<html>final</html>")
    use_pool(monkeypatch, FakePool([redirect, page]))
    fetched = _run(evidence.fetch_page("https://www.reuters.com/story"))
    assert fetched is not None
    assert fetched.final_url == "https://www.bbc.com/news/story"
    assert "final" in fetched.html


def test_fetch_page_rejects_oversize_body(monkeypatch):
    page = FakeStreamResponse(body=b"x" * 200_001)
    use_pool(monkeypatch, FakePool([page]))
    assert _run(evidence.fetch_page("https://www.bbc.com/huge")) is None


def test_fetch_page_returns_none_when_pool_blocks_host(monkeypatch):
    from app import evidence, egress

    class BlockingPool:
        def stream(self, *_args, **_kwargs):
            raise egress.BlockedHostError("rebound")

        async def aclose(self):
            return None

    monkeypatch.setattr(evidence, "build_pool", lambda: BlockingPool())
    assert asyncio.run(evidence.fetch_page("https://www.reuters.com/x")) is None


def test_retrieve_evidence_never_fetches_untrusted_domains(monkeypatch):
    results = [
        {"title": "Blog", "url": "https://random-blog.example/post", "snippet": "", "source": "ddg"},
        {"title": "Reuters", "url": "https://www.reuters.com/fact-check/1", "snippet": "", "source": "ddg"},
    ]

    async def fake_search(_claim, max_results=15):
        return results

    async def fake_fetch(url):
        assert "reuters.com" in url, f"must not fetch {url}"
        return evidence.FetchedPage(
            html="<article>Evidence text that directly supports the claim under test.</article>",
            final_url=url,
        )

    monkeypatch.setattr(evidence, "search_evidence", fake_search)
    monkeypatch.setattr(evidence, "fetch_page", fake_fetch)
    citations = _run(evidence.retrieve_evidence("A claim long enough to check.", use_llm=False))
    assert [c["url"] for c in citations] == ["https://www.reuters.com/fact-check/1"]


def test_retrieve_evidence_deduplicates_urls_before_fetch(monkeypatch):
    results = [
        {"title": "A", "url": "https://www.reuters.com/a", "snippet": "", "source": "ddg"},
        {"title": "A dup", "url": "https://www.reuters.com/a", "snippet": "", "source": "bing"},
        {"title": "B", "url": "https://apnews.com/b", "snippet": "", "source": "ddg"},
    ]
    calls = []

    async def fake_search(_claim, max_results=15):
        return results

    async def fake_fetch(url):
        calls.append(url)
        return evidence.FetchedPage(
            html="<article>Evidence text that directly supports the claim under test.</article>",
            final_url=url,
        )

    monkeypatch.setattr(evidence, "search_evidence", fake_search)
    monkeypatch.setattr(evidence, "fetch_page", fake_fetch)
    citations = _run(evidence.retrieve_evidence("A claim long enough to check."))
    assert sorted(calls) == ["https://apnews.com/b", "https://www.reuters.com/a"]
    assert len(citations) == 2


def test_retrieve_evidence_drops_failed_fetches(monkeypatch):
    async def fake_search(_claim, max_results=15):
        return [{"title": "A", "url": "https://www.reuters.com/a", "snippet": "search snippet", "source": "ddg"}]

    async def fake_fetch(_url):
        return None

    monkeypatch.setattr(evidence, "search_evidence", fake_search)
    monkeypatch.setattr(evidence, "fetch_page", fake_fetch)
    assert _run(evidence.retrieve_evidence("A claim long enough to check.")) == []
