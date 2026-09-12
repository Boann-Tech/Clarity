"""Pydantic models for the Clarity API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SourceTier(str, Enum):
    primary = "primary"
    fact_check = "fact_check"
    secondary_news = "secondary_news"
    excluded = "excluded"


class Verdict(str, Enum):
    supported = "supported"
    contradicted = "contradicted"
    misleading = "misleading"
    unverified = "unverified"
    not_checkable = "not_checkable"


class ClaimDomain(str, Enum):
    health_science = "health_science"
    economics_finance = "economics_finance"
    politics_government = "politics_government"
    historical = "historical"
    current_event = "current_event"
    quote_attribution = "quote_attribution"
    other = "other"


# ── Request ──


class CheckRequest(BaseModel):
    claim: str = Field(..., min_length=10, max_length=500, description="The claim to check")

    @field_validator("claim")
    @classmethod
    def normalize_claim(cls, v: str) -> str:
        return " ".join(v.split())  # normalize whitespace


# ── Response pieces ──


class CitationSource(BaseModel):
    title: str = Field(..., max_length=300)
    publisher: str = Field(..., max_length=200)
    url: str = Field(..., max_length=2048)
    published_date: Optional[str] = Field(None, description="ISO date or null")
    accessed_at: str = Field(..., description="ISO datetime of retrieval")
    tier: SourceTier
    snippet: str = Field(..., max_length=800, description="Relevant passage from the source")
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieval_status: str = Field(
        default="ok",
        description="ok, fetch_error, parse_error, too_large, blocked",
    )


class Assessment(BaseModel):
    verdict: Verdict
    confidence: float = Field(..., ge=0.0, le=1.0)
    explanation: str = Field(..., max_length=600)
    domain: Optional[ClaimDomain] = None


class CheckResponse(BaseModel):
    request_id: str
    claim: str
    normalized_claim: str
    checked_at: str
    assessment: Assessment
    citations: list[CitationSource] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    policy_version: str = "3.0"