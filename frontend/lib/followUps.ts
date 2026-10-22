import type { QueryScope } from '@/lib/chat'

/** The most follow-up questions shown under an answer. */
export const MAX_FOLLOW_UPS = 3

type ScopeCompany = QueryScope['companies'][number]

/** A question asked earlier in the conversation, with its answer's Query Scope if any. */
export interface AskedQuestion {
  question: string
  scope: QueryScope | null
}

/** What a template or a Query Scope asks about: a Company's risks, revenue or outlook. */
type Kind = 'risk' | 'revenue' | 'outlook'

/** A follow-up question, with the kind and the Companies (tickers) it asks about. */
interface Template {
  question: string
  kind: Kind
  tickers: string[]
}

/**
 * Up to three follow-up questions for an answer, from fixed templates over its Query
 * Scope, never from a model, so each question still makes exactly one Answer Call:
 *
 * - each Sector phrase → the group's main risks;
 * - one Company (named outside any Sector phrase) → its risks, its revenue and its outlook;
 * - several Companies → a comparison of their risks, revenue and outlook.
 *
 * A question asking how something changed is offered only for a Tracked Company, so a
 * suggestion never leads straight to a Snapshot trend's Coverage Gap. A suggestion never
 * repeats what the conversation asked: a template is dropped when its kind and Companies
 * match the Query Scope of the question just asked or of any `earlier` one (see
 * `scopeKinds`), or when its text equals one of those questions. Each question names its
 * Companies by short name and its group by the phrase the question used, so the
 * backend's Query Scope rules resolve it as they did the question.
 */
export function followUps(
  scope: QueryScope,
  question: string,
  earlier: readonly AskedQuestion[] = []
): string[] {
  const inPhrase = new Set(scope.sectorPhrases.flatMap((phrase) => phrase.tickers))
  const named = scope.companies.filter((company) => !inPhrase.has(company.ticker))
  const candidates: Template[] = [
    ...scope.sectorPhrases.map((p) => ({
      question: `What are the main risk factors for ${group(p.phrase)}?`,
      kind: 'risk' as const,
      tickers: p.tickers,
    })),
    ...(named.length === 1 ? oneCompany(named[0]) : named.length > 1 ? comparison(named) : []),
  ]
  const asked = [...earlier, { question, scope }]
  const askedTexts = new Set(asked.map((a) => normalized(a.question)))
  const askedScopes = asked.flatMap((a) => (a.scope ? [a.scope] : []))
  const shown = new Set<string>()
  return candidates
    .filter((template) => {
      if (shown.has(template.question) || askedTexts.has(normalized(template.question))) {
        return false
      }
      shown.add(template.question)
      return !askedScopes.some((s) => matches(template, s))
    })
    .map((template) => template.question)
    .slice(0, MAX_FOLLOW_UPS)
}

/**
 * The kinds a Query Scope asks about, read from what retrieval planned: Risk Factors
 * planned is a risk question, the MD&A (where the outlook route searches) an outlook
 * question, and the revenue metric a revenue question. A question planning both, as a
 * cybersecurity question plans Risk Factors and the MD&A, counts as both.
 */
function scopeKinds(scope: QueryScope): Set<Kind> {
  const kinds = new Set<Kind>()
  if (scope.sections.includes('Risk Factors')) kinds.add('risk')
  if (scope.sections.includes('MD&A')) kinds.add('outlook')
  if (scope.metric === 'revenue') kinds.add('revenue')
  return kinds
}

/** Whether a Query Scope already asked a template's kind about the same Companies. */
function matches(template: Template, scope: QueryScope): boolean {
  const tickers = new Set(scope.companies.map((company) => company.ticker))
  return (
    scopeKinds(scope).has(template.kind) &&
    tickers.size === new Set(template.tickers).size &&
    template.tickers.every((ticker) => tickers.has(ticker))
  )
}

/** The question "What's covered" fills in to ask about one Company: its main risks. */
export function askAboutCompany(name: string): string {
  return `What are ${possessive(shortName(name))} main risk factors?`
}

function oneCompany(company: ScopeCompany): Template[] {
  const owner = possessive(shortName(company.name))
  const tickers = [company.ticker]
  return [
    { question: askAboutCompany(company.name), kind: 'risk', tickers },
    {
      question:
        company.coverage === 'tracked'
          ? `How has ${owner} revenue changed over the last two years?`
          : `What was ${owner} revenue in its latest filing?`,
      kind: 'revenue',
      tickers,
    },
    {
      question: `What does ${owner} latest filing say about its outlook?`,
      kind: 'outlook',
      tickers,
    },
  ]
}

function comparison(companies: ScopeCompany[]): Template[] {
  const names = listed(companies.map((company) => shortName(company.name)))
  const among = companies.length === 2 ? 'between' : 'across'
  const tickers = companies.map((company) => company.ticker)
  return [
    { question: `How do the main risk factors of ${names} compare?`, kind: 'risk', tickers },
    {
      question: `How does revenue compare ${among} ${names} in their latest filings?`,
      kind: 'revenue',
      tickers,
    },
    {
      question: `How do ${names} describe their outlook in their latest filings?`,
      kind: 'outlook',
      tickers,
    },
  ]
}

/** A Sector phrase as a group: "energy sector" → "the energy sector". */
function group(phrase: string): string {
  const lower = phrase.trim().toLowerCase()
  return /\b(?:sector|industry|industries)$/.test(lower) && !lower.startsWith('the ')
    ? `the ${lower}`
    : lower
}

/**
 * A Company's legal suffixes, as the backend's `short_name` drops them: a copy of
 * `_SUFFIX` in `backend/src/edgar_rag/_query_scope.py`, which a test keeps in sync.
 */
export const LEGAL_SUFFIX =
  /(?:,?\s+(?:(?:&|and)\s+)?(?:Inc|Incorporated|Corp|Corporation|Company|Co|Group|Holdings|plc|Ltd)\.?)+$/i

/** A leading "The": a copy of the backend's `_THE`, kept in sync by the same test. */
export const LEADING_THE = /^The\s+/i

/**
 * A Company's name without its legal suffix, a leading "The" or a ".com", as the
 * backend's Query Scope rules also match it: "JPMorgan Chase & Co" → "JPMorgan Chase".
 */
function shortName(name: string): string {
  const short = name.trim().replace(LEGAL_SUFFIX, '').replace(LEADING_THE, '').trim()
  return short.replace(/\.com$/i, '') || name
}

function possessive(name: string): string {
  return name.endsWith('s') ? `${name}'` : `${name}'s`
}

/** Names as a list in prose: "A and B", "A, B and C". */
function listed(names: string[]): string {
  return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`
}

/** A question for comparing: lower case, plain apostrophes, single spaces, no end mark. */
function normalized(question: string): string {
  return question
    .toLowerCase()
    .replace(/[’‘]/g, "'")
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[?.!\s]+$/, '')
}
