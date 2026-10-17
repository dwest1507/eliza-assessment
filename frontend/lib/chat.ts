import type { UIMessage } from 'ai'

/** One reported row of a Facts Source, as its Filing prints it. */
export interface FactRow {
  /** `revenue`, `net_income` or `segment_revenue`. */
  metric: string
  /** e.g. "Revenue" or "Segment revenue: Compute & Networking". */
  metricName: string
  segment: string | null
  /** The length of the period the value covers: 3 or 12. */
  months: number
  reportPeriod: string
  /** In whole US dollars. */
  value: number
  /** The value in millions of dollars, e.g. "$57,006 million". */
  valueText: string
  /** The row label as the Filing prints it. */
  label: string | null
}

/**
 * One numbered Source as the chat API streams it in its `data-sources` part: the
 * retrieved text of one Section of one Filing (`kind` "text"), or the Financial Facts
 * taken from one Filing (`kind` "facts", with its `rows`).
 */
export interface Source {
  tag: string
  filingId: string
  company: string
  ticker: string
  formType: string
  reportPeriod: string
  fiscalPeriod: string | null
  section: string
  item: string | null
  label: string
  text: string
  kind?: 'text' | 'facts'
  rows?: FactRow[]
}

/** A Sector phrase in the question and the Sector table rows it resolved to. */
export interface SectorPhrase {
  phrase: string
  column: 'sector' | 'industry'
  values: string[]
  tickers: string[]
}

/**
 * What the rules resolved from the question before retrieval, as the chat API streams
 * it in its `data-query-scope` part.
 */
export interface QueryScope {
  companies: { ticker: string; name: string; coverage: string | null }[]
  sectorPhrases: SectorPhrase[]
  timeWindow: { kind: string; count: number | null; label: string }
  sections: string[]
  /** `revenue`, `net_income`, or null when the question names no metric. */
  metric: string | null
}

/**
 * A part of the question the Corpus cannot answer, as the chat API streams it in its
 * `data-coverage-gaps` part. `text` is the fixed wording the answer states, starting
 * with `label`.
 */
export interface CoverageGap {
  kind: 'snapshot_trend' | 'missing_company' | 'stale_filing' | 'no_guidance' | 'periods_differ'
  label: string
  /** Tickers, or names for Companies missing from the Corpus. */
  companies: string[]
  text: string
}

/** The data parts the chat API sends before the answer text. */
export type ResearchDataParts = {
  'query-scope': QueryScope
  sources: { sources: Source[] }
  'coverage-gaps': { gaps: CoverageGap[] }
}

export type ResearchMessage = UIMessage<unknown, ResearchDataParts>

/**
 * A message as these helpers read it. The workspace passes its `useChat` messages; the
 * chat proxy passes what the browser posted, so every helper checks the shape it reads
 * and never throws on a malformed message.
 */
export type MessageLike = Pick<ResearchMessage, 'parts'> | { parts?: unknown }

function partsOf(message: MessageLike): unknown[] {
  return Array.isArray(message.parts) ? message.parts : []
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** The text of a message: its text parts, joined. */
export function messageText(message: MessageLike): string {
  return partsOf(message)
    .map((p) => (isRecord(p) && p.type === 'text' && typeof p.text === 'string' ? p.text : ''))
    .join('')
}

/**
 * The data of a message's data part of the given type (`sources` reads the
 * `data-sources` part), or null when it has none.
 */
export function messageDataPart<K extends keyof ResearchDataParts>(
  message: MessageLike,
  type: K
): ResearchDataParts[K] | null {
  const part = partsOf(message).find((p) => isRecord(p) && p.type === `data-${type}`)
  return isRecord(part) && isRecord(part.data) ? (part.data as ResearchDataParts[K]) : null
}

/** The Sources an answer may cite, from its `data-sources` part. */
export function messageSources(message: MessageLike): Source[] {
  const sources = messageDataPart(message, 'sources')?.sources
  return Array.isArray(sources) ? sources : []
}

/** The Filing ID each Source tag of an answer cited, from its `data-sources` part. */
export function messageCitedFilings(message: MessageLike): Record<string, string> {
  const cited: Record<string, string> = {}
  for (const source of messageSources(message) as unknown[]) {
    if (isRecord(source) && typeof source.tag === 'string' && typeof source.filingId === 'string') {
      cited[source.tag] = source.filingId
    }
  }
  return cited
}

/** A gap's wording without its leading label, which the callout shows as a heading. */
export function gapWording(gap: CoverageGap): string {
  const prefix = `${gap.label}: `
  return gap.text.startsWith(prefix) ? gap.text.slice(prefix.length) : gap.text
}

/** The href a citation link carries. */
export function citationHref(tag: string): string {
  return `#source-${tag}`
}

/** The Source tag a citation href names, or null for any other link. */
export function citedTag(href: string | undefined): string | null {
  const match = href?.match(/^#source-(S\d+)$/)
  return match ? match[1] : null
}

/**
 * The answer's Markdown with every citation turned into a link: `[S3]` becomes
 * `[S3](#source-S3)`, and a grouped `[S1, S3]` becomes one link per tag.
 */
export function linkCitations(markdown: string): string {
  return markdown.replace(/\[(S\d+(?:\s*[,;]\s*S\d+)*)\](?!\()/g, (_, group: string) =>
    group
      .split(/\s*[,;]\s*/)
      .map((tag) => `[${tag}](${citationHref(tag)})`)
      .join(' ')
  )
}
