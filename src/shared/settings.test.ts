import { describe, expect, it } from "vitest"
import {
  DEFAULT_SETTINGS,
  assessPageUrl,
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
