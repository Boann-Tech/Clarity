/**
 * Shared protocol types and contract functions for the evidence-first
 * claim-checking Chrome extension MVP.
 *
 * Domain-specific verdict system: a claim is never "false" or "true";
 * it is Supported / Contradicted / Misleading / Unverified / NotCheckable.
 *
 * Every verdict requires at least one valid, fetched-and-stored citation URL.
 * Without one, the verdict is downgraded to Unverified at the boundary.
 */

/* ───────── Types ───────── */

export type Verdict =
  | "supported"
  | "contradicted"
  | "misleading"
  | "unverified"
  | "not_checkable"

export type ClaimDomain =
  | "health_science"
  | "economics_finance"
  | "politics_government"
  | "historical"
  | "current_event"
  | "quote_attribution"
  | "other"

export interface Citation {
  title: string
  publisher: string
  url: string
  publishedDate: string       // ISO date
  snippet: string
  sourceTier: "primary" | "fact_check" | "secondary_news"
}

export interface ClaimCheck {
  claim: string
  checkability: "checkable" | "not_checkable"
  domain?: ClaimDomain
  verdict: Verdict
  confidence: number          // 0 – 1
  explanation: string
  citations: Citation[]
  needsHumanReview: boolean
  checkedAt: string           // ISO datetime
}

/* ───────── Raw from LLM ───────── */

export interface RawClaimResponse {
  claim: string
  verdict: string
  confidence: number
  explanation: string
  citations: Citation[]
  checkedAt: string
}

/* ───────── Page snapshot ───────── */

export interface PagePayload {
  title: string
  text: string                // visible body text
  url: string
  kind: "article" | "youtube" | "social" | "other"
  publishedDate?: string
  author?: string
}

/* ───────── Verdict contracts (evidence-before-verdict) ───────── */

function clampConfidence(n: number): number {
  return Math.max(0, Math.min(1, n))
}

/**
 * Strip checkable claims from a list of candidate sentences.
 * Opinion/value statements and pure predictions are excluded.
 */
export function selectCheckableClaims(
  candidates: string[],
  limit = 10,
): string[] {
  const seen = new Set<string>()
  const out: string[] = []

  for (const c of candidates) {
    if (out.length >= limit) break
    const trimmed = c.trim()
    if (!trimmed) continue
    if (seen.has(trimmed)) continue
    seen.add(trimmed)

    // Crude heuristic: skip sentences that are subjective/imperative
    // (will be replaced by an LLM classifier in production)
    if (/^(this|that) (policy|law|decision) (is|was) (terrible|good|bad|great)/i.test(trimmed)) {
      continue // skip opinion
    }

    out.push(trimmed)
  }

  return out
}

/**
 * Extract sentence-level candidates from a PagePayload.
 * Splits on sentence boundaries, then strips subjective/non-factual sentences.
 */
export function extractCandidates(payload: PagePayload): string[] {
  // Very rough sentence splitting for the MVP stage
  const subjectivePatterns = [
    /^(this|that|it) (is|was) (a|an|the|not|very|quite|rather|somewhat)/i,
    /^(this|that|it) (means|shows|suggests|demonstrates|indicates|seems|appears|feels|looks)/i,
    /^(i|we|you) (think|believe|feel|hope|wish|know|agree|disagree)/i,
    /^(what|why|how|when|where|who)\b/i,
    /^(please|let|imagine|consider)/i,
  ]

  const sentences = payload.text
    .replace(/\n+/g, " ")
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 20 && s.length < 400)
    .filter((s) => !subjectivePatterns.some((re) => re.test(s)))

  return sentences
}

/**
 * Validate and sanitise a raw LLM response into a domain-safe ClaimCheck.
 *
 * Safety rules:
 *   1. Supported/Contradicted/Misleading verdicts REQUIRE at least one
 *      valid Citation with a real URL. Without it → Unverified.
 *   2. Misleading requires at least 2 citations.
 *   3. Confidence is clamped to [0, 1].
 *   4. needsHumanReview is set for low-confidence or ambiguous domains.
 */
