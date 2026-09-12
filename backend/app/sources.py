"""Source tiering and quality ranking for evidence retrieval.

The core ethical invariant of Clarity:
  - No verdict without at least one qualifying citation URL.
  - Misleading requires 2+ independent citations.
  - Unverified = evidence not found, not a judgment on the claim.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Trusted source registry ──
# Domain → tier mapping. Wildcard support via prefix matching.

TRUSTED_SOURCES: dict[str, str] = {
    # Health (primary)
    "who.int": "primary",
    "cdc.gov": "primary",
    "nih.gov": "primary",
    "pubmed.ncbi.nlm.nih.gov": "primary",
    "clinicaltrials.gov": "primary",
    "fda.gov": "primary",
    "ema.europa.eu": "primary",
    "ecdc.europa.eu": "primary",
    "msdmanuals.com": "primary",
    "cochrane.org": "primary",
    # Economics (primary)
    "bls.gov": "primary",
    "worldbank.org": "primary",
    "imf.org": "primary",
    "ecb.europa.eu": "primary",
    "federalreserve.gov": "primary",
    "oecd.org": "primary",
    "eurostat.eu": "primary",
    "cso.ie": "primary",
    "statista.com": "primary",
    # Government & Law (primary)
    "congress.gov": "primary",
    "supremecourt.gov": "primary",
    "gov.ie": "primary",
    "citizensinformation.ie": "primary",
    "eur-lex.europa.eu": "primary",
    "justice.ie": "primary",
    "data.gov.ie": "primary",
    "gov.uk": "primary",
    "legislation.gov.uk": "primary",
    "whitehouse.gov": "primary",
    "usa.gov": "primary",
    "census.gov": "primary",
    "elections.ie": "primary",
    # Science (primary)
    "nature.com": "primary",
    "science.org": "primary",
    "thelancet.com": "primary",
    "nejm.org": "primary",
    "bmj.com": "primary",
    "cell.com": "primary",
    "springer.com": "primary",
    # Companies / finance (primary — official filings)
    "sec.gov": "primary",
    "reports.fca.org.uk": "primary",
    # Fact-check organisations
    "reuters.com": "fact_check",
    "apnews.com": "fact_check",
    "politifact.com": "fact_check",
    "factcheck.org": "fact_check",
    "snopes.com": "fact_check",
    "fullfact.org": "fact_check",
    "africacheck.org": "fact_check",
    "chequeado.com": "fact_check",
    "poynter.org": "fact_check",
    # Secondary news
    "bbc.co.uk": "secondary_news",
    "bbc.com": "secondary_news",
    "theguardian.com": "secondary_news",
    "nytimes.com": "secondary_news",
    "washingtonpost.com": "secondary_news",
    "ft.com": "secondary_news",
    "bloomberg.com": "secondary_news",
    "wsj.com": "secondary_news",
    "economist.com": "secondary_news",
    "irishtimes.com": "secondary_news",
    "thejournal.ie": "secondary_news",
    "rte.ie": "secondary_news",
    "independent.ie": "secondary_news",
}

# Domains that are NEVER acceptable as evidence
EXCLUDED_DOMAINS: set[str] = {
    "twitter.com", "x.com", "facebook.com", "reddit.com",
    "youtube.com", "tiktok.com", "instagram.com",
    "wikipedia.org",  # useful for reference but not primary evidence
    "medium.com", "substack.com",
    "blogspot.com", "wordpress.com",
}

# Prefix patterns for domains that contain the registry domain
DOMAIN_PREFIXES = (
    "www.", "news.", "edition.", "api.", "data.", "open.",
)


@dataclass
class SourceQuality:
    domain: str
    tier: str  # primary, fact_check, secondary, excluded, unknown
    is_independent: bool = True


def url_host(url: str) -> str:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def classify_domain(url: str) -> SourceQuality:
    """Determine the source tier for a URL's domain.

    Checks:
      1. Exact match in TRUSTED_SOURCES
      2. Prefix variations (www.bbc.co.uk → bbc.co.uk)
      3. Subdomain match (sub.domain.gov.ie → matches gov.ie)
      4. Exclusion list
      5. Unknown → returns "unknown", which maps to excluded
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # Strip leading www. etc
    raw = hostname.lower()
    for prefix in DOMAIN_PREFIXES:
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break

    # Check exclusion list
    if raw in EXCLUDED_DOMAINS:
        return SourceQuality(domain=hostname, tier="excluded", is_independent=False)

    # Exact match
    if raw in TRUSTED_SOURCES:
        return SourceQuality(domain=hostname, tier=TRUSTED_SOURCES[raw])

    # Subdomain match — try the last two segments (gov.ie, bbc.co.uk)
    parts = raw.split(".")
    if len(parts) >= 2:
        for i in range(len(parts) - 1):
            candidate = ".".join(parts[i:])
            if candidate in TRUSTED_SOURCES:
                return SourceQuality(domain=hostname, tier=TRUSTED_SOURCES[candidate])

    # Unknown
    return SourceQuality(domain=hostname, tier="unknown")


def tier_weight(tier: str) -> float:
    """Numeric weight for sort ordering. Higher = better."""
    weights = {
        "primary": 10.0,
        "fact_check": 7.0,
        "secondary_news": 4.0,
        "unknown": 0.0,
        "excluded": -1.0,
    }
    return weights.get(tier, 0.0)


def score_source(
    domain: str,
    tier: str,
    relevance: float,
    has_date: bool,
    is_independent: bool,
) -> float:
    """Composite quality score for ordering evidence.

    Factors:
      - Tier weight (primary > fact_check > news > unknown)
      - Relevance to the claim (from text similarity)
      - Date bonus (articles with dates)
      - Independence bonus
    """
    score = tier_weight(tier) * 2.0
    score += relevance * 5.0
    if has_date:
        score += 1.0
    if is_independent:
        score += 0.5
    return score


def deduplicate_and_rank(sources: list[dict]) -> list[dict]:
    """Deduplicate by URL and rank by composite quality score.

    Returns a sorted list (best first).
    """
    seen = set()
    unique = []

    for src in sources:
        url = src.get("url", "")
        if url in seen:
            continue
        seen.add(url)

        sq = classify_domain(url)
        # Unknown/un-curated domains may be useful discovery leads, but must
        # never become evidence cards or cross the public API boundary.
        if sq.tier in {"excluded", "unknown"}:
            continue

        src["tier"] = sq.tier
        src["relevance_score"] = score_source(
            domain=sq.domain,
            tier=sq.tier,
            relevance=src.get("relevance", 0.5),
            has_date=bool(src.get("published_date")),
            is_independent=sq.is_independent,
        )
        unique.append(src)

    unique.sort(key=lambda s: s.get("relevance_score", 0), reverse=True)
    return unique