"""Tests for optional production search-provider adapters."""

import asyncio


def test_brave_search_maps_web_results(monkeypatch):
    from app import evidence

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "web": {
                    "results": [{
                        "title": "Official statistic",
                        "url": "https://www.imf.org/example",
                        "description": "Authoritative economic evidence.",
                    }]
                }
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(evidence.httpx, "AsyncClient", lambda **_kwargs: Client())
    monkeypatch.setattr(evidence.settings, "brave_search_api_key", "test-key")

    results = asyncio.run(evidence.search_brave("IMF growth forecast", 5))

    assert results == [{
        "title": "Official statistic",
        "url": "https://www.imf.org/example",
        "snippet": "Authoritative economic evidence.",
        "source": "brave_search",
    }]


def test_serpapi_maps_organic_results(monkeypatch):
    from app import evidence

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "organic_results": [{
                    "title": "WHO guidance",
                    "link": "https://www.who.int/example",
                    "snippet": "Primary health guidance.",
                }]
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(evidence.httpx, "AsyncClient", lambda **_kwargs: Client())
    monkeypatch.setattr(evidence.settings, "serpapi_key", "test-key")

    results = asyncio.run(evidence.search_serpapi("WHO guidance", 5))

    assert results == [{
        "title": "WHO guidance",
        "url": "https://www.who.int/example",
        "snippet": "Primary health guidance.",
        "source": "serpapi",
    }]
