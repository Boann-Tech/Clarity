import { describe, expect, it } from "vitest"
import { assessmentFromResponse } from "../shared/protocol.js"

/**
 * The worker must preserve a citation-backed verdict returned by the backend,
 * rather than relabel every citation result as supported.
 */
describe("backend assessment mapping", () => {
  it("preserves a contradicted backend assessment with a validated citation", () => {
    const result = assessmentFromResponse({
      claim: "US inflation fell by 50% in 2024.",
      verdict: "contradicted",
      confidence: 0.95,
      explanation: "BLS CPI-U increased 2.9% year-over-year.",
      checkedAt: "2026-08-24T00:00:00Z",
      citations: [{
        title: "Consumer Price Index",
        publisher: "BLS",
        url: "https://www.bls.gov/cpi/",
        publishedDate: "2024-12-31",
        snippet: "CPI-U increased 2.9%.",
        sourceTier: "primary",
      }],
    })

    expect(result.verdict).toBe("contradicted")
    expect(result.confidence).toBe(0.95)
  })
})
