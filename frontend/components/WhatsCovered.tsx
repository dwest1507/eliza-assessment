import { WHATS_COVERED_ID, type CoverageSummary, type CoveredCompany } from '@/lib/coverage'

/**
 * "What's covered": every Company in the Corpus, grouped in plain words into those with
 * two or more years of history (Tracked Companies) and those with only a few Filings
 * (Snapshot Companies), the domain terms on hover. The workspace's coverage line links
 * to its anchor.
 */
export default function WhatsCovered({ summary }: { summary: CoverageSummary }) {
  const tracked = summary.companies.filter((c) => c.tracked)
  const snapshot = summary.companies.filter((c) => !c.tracked)
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
        <p className="mt-2 max-w-3xl text-[14px] leading-relaxed text-muted">
          Answers come only from the filings of these {summary.companies.length} companies. Ask how
          something changed over time for the first group; the second has too few filings to show a
          trend.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <CompanyGroup
          id={`${WHATS_COVERED_ID}-tracked`}
          title="Two or more years of history"
          term="Tracked Companies"
          companies={tracked}
        />
        <CompanyGroup
          id={`${WHATS_COVERED_ID}-snapshot`}
          title="Only a few filings"
          term="Snapshot Companies"
          companies={snapshot}
        />
      </div>
    </section>
  )
}

function CompanyGroup({
  id,
  title,
  term,
  companies,
}: {
  id: string
  title: string
  term: string
  companies: CoveredCompany[]
}) {
  return (
    <div className="card p-4">
      <h3 id={id} className="text-[15px] font-semibold">
        <span title={term} className="cursor-help">
          {title}
        </span>{' '}
        <span className="font-normal text-muted">({companies.length})</span>
      </h3>
      <ul aria-labelledby={id} className="mt-3 grid gap-x-4 gap-y-1 text-[14px] sm:grid-cols-2">
        {companies.map((c) => (
          <li key={c.ticker}>
            {c.company} <span className="font-mono text-[12.5px] text-muted">({c.ticker})</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
