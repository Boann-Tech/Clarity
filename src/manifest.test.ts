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
})
