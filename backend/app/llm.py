"""Bifrost gateway integration for Clarity's evidence pipeline.

Bifrost is Clarity's single AI egress point. It exposes deployed models
(including DeepSeek Pro) through an OpenAI-compatible endpoint.

The LLM is used as a *judge of evidence*, not a source of it.
It never generates citations. It only evaluates passages we already
retrieved from real sources.

Three roles:
1. normalize_claim — extract structured search queries from raw claim text
2. classify_passages — tag each retrieved passage supports/contradicts/context/irrelevant
3. synthesize_verdict — produce final verdict + explanation from classified passages

Every function has a deterministic fallback — if the LLM call fails,
the pipeline degrades gracefully to the rule-based system.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger("clarity.llm")

# ── Bifrost client (OpenAI-compatible) ──


def _build_client():
    """Create an OpenAI-compatible client pointing at Bifrost."""
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package not installed — LLM features disabled")
        return None

    if not settings.bifrost_api_key:
        logger.info("No Bifrost API key configured — LLM features disabled")
        return None

    return OpenAI(
        api_key=settings.bifrost_api_key,
        base_url=settings.bifrost_base_url,
    )


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    json_mode: bool = True,
) -> str | None:
    """Call the configured Bifrost-deployed model and return response text.

    Returns None on any failure (caller handles fallback).
    """
    client = _build_client()
    if client is None:
        return None

    kwargs: dict[str, Any] = {
        "model": settings.bifrost_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content
    except Exception as first_error:
        # Some Bifrost-backed deployments do not expose response_format.
        # The prompts still require JSON, so retry once without that optional
        # OpenAI feature before falling back to deterministic evaluation.
        if json_mode:
            try:
                kwargs.pop("response_format", None)
                resp = client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content
            except Exception as retry_error:
                logger.warning("Bifrost LLM call failed after JSON-mode retry: %s", retry_error)
                return None
        logger.warning("Bifrost LLM call failed: %s", first_error)
        return None


# ── Claim Normalization ──

NORMALIZE_SYSTEM_PROMPT = """You are a claim normalization assistant for an evidence-checking tool.
Your job is to take a raw claim and extract structured information for web search.

Rules:
- Identify the core factual assertion
- Extract entities (countries, organizations, people)
- Extract the metric or subject (e.g. "inflation rate", "unemployment", "GDP")
- Extract the time period
- Generate 2-3 search queries optimized for finding primary sources
- If the claim is not a factual assertion, return checkable: false
- Return ONLY valid JSON, no markdown"""


def normalize_claim(claim: str) -> dict[str, Any]:
    """Extract structured information from a raw claim for better search."""
    default = {
        "normalized_claim": claim,
        "checkable": True,
        "entities": [],
        "metric": "",
        "time_period": "",
        "search_queries": [claim],
    }

    content = _call_llm(NORMALIZE_SYSTEM_PROMPT, claim, max_tokens=512)
    if not content:
        return default

    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            return default
        # Ensure required fields
        parsed.setdefault("normalized_claim", claim)
        parsed.setdefault("checkable", True)
        parsed.setdefault("search_queries", [claim])
        return parsed
    except (json.JSONDecodeError, ValueError):
        return default


# ── Passage Classification ──

CLASSIFY_SYSTEM_PROMPT = """You are an evidence classification assistant. Your job is to evaluate
whether a retrieved passage supports, contradicts, or provides context for a given claim.

