"""Tests for domain-specific primary-source retrieval connectors."""

import asyncio


def test_bls_connector_returns_us_inflation_evidence(monkeypatch):
    """A US inflation claim should get a BLS CPI-U primary-source card."""
    from app import evidence

    payload = {
        "status": "REQUEST_SUCCEEDED",
        "Results": {
            "series": [{
                "data": [
                    {"year": "2024", "period": "M12", "periodName": "December", "value": "315.605"},
                    {"year": "2023", "period": "M12", "periodName": "December", "value": "306.746"},
                ]
            }]
        },
    }

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(evidence.httpx, "AsyncClient", lambda **_kwargs: Client())

    results = asyncio.run(evidence.search_bls_cpi("US inflation fell by 50% in 2024."))

    assert len(results) == 1
    result = results[0]
    assert result["url"] == "https://www.bls.gov/cpi/"
    assert result["source"] == "bls_cpi_api"
    assert "2.9%" in result["snippet"]
    assert "315.605" in result["snippet"]


def test_bls_connector_ignores_non_us_or_non_inflation_claims():
    from app.evidence import search_bls_cpi

    assert asyncio.run(search_bls_cpi("Ireland's CPI rose in 2024.")) == []
    assert asyncio.run(search_bls_cpi("The United States elected a president.")) == []


def test_retrieve_evidence_preserves_direct_bls_api_evidence(monkeypatch):
    """A direct BLS API result is evidence itself; do not re-scrape its web page."""
    from app import evidence

    direct = [{
        "title": "Consumer Price Index for All Urban Consumers (CPI-U), 2024",
        "url": "https://www.bls.gov/cpi/",
        "snippet": "BLS CPI-U was 315.605 in December 2024 compared with 306.746 in December 2023: a 2.9% increase.",
        "source": "bls_cpi_api",
        "published_date": "2024-12-31",
        "retrieval_status": "ok",
        "relevance": 1.0,
    }]
    async def return_direct(*_args, **_kwargs):
        return direct

    monkeypatch.setattr(evidence, "search_evidence", return_direct)

    async def fail_if_called(_url):
        raise AssertionError("Direct API evidence must not be fetched as an HTML page")

    monkeypatch.setattr(evidence, "fetch_page", fail_if_called)

    citations = asyncio.run(
        evidence.retrieve_evidence("US inflation fell by 50% in 2024.", use_llm=False)
    )

    assert len(citations) == 1
    assert citations[0]["tier"] == "primary"
    assert citations[0]["retrieval_status"] == "ok"
    assert "2.9%" in citations[0]["snippet"]
