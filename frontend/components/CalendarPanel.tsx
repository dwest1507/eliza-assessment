import CompanyCalendar from '@/components/CompanyCalendar'
import type { CompanyCalendar as Calendar } from '@/lib/evalExport'

interface CalendarPanelProps {
  /** The tickers of every Company the conversation's Query Scopes named, alphabetical. */
  tickers: string[]
  /** Each Company's Company Calendar, from the evaluation export. */
  calendars: ReadonlyMap<string, Calendar>
  /** The ticker shown. */
  selected: string | null
  onSelect: (ticker: string) => void
}

/**
 * The side panel's Calendar tab: a strip of ticker tabs, one per Company the
 * conversation's Query Scopes named (never one only retrieved as a Source), in
 * alphabetical order and styled like the Source tabs, then the selected Company's
 * Company Calendar.
 */
export default function CalendarPanel({
  tickers,
  calendars,
  selected,
  onSelect,
}: CalendarPanelProps) {
  const shown = selected && tickers.includes(selected) ? selected : tickers[0]
  if (!shown) {
    return (
      <p className="px-4 py-6 text-[13.5px] leading-relaxed text-muted">
        No companies yet. Ask about a company, and how its fiscal quarters line up with the calendar
        shows here.
      </p>
    )
  }
  const calendar = calendars.get(shown)
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <nav aria-label="Companies asked about" className="shrink-0 border-b border-line px-4 py-2">
        <ul className="flex flex-wrap gap-1">
          {tickers.map((ticker) => (
            <li key={ticker}>
              <button
                type="button"
                onClick={() => onSelect(ticker)}
                aria-pressed={ticker === shown}
                title={calendars.get(ticker)?.company ?? ticker}
                className="rounded-md px-2 py-0.5 font-mono text-[12px] font-medium text-accent-strong transition-colors hover:bg-raised hover:text-ink aria-pressed:bg-accent aria-pressed:text-on-accent"
              >
                {ticker}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {calendar ? (
          <CompanyCalendar calendar={calendar} />
        ) : (
          <p className="text-[13.5px] text-muted">No calendar for {shown}.</p>
        )}
      </div>
    </div>
  )
}