Rules:
- You may ONLY base your assessment on the passage text provided. Do not use your training data.
- "supports" = the passage directly backs the claim
- "contradicts" = the passage directly contradicts the claim
- "context" = the passage is relevant but neither clearly supports nor contradicts (adds nuance)
- "irrelevant" = the passage does not relate to the claim
- If unsure, mark as "context" — never guess
- Confidence: 0.0-1.0 reflecting how clear the relationship is
- Return ONLY valid JSON, no markdown"""


def classify_passages(
    claim: str,
    passages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Classify each passage's relationship to the claim.

    Each passage dict must have at least {"index": int, "text": str, "url": str}.
    Returns passages with added "relation", "confidence", "reasoning" fields.
    Falls back to default "context" relation if LLM unavailable.
    """
    if not passages:
        return []

    # Format for the LLM
    passages_text = "\n\n".join(
        f"--- Passage {p.get('index', i)} ---\nURL: {p.get('url', '')}\nText: {p.get('text', '')[:800]}"
        for i, p in enumerate(passages)
    )

    user_prompt = f"Claim: {claim}\n\nRetrieved passages:\n{passages_text}\n\nFor each passage, return its index, relation (supports/contradicts/context/irrelevant), confidence (0-1), and one-sentence reasoning."

    content = _call_llm(CLASSIFY_SYSTEM_PROMPT, user_prompt, max_tokens=2048)
    if not content:
        # Fallback: mark all as context
        for i, p in enumerate(passages):
            p["relation"] = "context"
            p["llm_confidence"] = 0.5
            p["reasoning"] = "LLM unavailable — defaulting to context"
        return passages

    try:
        parsed = json.loads(content)
        classifications = parsed if isinstance(parsed, list) else parsed.get("classifications", [])

        # Build lookup by index
        classification_map: dict[int, dict] = {}
        for c in classifications:
            idx = c.get("index")
            if idx is not None:
                classification_map[int(idx)] = c

        # Apply to passages
        for i, p in enumerate(passages):
            c = classification_map.get(i) or classification_map.get(p.get("index", i))
            if c:
                p["relation"] = c.get("relation", "context")
                p["llm_confidence"] = min(float(c.get("confidence", 0.5)), 1.0)
                p["reasoning"] = c.get("reasoning", "")
            else:
                p["relation"] = "context"
                p["llm_confidence"] = 0.5
                p["reasoning"] = "Not classified by LLM"
    except (json.JSONDecodeError, ValueError, TypeError):
        for p in passages:
            p["relation"] = "context"
            p["llm_confidence"] = 0.5
            p["reasoning"] = "LLM response parse failed"

    return passages


# ── Verdict Synthesis ──

VERDICT_SYSTEM_PROMPT = """You are a verdict synthesis assistant. Your job is to produce a fair,
evidence-based assessment from classified source passages.

Rules:
- Base your assessment ONLY on the classified passages provided
- Consider source quality: primary sources > fact-check orgs > secondary news
- Weight passages by their relation: supports > contradicts > context
- Verdict must be one of: supported, contradicted, misleading, unverified, not_checkable
- "misleading" means the claim omits crucial context — requires at least 2 independent sources
- "unverified" means insufficient qualifying evidence
- Confidence 0.0-1.0 reflecting evidence strength
- Explanation should cite specific passages by index
- Never invent evidence. Never use your training data as a source.
- Return ONLY valid JSON with keys: verdict, confidence, explanation, limitations (list), domain"""


