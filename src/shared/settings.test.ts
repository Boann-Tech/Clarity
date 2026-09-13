import { describe, expect, it } from "vitest"
import {
  DEFAULT_SETTINGS,
  assessPageUrl,
  fetchBatchAssessments,
  isHostMatch,
  mergeHistory,
  normalizeBackendUrl,
  resolveSettings,
} from "./protocol"

describe("resolveSettings", () => {
  it("reads the unified settings key and clamps maxClaims", () => {
    const settings = resolveSettings({ backendUrl: "https://api.example.com/", backendToken: "t", maxClaims: 999 })
    expect(settings.backendUrl).toBe("https://api.example.com")
    expect(settings.backendToken).toBe("t")
    expect(settings.maxClaims).toBe(20)
    expect(resolveSettings(undefined)).toEqual(DEFAULT_SETTINGS)
  })
})

describe("normalizeBackendUrl", () => {
  it("adds a scheme and strips trailing slashes", () => {
    expect(normalizeBackendUrl("localhost:9000/")).toBe("http://localhost:9000")
    expect(normalizeBackendUrl("")).toBe(DEFAULT_SETTINGS.backendUrl)
  })
})

describe("mergeHistory", () => {
  it("prepends additions and caps the list", () => {
    expect(mergeHistory([{ id: 1 }], [{ id: 2 }, { id: 3 }], 2)).toEqual([{ id: 2 }, { id: 3 }])
  })
})

describe("isHostMatch", () => {
  it("matches exact hosts and subdomains only", () => {
    expect(isHostMatch("x.com", "x.com")).toBe(true)
    expect(isHostMatch("mobile.x.com", "x.com")).toBe(true)
    expect(isHostMatch("netflix.com", "x.com")).toBe(false)
    expect(isHostMatch("x.com.evil.example", "x.com")).toBe(false)
  })
})

describe("assessPageUrl", () => {
  it("rejects browser and extension pages", () => {
    expect(assessPageUrl("chrome://extensions")).toContain("public http(s) webpages")
    expect(assessPageUrl("https://www.bbc.com/news/example")).toBeNull()
  })
})

describe("fetchBatchAssessments", () => {
  it("posts claims to the batch route with auth and returns results", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = []
    const fakeFetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init: init ?? {} })
      return new Response(JSON.stringify({ results: [{ claim: "A" }] }), { status: 200 })
    }) as typeof fetch

    const outcome = await fetchBatchAssessments(
      ["Inflation fell to 2 percent in 2024."],
      { ...DEFAULT_SETTINGS, backendUrl: "http://localhost:8080", backendToken: "tok" },
      fakeFetch,
    )

    expect(calls).toHaveLength(1)
    expect(calls[0].url).toBe("http://localhost:8080/api/check/batch")
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ claims: ["Inflation fell to 2 percent in 2024."] })
    expect((calls[0].init.headers as Record<string, string>).Authorization).toBe("Bearer tok")
    expect(outcome).toEqual({ results: [{ claim: "A" }] })
  })

  it("maps non-ok responses to an error marker", async () => {
    const fakeFetch = (async () => new Response("nope", { status: 500 })) as typeof fetch
    expect(await fetchBatchAssessments(["A claim long enough."], DEFAULT_SETTINGS, fakeFetch)).toEqual({ error: "HTTP 500" })
  })

  it("maps network failures to null", async () => {
    const fakeFetch = (async () => { throw new Error("down") }) as typeof fetch
    expect(await fetchBatchAssessments(["A claim long enough."], DEFAULT_SETTINGS, fakeFetch)).toBeNull()
  })
})
