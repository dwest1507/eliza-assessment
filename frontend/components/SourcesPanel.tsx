import { useEffect, useRef } from 'react'
import type { FactRow, Source } from '@/lib/chat'

interface SourcesPanelProps {
  /** The Sources of one answer. */
  sources: Source[]
  /** The tag of the Source shown. */
  selected: string
  onSelect: (tag: string) => void
  onClose: () => void
}

/** How a Source reads in a list: "TSLA 10-K FY2025, Risk Factors". */
export function shortLabel(source: Source): string {
  const period = source.fiscalPeriod ? ` ${source.fiscalPeriod}` : ''
  return `${source.ticker} ${source.formType}${period}, ${source.section}`
}

/**
 * The side panel that shows one Source of an answer: where it comes from (Filing ID,
 * Form Type, Report Period, Fiscal Period, Section, Item) and its passage text.
 */
export default function SourcesPanel({ sources, selected, onSelect, onClose }: SourcesPanelProps) {
  const source = sources.find((s) => s.tag === selected) ?? sources[0]
  const passageRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    passageRef.current?.scrollTo?.({ top: 0 })
  }, [source.tag])

  const fields: [string, string][] = [
    ['Filing ID', source.filingId],
    ['Company', source.company],
    ['Form Type', source.formType],
    ['Report Period', source.reportPeriod],
    ['Fiscal Period', source.fiscalPeriod ?? '—'],
    ['Section', source.section],
    ['Item', source.item ?? '—'],
  ]

  return (
    <aside
      aria-label="Sources"
      className="fixed inset-0 z-20 flex flex-col bg-elevated lg:static lg:z-auto lg:w-[30rem] lg:shrink-0 lg:border-l lg:border-line lg:bg-canvas/70 lg:backdrop-blur-xl"
    >
      <div className="flex shrink-0 items-center justify-between border-b border-line px-4 py-3">
        <h2 className="eyebrow text-ink">Sources</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close Sources"
          className="rounded-md p-1 text-muted transition-colors hover:bg-raised hover:text-ink"
        >
          <svg
            viewBox="0 0 24 24"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
          >
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      <nav aria-label="This answer's Sources" className="shrink-0 border-b border-line px-4 py-2">
        <ul className="flex flex-wrap gap-1">
          {sources.map((s) => (
            <li key={s.tag}>
              <button
                type="button"
                onClick={() => onSelect(s.tag)}
                aria-pressed={s.tag === source.tag}
                title={shortLabel(s)}
                className="rounded-md px-2 py-0.5 font-mono text-[12px] text-muted transition-colors hover:bg-raised hover:text-ink aria-pressed:bg-accent aria-pressed:text-on-accent"
              >
                {s.tag}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <section
        aria-labelledby={`source-heading-${source.tag}`}
        className="flex min-h-0 flex-1 flex-col"
      >
        <div className="shrink-0 px-4 pt-4">
          <h3 id={`source-heading-${source.tag}`} className="text-[14px] font-semibold text-white">
            <span className="mr-2 font-mono text-accent-strong">{source.tag}</span>
            {shortLabel(source)}
          </h3>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[13px]">
            {fields.map(([name, value]) => (
              <div key={name} className="contents">
                <dt className="font-mono text-[11px] tracking-wide text-muted/80">{name}</dt>
                <dd className="font-mono text-[12.5px] break-all text-ink">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
        <div
          ref={passageRef}
          className="mt-4 min-h-0 flex-1 overflow-y-auto border-t border-line bg-canvas-deep/60 px-4 py-4"
        >
          {source.kind === 'facts' && source.rows ? (
            <FactsTable rows={source.rows} />
          ) : (
            <p className="text-[13px] leading-relaxed break-words whitespace-pre-wrap text-ink">
              {source.text}
            </p>
          )}
        </div>
      </section>
    </aside>
  )
}

/** A Facts Source's rows: each figure the Filing reports, with the label it prints. */
function FactsTable({ rows }: { rows: FactRow[] }) {
  return (
    <table aria-label="Financial Facts" className="w-full border-collapse text-[12.5px]">
      <thead>
        <tr className="border-b border-line text-left text-muted">
          <th className="py-1 pr-3 font-medium">Metric</th>
          <th className="py-1 pr-3 font-medium">Period</th>
          <th className="py-1 pr-3 text-right font-medium">Value</th>
          <th className="py-1 font-medium">As printed</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={`${row.metric}:${row.segment ?? ''}`} className="border-b border-line">
            <td className="py-1 pr-3 text-ink">{row.metricName}</td>
            <td className="py-1 pr-3 text-muted">
              {row.months} months ended {row.reportPeriod}
            </td>
            <td className="py-1 pr-3 text-right font-mono whitespace-nowrap text-ink">
              {row.valueText}
            </td>
            <td className="py-1 text-muted">{row.label ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
