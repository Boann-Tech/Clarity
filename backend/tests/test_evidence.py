"""Evidence-retrieval tests using mocked HTTP clients."""

import asyncio
from unittest.mock import patch

from app.evidence import fetch_page, parse_ddg_results, search_bing_rss, search_ddg
from test_fetch_safety import FakeAsyncClient, FakeStreamResponse, _literal_public


class MockResponse:
    def __init__(self, status_code, text="", content=b"", url="https://lite.duckduckgo.com/lite/"):
        self.status_code = status_code
        self.text = text
        self.content = content or text.encode()
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")


class MockClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        return self.response

    async def get(self, *args, **kwargs):
        return self.response


def test_ddg_challenge_page_returns_no_results():
    """DDG's HTTP 202 interstitial must not be parsed as a search result."""
    challenge = '<a href="https://duckduckgo.com/">here</a>'
    response = MockResponse(202, text=challenge)

    with patch("app.evidence.httpx.AsyncClient", return_value=MockClient(response)):
        assert asyncio.run(search_ddg("inflation", 10)) == []


def test_bing_rss_parses_search_items():
    xml = b"""<?xml version='1.0'?><rss><channel><item>
      <title>Consumer Price Index</title>
      <link>https://www.bls.gov/cpi/</link>
      <description>Official BLS CPI statistics</description>
    </item></channel></rss>"""
    response = MockResponse(200, content=xml, url="https://www.bing.com/search")

    with patch("app.evidence.httpx.AsyncClient", return_value=MockClient(response)):
        results = asyncio.run(search_bing_rss("US CPI", 10))

    assert results == [{
        "title": "Consumer Price Index",
        "url": "https://www.bls.gov/cpi/",
        "snippet": "Official BLS CPI statistics",
        "source": "bing_rss",
    }]


def test_fetch_page_accepts_large_primary_source_html(monkeypatch):
    """BLS releases are large pages; size limits apply after text extraction."""
    from app import evidence

    url = "https://www.bls.gov/news.release/cpi.htm"
    body = ("<html><body><article>" + ("CPI evidence. " * 30_000) + "</article></body></html>").encode()
    client = FakeAsyncClient([FakeStreamResponse(body=body, url=url)])
    monkeypatch.setattr(evidence.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(evidence, "host_is_public", _literal_public)

    fetched = asyncio.run(fetch_page(url))

    assert fetched is not None
    assert "CPI evidence" in fetched.html


def test_fetch_page_rejects_large_untrusted_html(monkeypatch):
    """Unknown domains are never fetched, so their body size is irrelevant."""
    from app import evidence

    body = ("<html>" + ("x" * 200_001) + "</html>").encode()
    client = FakeAsyncClient([FakeStreamResponse(body=body, url="https://untrusted.example/article")])
    monkeypatch.setattr(evidence.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(evidence, "host_is_public", _literal_public)

    assert asyncio.run(fetch_page("https://untrusted.example/article")) is None
    assert client.requested == []


def test_fetch_page_retries_curated_source_with_browser_user_agent(monkeypatch):
    """Some authoritative sites reject custom bots but accept a browser UA."""
    from app import evidence

    url = "https://www.bls.gov/news.release/cpi.htm"
    client = FakeAsyncClient([
        FakeStreamResponse(status_code=403, url=url),
        FakeStreamResponse(body=b"<html><body>Official CPI release</body></html>", url=url),
    ])
    monkeypatch.setattr(evidence.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(evidence, "host_is_public", _literal_public)

    fetched = asyncio.run(fetch_page(url))

    assert fetched is not None
    assert "Official CPI release" in fetched.html
    assert len(client.requested) == 2
    assert "Mozilla/5.0" in client.request_headers[1]["User-Agent"]


def test_ddg_parser_accepts_href_before_class():
    html = '<a rel="nofollow" href="https://www.bls.gov/cpi/" class="result-link">CPI</a>'
    assert parse_ddg_results(html, 10) == [
        {"title": "CPI", "url": "https://www.bls.gov/cpi/", "snippet": "", "source": "duckduckgo"}
    ]


def test_ddg_parser_unwraps_uddg_redirect():
    html = (
        '<a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.reuters.com%2Ffact-check%2F1">'
        "Reuters</a>"
    )
    assert parse_ddg_results(html, 10)[0]["url"] == "https://www.reuters.com/fact-check/1"
