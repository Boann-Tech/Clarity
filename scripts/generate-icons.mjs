#!/usr/bin/env node
import { deflateSync } from "node:zlib"
import { writeFileSync } from "node:fs"

const CRC_TABLE = (() => {
  const table = new Uint32Array(256)
  for (let n = 0; n < 256; n++) {
    let c = n
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    table[n] = c >>> 0
  }
  return table
})()

function crc32(buf) {
  let c = 0xffffffff
  for (const byte of buf) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}

function chunk(type, data) {
  const length = Buffer.alloc(4)
  length.writeUInt32BE(data.length, 0)
  const typeBuf = Buffer.from(type, "ascii")
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0)
  return Buffer.concat([length, typeBuf, data, crc])
}

// Matches the landing page's .hero-icon and src/icons/icon.svg: a rounded
// square filled with the --gradient-primary blue-to-cyan diagonal, holding a
// white "C" (drawn as a ring open on the right, since this generator has no
// font rasterizer).
const GRADIENT_START = [0x3b, 0x82, 0xf6] // #3b82f6
const GRADIENT_END = [0x06, 0xb6, 0xd4] // #06b6d4
const WHITE = [0xff, 0xff, 0xff]

function mix([r1, g1, b1], [r2, g2, b2], t) {
  return [Math.round(r1 + (r2 - r1) * t), Math.round(g1 + (g2 - g1) * t), Math.round(b1 + (b2 - b1) * t)]
}

function renderPng(size) {
  const pixels = Buffer.alloc(size * size * 4)
  const center = (size - 1) / 2
  const radius = size * 0.25 // border-radius: 1.25rem on a 5rem box
  const innerMin = radius
  const innerMax = size - 1 - radius
  const outer = size * 0.35
  const inner = size * 0.21
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const cx = x < innerMin ? innerMin : x > innerMax ? innerMax : x
      const cy = y < innerMin ? innerMin : y > innerMax ? innerMax : y
      if (Math.hypot(x - cx, y - cy) > radius) continue // outside the rounded rect: leave transparent

      const offset = (y * size + x) * 4
      const gradientT = (x + y) / (2 * (size - 1))
      const background = mix(GRADIENT_START, GRADIENT_END, gradientT)

      const dx = x - center
      const dy = y - center
      const distance = Math.hypot(dx, dy)
      const angle = Math.atan2(dy, dx)
      const inRing = distance <= outer && distance >= inner
      const isGap = inRing && Math.abs(angle) < Math.PI / 5
      const [r, g, b] = inRing && !isGap ? WHITE : background
      pixels[offset] = r
      pixels[offset + 1] = g
      pixels[offset + 2] = b
      pixels[offset + 3] = 255
    }
  }
  const raw = Buffer.alloc(size * (size * 4 + 1))
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0
    pixels.copy(raw, y * (size * 4 + 1) + 1, y * size * 4, (y + 1) * size * 4)
  }
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(size, 0)
  ihdr.writeUInt32BE(size, 4)
  ihdr[8] = 8
  ihdr[9] = 6
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ])
}

for (const size of [16, 48, 128]) {
  writeFileSync(new URL(`../src/icons/icon${size}.png`, import.meta.url), renderPng(size))
}
console.log("Generated src/icons/icon{16,48,128}.png")
