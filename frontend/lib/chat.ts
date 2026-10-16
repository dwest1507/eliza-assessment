import type { UIMessage } from 'ai'

/**
 * One numbered Source as the chat API streams it in its `data-sources` part: the
 * retrieved text of one Section of one Filing.
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

/** The data parts the chat API sends before the answer text. */
export type ResearchDataParts = {
  'query-scope': QueryScope
  sources: { sources: Source[] }
}

export type ResearchMessage = UIMessage<unknown, ResearchDataParts>

/** The text of a message: its text parts, joined. */
export function messageText(message: Pick<UIMessage, 'parts'>): string {
  return message.parts
    .filter((p): p is { type: 'text'; text: string } => p.type === 'text')
    .map((p) => p.text)
    .join('')
}

/** The Sources an answer may cite, from its `data-sources` part. */
export function messageSources(message: ResearchMessage): Source[] {
  for (const part of message.parts) {
    if (part.type === 'data-sources') return part.data.sources
  }
  return []
}

/** The Query Scope an answer was given, from its `data-query-scope` part. */
export function messageQueryScope(message: ResearchMessage): QueryScope | null {
  for (const part of message.parts) {
    if (part.type === 'data-query-scope') return part.data
  }
  return null
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
