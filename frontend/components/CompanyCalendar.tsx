import type { CalendarPeriod, CalendarRevenue, CompanyCalendar as Calendar } from '@/lib/evalExport'

/** What a Snapshot Company's calendar says in place of its revenue column. */
export const SNAPSHOT_REVENUE_NOTE =
  'Revenue figures are extracted for companies with two or more years of filings.'

/** A revenue figure in millions of US dollars, e.g. `$57,006M`. */
export function revenueText(value: number): string {
  return `$${Math.round(value / 1_000_000).toLocaleString('en-US')}M`
}

/** What a hover on a revenue figure shows: its Filing and the label the Filing prints, or
 * how a derived figure was computed. */
function revenueSource(revenue: CalendarRevenue): string {
  return revenue.derived
    ? `Derived: ${revenue.derived}, from ${revenue.filingId} and its 10-Qs`
    : `${revenue.filingId} · ${revenue.label}`
}

/** The periods grouped by the calendar year they end in, newest first, as they come. */
function bands(periods: CalendarPeriod[]): [number, CalendarPeriod[]][] {
  const out: [number, CalendarPeriod[]][] = []
  for (const period of periods) {
    const last = out.at(-1)
    if (last && last[0] === period.calendarYear) last[1].push(period)
    else out.push([period.calendarYear, [period]])
  }
  return out
}

/**
 * A Company Calendar: one row per fiscal quarter from the Company's first Filing in the
 * Corpus to its latest, newest first, each beside its calendar months, its Filing (or
 * "not in the filings", in grey) and, for a Tracked Company, its revenue, with each
 * fiscal year's row in bold beside its fourth quarter. Rows are banded by the calendar
 * year the period ends in, so the fiscal year's alignment shows at a glance. A hover on
 * a figure names its Filing and the label it prints; a derived fourth quarter is marked
 * as derived. Shared by the workspace's Calendar tab and "What's covered".
 */
export default function CompanyCalendar({
  calendar,
  showName = true,
}: {
  calendar: Calendar
  /** False where the Company is already named above, as on a "What's covered" card. */
  showName?: boolean
}) {
  const tracked = calendar.coverage === 'tracked'
  return (
    <div className="flex flex-col gap-3">
      <div>
        {showName && (
          <h3 className="text-[15px] leading-snug font-semibold text-white">
            {calendar.company}
            <span className="ml-2 font-mono text-[12.5px] font-normal text-muted">
              {calendar.ticker}
            </span>
          </h3>
        )}
        {calendar.fiscalYearEnd && (
          <p className="mt-0.5 text-[13px] text-muted">Fiscal year ends {calendar.fiscalYearEnd}</p>
        )}
        {!tracked && <p className="mt-2 text-[13px] text-muted">{SNAPSHOT_REVENUE_NOTE}</p>}
      </div>
      <div className="overflow-x-auto">
        <table
          aria-label={`${calendar.ticker} fiscal calendar`}
          className="w-full border-collapse text-[12.5px]"
        >
          <thead>
            <tr className="border-b border-line text-left text-muted">
              <th scope="col" className="py-1 pr-3 font-medium">
                Fiscal period
              </th>
              <th scope="col" className="py-1 pr-3 font-medium">
                Calendar months
              </th>
              <th scope="col" className="py-1 pr-3 font-medium">
                Filing
              </th>
              {tracked && (
                <th scope="col" className="py-1 text-right font-medium">
                  Revenue
                </th>
              )}
            </tr>
          </thead>
          {bands(calendar.periods).map(([year, periods], i) => (
            <tbody
              key={year}
              aria-label={String(year)}
              className={i % 2 === 0 ? 'bg-white/[0.035]' : undefined}
            >
              <tr>
                <th
                  scope="rowgroup"
                  colSpan={tracked ? 4 : 3}
                  className="px-2 pt-2 pb-0.5 text-left font-mono text-[12px] font-normal tracking-widest text-muted"
                >
                  {year}
                </th>
              </tr>
              {periods.map((period) => (
                <PeriodRow key={period.fiscalPeriod} period={period} tracked={tracked} />
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </div>
  )
}

function PeriodRow({ period, tracked }: { period: CalendarPeriod; tracked: boolean }) {
  const filed = period.filing !== null
  const year = period.kind === 'year'
  return (
    <tr
      className={`border-t border-line ${filed ? 'text-ink' : 'text-muted'} ${
        year ? 'font-semibold' : ''
      }`}
    >
      <th scope="row" className="py-1 pr-3 pl-2 text-left font-[inherit] whitespace-nowrap">
        {period.fiscalPeriod}
      </th>
      <td className="py-1 pr-3 whitespace-nowrap">{period.months}</td>
      <td className="py-1 pr-3 whitespace-nowrap">
        {period.filing ? (
          <span title={period.filing.filingId}>{period.filing.formType}</span>
        ) : (
          <span className="italic">not in the filings</span>
        )}
      </td>
      {tracked && (
        <td className="py-1 pr-2 text-right font-mono whitespace-nowrap">
          {period.revenue ? (
            <>
              <span title={revenueSource(period.revenue)}>{revenueText(period.revenue.value)}</span>
              {period.revenue.derived && (
                <span className="ml-1 font-sans text-[12px] font-normal text-muted">derived</span>
              )}
            </>
          ) : (
            <span className="text-muted">—</span>
          )}
        </td>
      )}
    </tr>
  )
}
