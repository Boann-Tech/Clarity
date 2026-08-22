"""Tests for Clarity backend — source tiering, evidence retrieval, verdict calculation."""

from app.models import CheckRequest, Verdict
from app.sources import classify_domain, deduplicate_and_rank
from app.verdict import calculate_verdict


# ── Source tiering ──


def test_classify_primary_domain():
    result = classify_domain("https://www.who.int/publications/i/item/123")
    assert result.tier == "primary"


def test_classify_fact_check_domain():
    result = classify_domain("https://www.reuters.com/article/world/fact-check")
    assert result.tier == "fact_check"


def test_classify_secondary_news():
    result = classify_domain("https://www.bbc.com/news/world")
    assert result.tier == "secondary_news"


def test_classify_excluded_social():
    result = classify_domain("https://twitter.com/user/status/123")
    assert result.tier == "excluded"
    assert not result.is_independent


def test_classify_unknown():
    result = classify_domain("https://some-random-blog.com/post")
    assert result.tier == "unknown"


def test_classify_subdomain_match():
    result = classify_domain("https://data.gov.ie/dataset/123")
    assert result.tier == "primary"


# ── Deduplication and ranking ──


def test_deduplicate_by_url():
    sources = [
        {"url": "https://example.com/1", "title": "A"},
        {"url": "https://example.com/1", "title": "A duplicate"},
        {"url": "https://example.com/2", "title": "B"},
    ]
    ranked = deduplicate_and_rank(sources)
    assert len(ranked) == 2  # duplicate removed
    urls = [r["url"] for r in ranked]
    assert "https://example.com/1" in urls
    assert "https://example.com/2" in urls


def test_excluded_sources_filtered_out():
    sources = [
        {"url": "https://twitter.com/user/123", "title": "Tweet"},
        {"url": "https://reuters.com/article", "title": "News"},
    ]
    ranked = deduplicate_and_rank(sources)
    assert len(ranked) == 1
    assert ranked[0]["tier"] == "fact_check"


# ── Verdict calculation ──


def test_verdict_unverified_empty():
    assessment = calculate_verdict([])
    assert assessment.verdict == Verdict.unverified
    assert assessment.confidence == 0.0


def test_verdict_secondary_only():
    citations = [
        {"url": "https://bbc.com/news", "tier": "secondary_news", "published_date": "2026-01-01"},
        {"url": "https://bbc.com/news/2", "tier": "secondary_news", "published_date": "2026-01-02"},
    ]
    assessment = calculate_verdict(citations)
    assert assessment.verdict == Verdict.unverified
    assert assessment.confidence == 0.2  # secondary only, low confidence


def test_verdict_supported_with_primary():
    citations = [
        {"url": "https://who.int/doc", "tier": "primary", "published_date": "2026-01-01"},
        {"url": "https://reuters.com/check", "tier": "fact_check", "published_date": "2026-01-02"},
    ]
    assessment = calculate_verdict(citations)
    assert assessment.verdict == Verdict.supported
    assert assessment.confidence > 0.5


def test_verdict_supported_single_primary():
    citations = [
        {"url": "https://bls.gov/data", "tier": "primary", "published_date": "2026-01-01"},
    ]
    assessment = calculate_verdict(citations)
    assert assessment.verdict == Verdict.supported
    assert assessment.confidence > 0.3


# ── Request validation ──


def test_check_request_normalizes_whitespace():
    req = CheckRequest(claim="  Inflation   fell  2.3%  ")
    assert req.claim == "Inflation fell 2.3%"
    assert req.normalize_claim(req.claim) == "Inflation fell 2.3%"