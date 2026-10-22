'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import CompanyCalendar from '@/components/CompanyCalendar'
import {
  WHATS_COVERED_ID,
  askHref,
  matchKey,
  matchName,
  searchCompanies,
  type CompanyMatch,
} from '@/lib/coverage'
import type { CompanyCalendar as Calendar, MissingCompany } from '@/lib/evalExport'
import { askAboutCompany } from '@/lib/followUps'

/** The most other matches listed under a search's card. */
const MAX_OTHER_MATCHES = 8

/** Each coverage class in plain words, the domain term on hover. */
const COVERAGE = {
  tracked: { badge: 'Two or more years', group: 'Two or more years of quarterly filings' },
  snapshot: { badge: 'A few filings', group: 'A few filings' },
} as const

function coverageOf(calendar: Calendar): keyof typeof COVERAGE {
  return calendar.coverage === 'tracked' ? 'tracked' : 'snapshot'
}

/**
 * "What's covered": a summary line, then a search across every covered Company's name,
 * ticker and common names (the names questions are matched by) and the notable Companies
 * missing from the Corpus. The best match opens a company card (its Sector, coverage
 * badge, Company Calendar and "Ask about this company", which fills a question in the
 * workspace without sending it); a missing Company is said plainly not to be in the
 * filings. "Show all companies" lists every Company by coverage, filterable by Sector,
 * each row opening its card. The workspace's coverage line links to its anchor.
 */
