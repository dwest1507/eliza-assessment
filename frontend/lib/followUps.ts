import type { QueryScope } from '@/lib/chat'

/** The most follow-up questions shown under an answer. */
export const MAX_FOLLOW_UPS = 3

type ScopeCompany = QueryScope['companies'][number]

/**
 * Up to three follow-up questions for an answer, from fixed templates over its Query
 * Scope, never from a model, so each question still makes exactly one Answer Call:
 *
 * - each Sector phrase → the group's main risks;
 * - one Company (named outside any Sector phrase) → its risks, its revenue and its outlook;
 * - several Companies → a comparison of their risks, revenue and outlook.
 *
 * A question asking how something changed is offered only for a Tracked Company, so a
 * suggestion never leads straight to a Snapshot trend's Coverage Gap. A suggestion equal
 * to the question just asked is dropped. Each question names its Companies by short
 * name and its group by the phrase the question used, so the backend's Query Scope rules
 * resolve it as they did the question.
 */
export function followUps(scope: QueryScope, question: string): string[] {
  const inPhrase = new Set(scope.sectorPhrases.flatMap((phrase) => phrase.tickers))
  const named = scope.companies.filter((company) => !inPhrase.has(company.ticker))
  const candidates = [
    ...scope.sectorPhrases.map((p) => `What are the main risk factors for ${group(p.phrase)}?`),
    ...(named.length === 1 ? oneCompany(named[0]) : named.length > 1 ? comparison(named) : []),
  ]
  const asked = normalized(question)
  return [...new Set(candidates)]
    .filter((candidate) => normalized(candidate) !== asked)
    .slice(0, MAX_FOLLOW_UPS)
}

/** The question "What's covered" fills in to ask about one Company: its main risks. */
export function askAboutCompany(name: string): string {
  return `What are ${possessive(shortName(name))} main risk factors?`
}

function oneCompany(company: ScopeCompany): string[] {
  const owner = possessive(shortName(company.name))
  return [
    askAboutCompany(company.name),
    company.coverage === 'tracked'
      ? `How has ${owner} revenue changed over the last two years?`
      : `What was ${owner} revenue in its latest filing?`,
    `What does ${owner} latest filing say about its outlook?`,
  ]
}

function comparison(companies: ScopeCompany[]): string[] {
  const names = listed(companies.map((company) => shortName(company.name)))
  const among = companies.length === 2 ? 'between' : 'across'
  return [
    `How do the main risk factors of ${names} compare?`,
    `How does revenue compare ${among} ${names} in their latest filings?`,
    `How do ${names} describe their outlook in their latest filings?`,
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