export function assessmentFromResponse(raw: RawClaimResponse): ClaimCheck {
  const citations = (raw.citations ?? []).filter(
    (c) => c.url && c.url.startsWith("http"),
  )
  const confidence = clampConfidence(raw.confidence)

  let verdict: Verdict
  let explanation: string

  if (raw.verdict === "not_checkable") {
    verdict = "not_checkable"
    explanation = "Not a checkable factual claim."
  } else if (citations.length === 0) {
    verdict = "unverified"
    explanation = "No validated citations could be retrieved for this claim."
  } else if (raw.verdict === "misleading" && citations.length < 2) {
    verdict = "unverified"
    explanation = "A misleading verdict requires at least two independent sources."
  } else {
    verdict = raw.verdict as Verdict
    if (!["supported", "contradicted", "misleading"].includes(verdict)) {
      verdict = "unverified"
      explanation = "Verdict type is not recognised without evidence backing."
    } else {
      explanation = raw.explanation || `Assessment based on ${citations.length} source(s).`
    }
  }

  // Unverified verdicts carry zero confidence — we don't know what we don't know
  const effectiveConfidence = verdict === "unverified" || verdict === "not_checkable" ? 0 : confidence

  return {
    claim: raw.claim,
    checkability: verdict === "not_checkable" ? "not_checkable" : "checkable",
    verdict,
    confidence: effectiveConfidence,
    explanation,
    citations,
    needsHumanReview: effectiveConfidence < 0.5 || verdict === "unverified",
    checkedAt: raw.checkedAt || new Date().toISOString(),
  }
}

/* ───────── Settings, URL, and host contracts (shared) ───────── */

export interface AppSettings {
  backendUrl: string
  backendToken: string
  maxClaims: number
}

export const DEFAULT_SETTINGS: AppSettings = {
  backendUrl: "http://localhost:8080",
  backendToken: "",
  maxClaims: 10,
}

export function normalizeBackendUrl(url: string): string {
  const trimmed = url.trim().replace(/\/+$/, "")
  if (!trimmed) return DEFAULT_SETTINGS.backendUrl
  return /^https?:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`
}

export function resolveSettings(stored: unknown): AppSettings {
  const value = (stored ?? {}) as Partial<AppSettings>
  const maxClaims = Number(value.maxClaims)
  return {
    backendUrl: normalizeBackendUrl(String(value.backendUrl ?? DEFAULT_SETTINGS.backendUrl)),
    backendToken: typeof value.backendToken === "string" ? value.backendToken : "",
    maxClaims: Number.isFinite(maxClaims)
      ? Math.min(Math.max(Math.round(maxClaims), 1), 20)
      : DEFAULT_SETTINGS.maxClaims,
  }
}

export function mergeHistory<T>(existing: T[], additions: T[], max: number): T[] {
  return [...additions, ...existing].slice(0, max)
}

export function isHostMatch(host: string, domain: string): boolean {
  const h = host.toLowerCase()
  const d = domain.toLowerCase()
  return h === d || h.endsWith(`.${d}`)
}

export function assessPageUrl(url: string): string | null {
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return "Clarity can only check public http(s) webpages. Open an article, video, or public post first."
    }
    return null
  } catch {
    return "Clarity could not identify this page. Open a public webpage and try again."
  }
}

export function mapTier(tier: string): Citation["sourceTier"] {
  if (tier === "primary") return "primary"
  if (tier === "fact_check") return "fact_check"
  return "secondary_news"
}

export async function testBackendConnection(url: string, token: string): Promise<boolean> {
  try {
    const headers: Record<string, string> = {}
    if (token) headers.Authorization = `Bearer ${token}`
    const response = await fetch(`${normalizeBackendUrl(url)}/api/health`, {
      headers,
      signal: AbortSignal.timeout(5000),
    })
    return response.ok
  } catch {
    return false
  }
}

/* ───────── Batch claim-check contract (extension → backend) ───────── */

export function chunkClaims(claims: string[], size = 10): string[][] {
  const chunks: string[][] = []
  for (let index = 0; index < claims.length; index += size) {
    chunks.push(claims.slice(index, index + size))
  }
  return chunks
}

export interface BatchCheckResponse {
  results: Array<{
    claim?: string
    assessment?: { verdict?: string; confidence?: number; explanation?: string }
    citations?: Array<Record<string, unknown>>
    checked_at?: string
  }>
}

/**
 * Check up to ten claims in a single backend request.
 *
 * Returns the batch results in input order, an `{ error }` marker for a
 * non-ok HTTP response, or null when the backend could not be reached.
 * A single 120 s budget covers the whole batch; callers must not fan out
 * per-claim requests.
 */
export async function fetchBatchAssessments(
  claims: string[],
  settings: AppSettings,
  fetchFn: typeof fetch = fetch,
): Promise<BatchCheckResponse | { error: string } | null> {
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (settings.backendToken) headers.Authorization = `Bearer ${settings.backendToken}`
  try {
    const response = await fetchFn(`${normalizeBackendUrl(settings.backendUrl)}/api/check/batch`, {
      method: "POST",
      headers,
      body: JSON.stringify({ claims }),
      signal: AbortSignal.timeout(120000),
    })
    if (!response.ok) return { error: `HTTP ${response.status}` }
    return await response.json() as BatchCheckResponse
  } catch {
    return null
  }
}