export default function WhatsCovered({
  companies,
  missing,
}: {
  companies: Calendar[]
  missing: MissingCompany[]
}) {
  const [query, setQuery] = useState('')
  // A match the reader picked from a list, or null for the search's best match.
  const [picked, setPicked] = useState<CompanyMatch | null>(null)
  const [showAll, setShowAll] = useState(false)
  const matches = useMemo(
    () => searchCompanies(query, companies, missing),
    [query, companies, missing]
  )
  const shown = picked ?? matches[0] ?? null
  const resultRef = useRef<HTMLDivElement>(null)

  // A Company picked from a list below brings its card into view.
  useEffect(() => {
    if (picked) resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [picked])
  const others = matches
    .filter((m) => !shown || matchKey(m) !== matchKey(shown))
    .slice(0, MAX_OTHER_MATCHES)
  const tracked = companies.filter((c) => coverageOf(c) === 'tracked').length

  return (
    <section
      id={WHATS_COVERED_ID}
      aria-labelledby={`${WHATS_COVERED_ID}-heading`}
      className="flex scroll-mt-20 flex-col gap-4"
    >
      <div>
        <h2
          id={`${WHATS_COVERED_ID}-heading`}
          className="headline text-2xl font-semibold tracking-[-0.02em] md:text-3xl"
        >
          What’s covered
        </h2>
        <p className="mt-2 text-[15px] text-ink">
          {companies.length} companies · {tracked} with two or more years of quarterly filings ·{' '}
          {companies.length - tracked} with a few filings
        </p>
        <p className="mt-1 max-w-3xl text-[14px] leading-relaxed text-muted">
          Answers come only from these companies’ filings. Ask how something changed over time for a
          company with two or more years; one with a few filings has too few to show a trend.
        </p>
      </div>

      <div role="search" className="flex flex-col gap-3">
        <input
          type="search"
          aria-label="Search companies"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setPicked(null)
          }}
          placeholder="Search by name, ticker or common name: Google, NVDA, Coke…"
          className="h-10 w-full max-w-xl rounded-lg border border-line bg-white/[0.04] px-4 text-[14px] text-ink transition-all duration-150 outline-none placeholder:text-muted focus:border-accent/50 focus:bg-white/[0.06] focus:shadow-[0_0_0_3px_rgba(14,165,233,0.15)]"
        />
        {query.trim() && !shown && (
          <p role="status" className="text-[14px] text-muted">
            No company matches “{query.trim()}”.
          </p>
        )}
      </div>

      <div ref={resultRef} className="scroll-mt-20 empty:hidden">
        {shown?.kind === 'covered' && <CompanyCard calendar={shown.company} />}
        {shown?.kind === 'missing' && (
          <p role="status" className="card max-w-3xl p-4 text-[14px] leading-relaxed">
            <span className="font-semibold text-white">{shown.company.name}</span> isn’t in the
            filings, so questions about it can’t be answered here.
          </p>
        )}
      </div>
      {others.length > 0 && (
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[13.5px]">
          <span className="text-muted">Also matching:</span>
          <ul aria-label="Also matching" className="flex flex-wrap gap-x-3 gap-y-1">
            {others.map((match) => (
              <li key={matchKey(match)}>
                <button
                  type="button"
                  onClick={() => setPicked(match)}
                  className="text-accent-strong underline-offset-2 hover:underline"
                >
                  {matchName(match)} ({match.company.ticker})
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <button
          type="button"
          aria-expanded={showAll}
          onClick={() => setShowAll(!showAll)}
          className="btn-secondary px-4 py-1.5 text-[13.5px]"
        >
          {showAll ? 'Hide all companies' : 'Show all companies'}
        </button>
      </div>
      {showAll && (
        <AllCompanies
          companies={companies}
          onPick={(company) => setPicked({ kind: 'covered', company })}
        />
      )}
    </section>
  )
}

/** A covered Company's card: its Sector, coverage badge, "Ask about this company" and its
 * Company Calendar. */
function CompanyCard({ calendar }: { calendar: Calendar }) {
  const coverage = coverageOf(calendar)
  const id = `${WHATS_COVERED_ID}-card-${calendar.ticker}`
  return (
    <article aria-labelledby={id} className="card flex max-w-3xl flex-col gap-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id={id} className="text-[16px] leading-snug font-semibold text-white">
            {calendar.company}
            <span className="ml-2 font-mono text-[12.5px] font-normal text-muted">
              {calendar.ticker}
            </span>
          </h3>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-muted">
            {calendar.sector && <span>{calendar.sector}</span>}
            <span
              title={coverage === 'tracked' ? 'Tracked Company' : 'Snapshot Company'}
              className="cursor-help rounded-full border border-line px-2 py-0.5 text-[12px] text-ink"
            >
              {COVERAGE[coverage].badge}
            </span>
          </p>
        </div>
        <Link
          href={askHref(askAboutCompany(calendar.company))}
          className="btn-primary px-4 py-1.5 text-[13.5px]"
        >
          Ask about this company
        </Link>
      </div>
      <CompanyCalendar calendar={calendar} showName={false} />
    </article>
  )
}

/** Every covered Company, grouped by coverage and filterable by Sector, each row opening
 * its card. */
function AllCompanies({
  companies,
  onPick,
}: {
  companies: Calendar[]
  onPick: (company: Calendar) => void
}) {
  const [sector, setSector] = useState('')
  const sectors = [...new Set(companies.flatMap((c) => (c.sector ? [c.sector] : [])))].sort()
  const listed = companies
    .filter((c) => !sector || c.sector === sector)
    .sort((a, b) => a.company.localeCompare(b.company))
  return (
    <div className="flex flex-col gap-3">
      <label className="flex items-center gap-2 text-[13.5px] text-muted">
        Sector
        <select
          value={sector}
          onChange={(e) => setSector(e.target.value)}
          className="rounded-md border border-line bg-elevated px-2 py-1 text-[13.5px] text-ink"
        >
          <option value="">All sectors</option>
          {sectors.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>
      <div className="grid gap-4 md:grid-cols-2">
        {(['tracked', 'snapshot'] as const).map((coverage) => {
          const group = listed.filter((c) => coverageOf(c) === coverage)
          if (group.length === 0) return null
          const id = `${WHATS_COVERED_ID}-${coverage}`
          return (
            <div key={coverage} className="card p-4">
              <h3 id={id} className="text-[15px] font-semibold">
                <span
                  title={coverage === 'tracked' ? 'Tracked Companies' : 'Snapshot Companies'}
                  className="cursor-help"
                >
                  {COVERAGE[coverage].group}
                </span>{' '}
                <span className="font-normal text-muted">({group.length})</span>
              </h3>
              <ul
                aria-labelledby={id}
                className="mt-3 grid gap-x-4 gap-y-1 text-[14px] sm:grid-cols-2"
              >
                {group.map((c) => (
                  <li key={c.ticker}>
                    <button
                      type="button"
                      onClick={() => onPick(c)}
                      className="text-left transition-colors hover:text-accent-strong"
                    >
                      {c.company}{' '}
                      <span className="font-mono text-[12.5px] text-muted">({c.ticker})</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>
    </div>
  )
}
