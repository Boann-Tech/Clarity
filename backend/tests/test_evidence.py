"""Evidence-retrieval tests using mocked HTTP clients."""

import asyncio
from unittest.mock import patch

from app.evidence import search_bing_rss, search_ddg


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
