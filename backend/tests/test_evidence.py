"""Evidence-retrieval tests using mocked HTTP clients."""

import asyncio
from unittest.mock import patch

from app.evidence import fetch_page, search_bing_rss, search_ddg


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

    class Response:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = "<html><body><article>" + ("CPI evidence. " * 30_000) + "</article></body></html>"

        def raise_for_status(self):
            return None

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(evidence.httpx, "AsyncClient", lambda **kwargs: Client())

    html = asyncio.run(fetch_page("https://www.bls.gov/news.release/cpi.htm"))

    assert html is not None
    assert "CPI evidence" in html


def test_fetch_page_rejects_large_untrusted_html(monkeypatch):
    """Large unknown pages remain rejected to bound retrieval resource use."""
    from app import evidence

    class Response:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = "<html>" + ("x" * 200_001) + "</html>"

        def raise_for_status(self):
            return None

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(evidence.httpx, "AsyncClient", lambda **kwargs: Client())

    assert asyncio.run(fetch_page("https://untrusted.example/article")) is None


def test_fetch_page_retries_curated_source_with_browser_user_agent(monkeypatch):
    """Some authoritative sites reject custom bots but accept a browser UA."""
    from app import evidence

    seen_user_agents = []

    class Response:
        def __init__(self, status_code, text):
            self.status_code = status_code
            self.headers = {"content-type": "text/html"}
            self.text = text

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, _url, headers):
            seen_user_agents.append(headers["User-Agent"])
            if len(seen_user_agents) == 1:
                return Response(403, "blocked")
            return Response(200, "<html><body>Official CPI release</body></html>")

    monkeypatch.setattr(evidence.httpx, "AsyncClient", lambda **kwargs: Client())

    html = asyncio.run(fetch_page("https://www.bls.gov/news.release/cpi.htm"))

    assert html is not None
    assert "Official CPI release" in html
    assert len(seen_user_agents) == 2
    assert "Mozilla/5.0" in seen_user_agents[1]
