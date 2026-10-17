import type { EvalExport } from '@/lib/evalExport'

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
