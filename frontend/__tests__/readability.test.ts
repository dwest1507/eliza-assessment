import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * Guards on the type and colour the stylesheet and components declare, since jsdom
 * computes no layout or Tailwind styles: secondary text has a 12px floor, and muted text
 * meets WCAG AA contrast (4.5:1) against the canvas.
 */

const ROOT = join(__dirname, '..')
const CSS = readFileSync(join(ROOT, 'app', 'globals.css'), 'utf8')

/** Every component, page and the stylesheet: wherever a font size can be declared. */
function styledFiles(): string[] {
  const files: string[] = [join(ROOT, 'app', 'globals.css')]
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name)
      if (entry.isDirectory()) walk(path)
      else if (path.endsWith('.tsx')) files.push(path)
    }
  }
  walk(join(ROOT, 'app'))
  walk(join(ROOT, 'components'))
  return files
}

function themeColour(name: string): string {
  const match = CSS.match(new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`))
  if (!match) throw new Error(`--color-${name} is not a six-digit hex colour`)
  return match[1]
}

/** WCAG 2 relative luminance of a `#rrggbb` colour. */
function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

describe('readability', () => {
  it('computes contrast as WCAG does', () => {
    // Worked examples: black on white is 21:1, and #767676 on white is the AA edge, 4.54:1.
    expect(contrast('#000000', '#ffffff')).toBeCloseTo(21, 5)
    expect(contrast('#767676', '#ffffff')).toBeCloseTo(4.54, 2)
  })

  it('gives muted text at least WCAG AA contrast against the canvas', () => {
    expect(contrast(themeColour('muted'), themeColour('canvas'))).toBeGreaterThanOrEqual(4.5)
  })

  it('never fades muted text, which would drop it below its measured contrast', () => {
    const faded = styledFiles().flatMap((file) =>
      [...readFileSync(file, 'utf8').matchAll(/\btext-muted\/\d+/g)].map(
        (m) => `${file.slice(ROOT.length + 1)}: ${m[0]}`
      )
    )
    expect(faded).toEqual([])
  })

  it('sets no text under 12px', () => {
    const small = styledFiles().flatMap((file) =>
      [...readFileSync(file, 'utf8').matchAll(/\btext-\[(\d+(?:\.\d+)?)px\]/g)]
        .filter((m) => Number(m[1]) < 12)
        .map((m) => `${file.slice(ROOT.length + 1)}: ${m[0]}`)
    )
    expect(small).toEqual([])
  })
})
