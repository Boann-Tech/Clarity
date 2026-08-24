import { describe, expect, it } from "vitest"

function assessPageUrl(url: string): string | null {
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

describe("page eligibility messaging", () => {
  it("rejects browser and extension pages before extraction", () => {
    expect(assessPageUrl("chrome://extensions")).toContain("public http(s) webpages")
    expect(assessPageUrl("file:///tmp/article.html")).toContain("public http(s) webpages")
  })

  it("allows normal article URLs", () => {
    expect(assessPageUrl("https://www.bbc.com/news/example")).toBeNull()
  })
})