def synthesize_verdict(
    claim: str,
    classified_passages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Produce a final verdict from classified passages.

    Returns dict with verdict, confidence, explanation, limitations, domain.
    Falls back to deterministic verdict if LLM unavailable.
    """
    supported = [p for p in classified_passages if p.get("relation") == "supports"]
    contradicted = [p for p in classified_passages if p.get("relation") == "contradicts"]
    context = [p for p in classified_passages if p.get("relation") == "context"]
    primary_count = sum(1 for p in classified_passages if p.get("tier") == "primary")

    if not classified_passages:
        return {
            "verdict": "unverified",
            "confidence": 0.0,
            "explanation": "No evidence passages were retrieved for this claim.",
            "limitations": ["no_sources_found"],
            "domain": None,
        }

    # Format for LLM
    passages_summary = "\n\n".join(
        f"[{p.get('index', i)}] Tier: {p.get('tier', 'unknown')} | "
        f"Relation: {p.get('relation', 'context')} | "
        f"Confidence: {p.get('llm_confidence', 0.5)}\n"
        f"URL: {p.get('url', '')}\n"
        f"Passage: {p.get('text', p.get('snippet', ''))[:600]}"
        for i, p in enumerate(classified_passages)
    )

    user_prompt = f"Claim: {claim}\n\nClassified evidence passages:\n{passages_summary}\n\nProduce a verdict assessment."

    content = _call_llm(VERDICT_SYSTEM_PROMPT, user_prompt, max_tokens=1024, temperature=0.2)
    if not content:
        return _deterministic_fallback(claim, classified_passages, supported, contradicted, primary_count)

    try:
        parsed = json.loads(content)
        required = {"verdict", "confidence", "explanation"}
        if not required.intersection(parsed.keys()):
            return _deterministic_fallback(claim, classified_passages, supported, contradicted, primary_count)

        # Clamp confidence
        parsed["confidence"] = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
        parsed.setdefault("limitations", [])
        parsed.setdefault("domain", None)

        # Evidence-first invariant: if verdict is supported/contradicted/misleading
        # but there are no qualifying sources, downgrade
        qualifying = [p for p in classified_passages if p.get("tier") in ("primary", "fact_check")]
        if parsed["verdict"] in ("supported", "contradicted") and not qualifying:
            parsed["verdict"] = "unverified"
            parsed["confidence"] = 0.0
            parsed["explanation"] = "The LLM assessment could not be validated against qualifying sources."
        if parsed["verdict"] == "misleading" and len(qualifying) < 2:
            parsed["verdict"] = "unverified"
            parsed["confidence"] = 0.0
            parsed["explanation"] = "A misleading verdict requires at least two independent qualifying sources."

        return parsed
    except (json.JSONDecodeError, ValueError, TypeError):
        return _deterministic_fallback(claim, classified_passages, supported, contradicted, primary_count)


def _deterministic_fallback(
    claim: str,
    classified_passages: list[dict[str, Any]],
    supported: list[dict[str, Any]],
    contradicted: list[dict[str, Any]],
    primary_count: int,
) -> dict[str, Any]:
    """Deterministic verdict when LLM is unavailable (same as original verdict.py logic)."""
    qualifying = [p for p in classified_passages if p.get("tier") in ("primary", "fact_check")]

    if not qualifying:
        secondary = [p for p in classified_passages if p.get("tier") == "secondary_news"]
        if secondary:
            return {
                "verdict": "unverified",
                "confidence": 0.2,
                "explanation": f"Found {len(secondary)} source(s) from secondary news, but no primary or fact-check sources. More authoritative evidence is needed.",
                "limitations": ["no_qualifying_sources"],
                "domain": None,
            }
        return {
            "verdict": "unverified",
            "confidence": 0.0,
            "explanation": "No validated citations could be retrieved for this claim.",
            "limitations": ["no_sources_found"],
            "domain": None,
        }

    n_qualifying = len(qualifying)
    base_confidence = min(0.5 + (n_qualifying * 0.08), 0.92)
    if primary_count >= 2:
        base_confidence = min(base_confidence + 0.1, 0.95)

    # Check if any qualifying source contradicts
    if contradicted and not supported:
        return {
            "verdict": "contradicted",
            "confidence": round(base_confidence, 2),
            "explanation": f"Found {len(contradicted)} source(s) that contradict this claim. The available evidence contradicts the assertion.",
            "limitations": [],
            "domain": None,
        }

    # Mixed evidence
    if supported and contradicted:
        return {
            "verdict": "misleading",
            "confidence": round(base_confidence * 0.8, 2),
            "explanation": f"Evidence is mixed: {len(supported)} source(s) support but {len(contradicted)} contradict this claim. The picture is more nuanced than stated.",
            "limitations": ["conflicting_qualifying_sources"],
            "domain": None,
        }

    return {
        "verdict": "supported",
        "confidence": round(base_confidence, 2),
        "explanation": f"Found {n_qualifying} qualifying source(s) ({primary_count} primary). The available evidence supports this claim.",
        "limitations": [],
        "domain": None,
    }