import { readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"
import manifest from "./manifest.json"

describe("extension manifest", () => {
  it("permits local backend requests and relies on activeTab for page access", () => {
    expect(manifest.permissions).toContain("activeTab")
    expect(manifest.permissions).toContain("scripting")
    expect(manifest.host_permissions).toContain("http://127.0.0.1:8080/*")
    expect(manifest.host_permissions).toContain("http://localhost:8080/*")
    expect(manifest).not.toHaveProperty("content_scripts")
  })

  it("ships raster PNG icons and a default action icon", () => {
    const sizes: Array<"16" | "48" | "128"> = ["16", "48", "128"]
    for (const size of sizes) {
      expect(manifest.icons[size]).toBe(`icons/icon${size}.png`)
      const bytes = readFileSync(new URL(`./icons/icon${size}.png`, import.meta.url))
      expect([...bytes.subarray(0, 8)]).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
    }
    expect(manifest.action.default_icon).toBe("icons/icon128.png")
    expect(manifest.minimum_chrome_version).toBe("116")
  })

  it("keeps the injected extractor import-free so tsc emits a classic script", () => {
    const source = readFileSync(new URL("./content/extractor.ts", import.meta.url), "utf8")
    expect(source).not.toMatch(/^\s*import\s/m)
    expect(source).not.toMatch(/^\s*export\s/m)
  })
})
