import {
  assessmentFromResponse,
  extractCandidates,
  selectCheckableClaims,
} from "./protocol"

describe("selectCheckableClaims", () => {
  it("keeps concrete factual claims and excludes opinions", () => {
    const claims = selectCheckableClaims([
      "Unemployment fell to 4.1% in April 2026.",
      "This policy is terrible.",
      "The government passed the Clean Air Act in 2025.",
    ])

    expect(claims).toEqual([
      "Unemployment fell to 4.1% in April 2026.",
      "The government passed the Clean Air Act in 2025.",
    ])
  })

  it("deduplicates and limits claims without changing their order", () => {
    expect(
      selectCheckableClaims([
        "Inflation was 3% in 2024.",
        "Inflation was 3% in 2024.",
        "Exports rose by 7% in 2025.",
      ], 1),
    ).toEqual(["Inflation was 3% in 2024."])
  })
})

describe("extractCandidates", () => {
  it("extracts sentence candidates from a page payload", () => {
    expect(
      extractCandidates({
        title: "Economic update",
        text: "Inflation fell to 2.3% in May 2026. This is a welcome change.",
        url: "https://news.example/article",
        kind: "article",
      }),
    ).toEqual(["Inflation fell to 2.3% in May 2026."])
  })
})

describe("assessmentFromResponse", () => {
  const validCitation = {
    title: "Consumer Price Index",
    publisher: "National Statistics Office",
    url: "https://statistics.example/cpi",
    publishedDate: "2026-06-18",
    snippet: "The annual consumer price inflation rate was 2.3% in May 2026.",
    sourceTier: "primary" as const,
  }

  it("downgrades a verdict without a fetched citation to Unverified", () => {
    const assessment = assessmentFromResponse({
      claim: "Inflation was 2.3% in May 2026.",
      verdict: "supported",
      confidence: 0.95,
      explanation: "The data confirms it.",
      citations: [],
      checkedAt: "2026-06-20T10:00:00Z",
    })

    expect(assessment.verdict).toBe("unverified")
    expect(assessment.confidence).toBe(0)
    expect(assessment.explanation).toContain("No validated citations")
  })

  it("keeps an evidence-backed verdict and clamps confidence", () => {
    const assessment = assessmentFromResponse({
      claim: "Inflation was 2.3% in May 2026.",
      verdict: "supported",
      confidence: 1.5,
      explanation: "The data confirms it.",
      citations: [validCitation],
      checkedAt: "2026-06-20T10:00:00Z",
    })

    expect(assessment.verdict).toBe("supported")
    expect(assessment.confidence).toBe(1)
    expect(assessment.citations).toHaveLength(1)
  })

  it("requires two valid citations for a misleading verdict", () => {
    const assessment = assessmentFromResponse({
      claim: "Inflation was 2.3% in May 2026.",
      verdict: "misleading",
      confidence: 0.8,
      explanation: "The timeframe changes the result.",
      citations: [validCitation],
      checkedAt: "2026-06-20T10:00:00Z",
    })

    expect(assessment.verdict).toBe("unverified")
  })
})
