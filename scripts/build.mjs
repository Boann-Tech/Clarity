#!/usr/bin/env node
import { execSync } from "node:child_process"
import { copyFileSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs"
import { relative, resolve, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, "..")
const SRC = resolve(ROOT, "src")
const DIST = resolve(ROOT, "dist")

if (existsSync(DIST)) {
  // Pure-Node removal — shelling out to `rm -rf` fails on Windows, where
  // there's no `rm` on PATH outside WSL/Git Bash.
  rmSync(DIST, { recursive: true, force: true })
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
    // path.relative handles separators correctly on every platform; the
    // previous string replace against a hardcoded "/" silently produced the
    // original absolute path on Windows (backslash-separated), which made
    // resolve(DIST, relPath) below ignore DIST entirely and copy nothing
    // into dist/ — manifest.json, icons, and panel.html included.
    const relPath = relative(SRC, srcPath)
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