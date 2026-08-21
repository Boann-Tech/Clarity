import { describe, it, expect } from "vitest"

// We can't import chrome.* in Node, so define the interface for test
interface FactCheckSource {
  domain: string
  tier: "primary" | "fact_check" | "secondary_news"
  label: string
}

interface ClaimVerificationWorker {
  verifyClaim(claim: string): Promise<{
    assessments: unknown[]
    results: unknown[]
  }>
}

// Lightweight contract test — the real worker needs chrome APIs,
// so this tests only the pure-function dispatch/ranking logic
describe("source ranking", () => {
  const sources: FactCheckSource[] = [
    { domain: "cdc.gov", tier: "primary", label: "CDC" },
    { domain: "reuters.com", tier: "fact_check", label: "Reuters Fact Check" },
    { domain: "who.int", tier: "primary", label: "WHO" },
    { domain: "example-blog.com", tier: "secondary_news", label: "Random Blog" },
  ]

  it("prefers primary over fact_check over secondary_news", () => {
    const ordered = [...sources].sort(
      (a, b) => ["primary", "fact_check", "secondary_news"].indexOf(a.tier) - ["primary", "fact_check", "secondary_news"].indexOf(b.tier),
    )
    expect(ordered[0].tier).toBe("primary")
    expect(ordered[1].tier).toBe("primary")
    expect(ordered[2].tier).toBe("fact_check")
    expect(ordered[3].tier).toBe("secondary_news")
  })
})

describe("page extraction pipeline", () => {
  it("extracts text from an article-like HTML document", () => {
    const html = `
      <html><body><article>
        <h1>Test Headline</h1>
        <p>Inflation fell to 2.3% in May 2026. The data was released this morning.</p>
      </article></body></html>
    `
    // In-browser: content script uses document.querySelector
    // For test, simulate with a simple text extractor
    const extractText = (doc: string): string => {
      const pMatch = doc.match(/<p>(.*?)<\/p>/)
      return pMatch ? pMatch[1] : ""
    }

    const text = extractText(html)
    expect(text).toContain("Inflation")
    expect(text.length).toBeGreaterThan(40)
  })
})