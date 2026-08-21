#!/usr/bin/env node
import { execSync } from "node:child_process"
import { copyFileSync, existsSync, mkdirSync, readdirSync, statSync } from "node:fs"
import { resolve, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, "..")
const SRC = resolve(ROOT, "src")
const DIST = resolve(ROOT, "dist")

if (existsSync(DIST)) {
  execSync(`rm -rf "${DIST}"`, { stdio: "pipe" })
}
mkdirSync(DIST, { recursive: true })

execSync(`npx tsc --project tsconfig.json --outDir dist`, {
  cwd: ROOT,
  stdio: "inherit",
})

function copyNonTs(dir) {
  const entries = readdirSync(dir)
  for (const entry of entries) {
    const srcPath = resolve(dir, entry)
    const relPath = srcPath.replace(SRC + "/", "")
    const distPath = resolve(DIST, relPath)
    if (statSync(srcPath).isDirectory()) {
      mkdirSync(distPath, { recursive: true })
      copyNonTs(srcPath)
    } else if (!entry.endsWith(".ts")) {
      const parent = resolve(distPath, "..")
      mkdirSync(parent, { recursive: true })
      copyFileSync(srcPath, distPath)
    }
  }
}

copyNonTs(SRC)

console.log("Build complete → dist/")