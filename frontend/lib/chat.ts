import type { ChatStatus, UIMessage } from 'ai'

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
  /**
   * Where retrieval searched, by Company and then oldest Filing first. Absent from an
   * answer saved before the chat API sent it.
   */
  searched?: SearchedPlace[]
}

/** One place retrieval searched: a Section of a Filing, or (`section` null) all of it. */
export interface SearchedPlace {
  ticker: string
  filingId: string
  section: string | null
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

/**
 * Whether an answer has finished: every answer has, except the last message while the
 * chat is waiting for or streaming its answer. A restored answer always has.
 */
export function answerComplete(
  message: { id: string },
  messages: readonly { id: string }[],
  status: ChatStatus
): boolean {
  const busy = status === 'submitted' || status === 'streaming'
  return !(busy && messages.at(-1)?.id === message.id)
}

/** A Source tag as the backend writes it: `S1`, `S2`, ... */
const SOURCE_TAG = /^S\d+$/

/**
 * The Filing ID each Source tag of an answer cited, from its `data-sources` part. The
 * browser sends these back with the history, so a tag that is not a Source tag (such as
 * `__proto__`) is skipped rather than used as a key.
 */
export function messageCitedFilings(message: MessageLike): Record<string, string> {
  return Object.fromEntries(
    (messageSources(message) as unknown[]).flatMap((source) =>
      isRecord(source) &&
      typeof source.tag === 'string' &&
      SOURCE_TAG.test(source.tag) &&
      typeof source.filingId === 'string'
        ? [[source.tag, source.filingId]]
        : []
    )
  )
}

/**
 * How many earlier messages the Answer Call's prompt keeps as history: the backend's
 * `HISTORY_TURNS` (`backend/src/edgar_rag/_prompt.py`), its one source of truth.
 * `__tests__/chat.test.ts` fails if this copy drifts from it.
 */
export const HISTORY_TURNS = 10

/** The most messages the chat API accepts: the question and the history the prompt keeps. */
export const MAX_MESSAGES = HISTORY_TURNS + 1

/**
 * The messages to send for the next answer: the latest `MAX_MESSAGES`, dropping the
 * oldest, so a long conversation keeps working. The prompt would not use the older ones.
 */
export function promptMessages<T>(messages: readonly T[]): T[] {
  return messages.slice(-MAX_MESSAGES)
}

/**
 * The chat API's reason for rejecting a request (a 4xx answer with a `detail` string),
 * from the error `useChat` reports, or null for any other failure, whose details are
 * not for the analyst.
 */
export function rejectionReason(error: unknown): string | null {
  if (!isRecord(error) || typeof error.statusCode !== 'number') return null
  if (error.statusCode < 400 || error.statusCode >= 500) return null
  if (typeof error.responseBody !== 'string') return null
  try {
    const body: unknown = JSON.parse(error.responseBody)
    return isRecord(body) && typeof body.detail === 'string' ? body.detail : null
  } catch {
    return null
  }
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

/** A citation in an answer's text: `[S3]`, or a group such as `[S1, S3]`, not yet a link. */
const CITATION = /\[(S\d+(?:\s*[,;]\s*S\d+)*)\](?!\()/g

/** The tags of one citation group: `S1, S3` gives `S1` and `S3`. */
function groupTags(group: string): string[] {
  return group.split(/\s*[,;]\s*/)
}

/**
 * The answer's Markdown with every citation turned into a link: `[S3]` becomes
 * `[S3](#source-S3)`, and a grouped `[S1, S3]` becomes one link per tag.
 */
export function linkCitations(markdown: string): string {
  return markdown.replace(CITATION, (_, group: string) =>
    groupTags(group)
      .map((tag) => `[${tag}](${citationHref(tag)})`)
      .join(' ')
  )
}

/** A Source tag's number, for putting tags in order: `S11` comes after `S2`. */
function tagNumber(tag: string): number {
  return Number(tag.slice(1))
}

/**
 * The Sources an answer's text cites, each once and in tag order. A cited tag that is
 * not among the Sources is skipped: the text shows it as unavailable instead.
 */
export function citedSources(text: string, sources: readonly Source[]): Source[] {
  const cited = new Set([...text.matchAll(CITATION)].flatMap((match) => groupTags(match[1])))
  return sources
    .filter((source) => cited.has(source.tag))
    .sort((a, b) => tagNumber(a.tag) - tagNumber(b.tag))
}

/** An answer's opening paragraph, the direct answer, and the rest of its analysis. */
export interface AnswerSplit {
  opening: string
  remainder: string
}

/** A blank line, which ends a Markdown paragraph: `\n\n`, `\r\n\r\n`, or one holding spaces. */
const BLANK_LINE = /\r?\n[ \t]*\r?\n/

/** A first block that is not a prose direct answer: a heading, a list item or a table row. */
const NOT_PROSE = /^\s*(?:#{1,6}(?:\s|$)|(?:[-*+]|\d+[.)])(?:\s|$)|\|)/

/**
 * An answer's text split at its first blank line into the opening paragraph, which the
 * prompt's fixed structure makes the direct answer, and the remainder. There is no split
 * (null) when there is no remainder yet, or when the first block is a heading, list item
 * or table row, since then it is not a prose answer and the whole text should show.
 */
export function splitAnswer(text: string): AnswerSplit | null {
  const body = text.replace(/^(?:[ \t]*\r?\n)+/, '')
  if (NOT_PROSE.test(body)) return null
  const match = BLANK_LINE.exec(body)
  if (!match) return null
  const remainder = body.slice(match.index + match[0].length).replace(/^(?:[ \t]*\r?\n)+/, '')
  if (!remainder.trim()) return null
  return { opening: body.slice(0, match.index), remainder }
}
