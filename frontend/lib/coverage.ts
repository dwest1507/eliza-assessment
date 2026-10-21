import type { CompanyCalendar, EvalExport, MissingCompany } from '@/lib/evalExport'

/** One covered Company, as the "What's covered" list names it. */
export interface CoveredCompany {
  ticker: string
  company: string
  /** A Tracked Company (two or more years of quarterly Filings), else a Snapshot Company. */
  tracked: boolean
}

/**
 * The Corpus coverage summary: how many Companies are covered, how many are Tracked
 * Companies, and the Companies. Built from the evaluation export's coverage grid, the
 * data "How it works" reads, so the workspace's line and that page never disagree.
 */
export interface CoverageSummary {
  companies: CoveredCompany[]
  tracked: number
}

/** The anchor of "How it works"'s "What's covered" list. */
export const WHATS_COVERED_ID = 'whats-covered'

export function coverageSummary(coverage: EvalExport['coverage']): CoverageSummary {
  const companies = coverage.companies.map((c) => ({
    ticker: c.ticker,
    company: c.company,
    tracked: c.coverage === 'tracked',
  }))
  return { companies, tracked: companies.filter((c) => c.tracked).length }
}

/** The workspace's query parameter holding a question to fill in, not send. */
export const ASK_PARAM = 'ask'

/** The workspace's address with `question` filled in, unsent. */
export function askHref(question: string): string {
  return `/?${ASK_PARAM}=${encodeURIComponent(question)}`
}

/** A Company a "What's covered" search matched: in the Corpus, or missing from it. */
export type CompanyMatch =
  { kind: 'covered'; company: CompanyCalendar } | { kind: 'missing'; company: MissingCompany }

/** A match's key, unique across both kinds. */
export function matchKey(match: CompanyMatch): string {
  return `${match.kind}:${match.company.ticker}`
}

/** A match's display name. */
export function matchName(match: CompanyMatch): string {
  return match.kind === 'covered' ? match.company.company : match.company.name
}

/** Text as the search compares it: lower case, no apostrophes or full stops, and any
 * other run of punctuation or spaces as one space, so "Coca-Cola" is "coca cola" and
 * "J.P. Morgan" is "jp morgan". */
function normalized(text: string): string {
  return text
    .toLowerCase()
    .replace(/['’‘.]/g, '')
    .replace(/[^a-z0-9&]+/g, ' ')
    .trim()
}

/**
 * How well a query matches a Company's ticker and names, lower being better, or null for
 * not at all: 0 for the ticker or a whole name, 1 for the start of a name, 2 for the
 * start of a later word of one.
 */
function rank(query: string, ticker: string, names: string[]): number | null {
  if (query === ticker.toLowerCase()) return 0
  let best: number | null = null
  for (const name of names.map(normalized)) {
    const r =
      name === query ? 0 : name.startsWith(query) ? 1 : name.includes(` ${query}`) ? 2 : null
    if (r !== null && (best === null || r < best)) best = r
  }
  return best
}

/**
 * The Companies a "What's covered" search matches, best first: covered Companies by
 * ticker, name or common name (the names questions are matched by), and missing
 * Companies by ticker, name or alias. Ties go alphabetically by name.
 */
export function searchCompanies(
  query: string,
  companies: CompanyCalendar[],
  missing: MissingCompany[]
): CompanyMatch[] {
  const q = normalized(query)
  if (!q) return []
  const candidates: [CompanyMatch, number | null][] = [
    ...companies.map((company): [CompanyMatch, number | null] => [
      { kind: 'covered', company },
      rank(q, company.ticker, [company.company, ...company.commonNames]),
    ]),
    ...missing.map((company): [CompanyMatch, number | null] => [
      { kind: 'missing', company },
      rank(q, company.ticker, [company.name, ...company.aliases]),
    ]),
  ]
  return candidates
    .filter((c): c is [CompanyMatch, number] => c[1] !== null)
    .sort((a, b) => a[1] - b[1] || matchName(a[0]).localeCompare(matchName(b[0])))
    .map(([match]) => match)
}
