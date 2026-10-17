import type { CoverageGap } from '@/lib/chat'

/**
 * Plain words for the domain terms (`CONTEXT.md`) that reach the default view. The terms
 * keep their meaning in code, tests, docs and the technical layer; the default view shows
 * the plain words and keeps the term as hover text, so technical readers can still match
 * the UI to the docs.
 */

/** A run of text: plain words, or the plain words standing for a domain term. */
export interface Segment {
  text: string
  /** The domain term the text stands for, shown on hover. */
  term?: string
}

/** Each domain term the backend's fixed wording may use, and the plain words for it. */
const TERMS: Record<string, string> = {
  'Snapshot Company': 'company with only a few filings',
  'Tracked Company': 'company with two or more years of filings',
  Corpus: 'collection',
  Filings: 'filings',
  Filing: 'filing',
}

const ANY_TERM = new RegExp(`\\b(?:${Object.keys(TERMS).join('|')})\\b`, 'g')

/** The text split into segments, each domain term replaced by its plain words. */
export function plainSegments(text: string): Segment[] {
  const segments: Segment[] = []
  let last = 0
  for (const match of text.matchAll(ANY_TERM)) {
    if (match.index > last) segments.push({ text: text.slice(last, match.index) })
    segments.push({ text: TERMS[match[0]], term: match[0] })
    last = match.index + match[0].length
  }
  if (last < text.length) segments.push({ text: text.slice(last) })
  return segments
}

/** Plain labels for the Coverage Gap kinds whose fixed label uses a domain term. */
const GAP_LABELS: Partial<Record<CoverageGap['kind'], string>> = {
  missing_company: 'Not covered',
  stale_filing: 'Out-of-date filing',
  no_guidance: 'No company guidance',
}

/** A gap's label in plain words; its fixed label (what the answer states) when plain already. */
export function plainGapLabel(gap: CoverageGap): string {
  return GAP_LABELS[gap.kind] ?? gap.label
}
