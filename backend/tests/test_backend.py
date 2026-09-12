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
        {"url": "https://reuters.com/article/1", "title": "A"},
        {"url": "https://reuters.com/article/1", "title": "A duplicate"},
        {"url": "https://apnews.com/article/2", "title": "B"},
    ]
    ranked = deduplicate_and_rank(sources)
    assert len(ranked) == 2  # duplicate removed
    urls = [r["url"] for r in ranked]
    assert "https://reuters.com/article/1" in urls
    assert "https://apnews.com/article/2" in urls


def test_excluded_sources_filtered_out():
    sources = [
        {"url": "https://twitter.com/user/123", "title": "Tweet"},
        {"url": "https://reuters.com/article", "title": "News"},
    ]
    ranked = deduplicate_and_rank(sources)
    assert len(ranked) == 1
    assert ranked[0]["tier"] == "fact_check"


def test_unknown_sources_are_not_returned_as_public_evidence():
    """Uncurated domains must never reach the CitationSource response boundary."""
    sources = [
        {"url": "https://some-random-blog.com/post", "title": "Uncurated blog"},
        {"url": "https://reuters.com/article", "title": "Trusted fact check"},
    ]

    ranked = deduplicate_and_rank(sources)

    assert [source["url"] for source in ranked] == ["https://reuters.com/article"]
    assert all(source["tier"] != "unknown" for source in ranked)


# ── Verdict calculation ──


def test_verdict_unverified_empty():
    assessment = calculate_verdict([])
    assert assessment.verdict == Verdict.unverified
    assert assessment.confidence == 0.0


def test_verdict_secondary_only():
    citations = [
        {
            "url": "https://bbc.com/news",
            "tier": "secondary_news",
            "published_date": "2026-01-01",
            "snippet": "BBC report.",
            "retrieval_status": "ok",
        },
        {
            "url": "https://bbc.com/news/2",
            "tier": "secondary_news",
            "published_date": "2026-01-02",
            "snippet": "Follow-up report.",
            "retrieval_status": "ok",
        },
    ]
    assessment = calculate_verdict(citations)
    assert assessment.verdict == Verdict.unverified
    assert assessment.confidence == 0.2  # secondary only, low confidence


def test_verdict_context_only_is_unverified():
    citations = [{"url": "https://who.int/doc", "tier": "primary", "snippet": "Fact text.", "retrieval_status": "ok", "relation": "context"}]
    assessment = calculate_verdict(citations)
    assert assessment.verdict == Verdict.unverified


def test_verdict_supports_requires_support_relation():
    citations = [{"url": "https://who.int/doc", "tier": "primary", "snippet": "Fact text.", "retrieval_status": "ok", "relation": "supports"}]
    assert calculate_verdict(citations).verdict == Verdict.supported


def test_verdict_contradicted():
    citations = [{"url": "https://bls.gov/data", "tier": "primary", "snippet": "Contradicts.", "retrieval_status": "ok", "relation": "contradicts"}]
    assert calculate_verdict(citations).verdict == Verdict.contradicted


def test_verdict_misleading_requires_two_independent_hosts():
    same_host = [
        {"url": "https://reuters.com/a", "tier": "fact_check", "snippet": "A", "retrieval_status": "ok", "relation": "supports"},
        {"url": "https://reuters.com/b", "tier": "fact_check", "snippet": "B", "retrieval_status": "ok", "relation": "contradicts"},
    ]
    independent = [
        {"url": "https://reuters.com/a", "tier": "fact_check", "snippet": "A", "retrieval_status": "ok", "relation": "supports"},
        {"url": "https://apnews.com/b", "tier": "fact_check", "snippet": "B", "retrieval_status": "ok", "relation": "contradicts"},
    ]
    assert calculate_verdict(same_host).verdict == Verdict.unverified
    assert calculate_verdict(independent).verdict == Verdict.misleading


def test_verdict_misleading_ignores_context_citation_hosts():
    same_publisher_conflict = [
        {"url": "https://reuters.com/a", "tier": "fact_check", "snippet": "A", "retrieval_status": "ok", "relation": "supports"},
        {"url": "https://reuters.com/b", "tier": "fact_check", "snippet": "B", "retrieval_status": "ok", "relation": "contradicts"},
        {"url": "https://who.int/c", "tier": "primary", "snippet": "C", "retrieval_status": "ok", "relation": "context"},
    ]
    independent_conflict = [
        {"url": "https://reuters.com/a", "tier": "fact_check", "snippet": "A", "retrieval_status": "ok", "relation": "supports"},
        {"url": "https://apnews.com/b", "tier": "fact_check", "snippet": "B", "retrieval_status": "ok", "relation": "contradicts"},
        {"url": "https://who.int/c", "tier": "primary", "snippet": "C", "retrieval_status": "ok", "relation": "context"},
    ]
    assert calculate_verdict(same_publisher_conflict).verdict == Verdict.unverified
    assert calculate_verdict(independent_conflict).verdict == Verdict.misleading


def test_verdict_ignores_unfetched_or_empty_citations():
    citations = [
        {"url": "https://who.int/doc", "tier": "primary", "snippet": "", "retrieval_status": "fetch_error", "relation": "supports"},
        {"url": "https://reuters.com/x", "tier": "fact_check", "snippet": "  ", "retrieval_status": "ok", "relation": "supports"},
    ]
    assert calculate_verdict(citations).verdict == Verdict.unverified


# ── Request validation ──


def test_check_request_normalizes_whitespace():
    req = CheckRequest(claim="  Inflation   fell  2.3%  ")
    assert req.claim == "Inflation fell 2.3%"
    assert req.normalize_claim(req.claim) == "Inflation fell 2.3%"