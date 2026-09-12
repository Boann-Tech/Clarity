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

function renderPng(size) {
  const pixels = Buffer.alloc(size * size * 4)
  const center = (size - 1) / 2
  const outer = size * 0.44
  const inner = size * 0.28
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = x - center
      const dy = y - center
      const distance = Math.hypot(dx, dy)
      const angle = Math.atan2(dy, dx)
      const inRing = distance <= outer && distance >= inner
      const isMouth = inRing && Math.abs(angle) < Math.PI / 5
      const offset = (y * size + x) * 4
      const [r, g, b] = inRing && !isMouth ? [74, 222, 128] : distance < inner ? [26, 33, 62] : [15, 52, 96]
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
