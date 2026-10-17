import { useEffect, useRef } from 'react'
import Disclosure from '@/components/Disclosure'
import type { FactRow, Source } from '@/lib/chat'
import { passageBlocks, sourceHeading } from '@/lib/source'

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
 * The side panel that shows one Source of an answer: a readable line naming it, its
 * Filing metadata (Filing ID, Form Type, Report Period, Fiscal Period, Section, Item)
 * under a collapsed "Filing details" toggle, and its passage, with the passage's
 * flattened tables shown as tables, or a Facts Source's table of figures.
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
          <h3
            id={`source-heading-${source.tag}`}
            title={shortLabel(source)}
            className="text-[15px] leading-snug font-semibold text-white"
          >
            <span className="mr-2 font-mono text-[13px] text-accent-strong">{source.tag}</span>
            {sourceHeading(source)}
          </h3>
          <div className="mt-1">
            <Disclosure summary="Filing details">
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[13px]">
                {fields.map(([name, value]) => (
                  <div key={name} className="contents">
                    <dt className="font-mono text-[12px] tracking-wide text-muted">{name}</dt>
                    <dd className="font-mono text-[12.5px] break-all text-ink">{value}</dd>
                  </div>
                ))}
              </dl>
            </Disclosure>
          </div>
        </div>
        <div
          ref={passageRef}
          className="mt-4 min-h-0 flex-1 overflow-y-auto border-t border-line bg-canvas-deep/60 px-4 py-4"
        >
          {source.kind === 'facts' && source.rows ? (
            <FactsTable rows={source.rows} />
          ) : (
            <Passage text={source.text} />
          )}
        </div>
      </section>
    </aside>
  )
}

/**
 * A passage's text: its paragraphs, its flattened tables as tables (no header row, since
 * the Corpus marks none) and a visible break where the excerpt skips text.
 */
function Passage({ text }: { text: string }) {
  return (
    <div className="space-y-3 text-[13.5px] leading-relaxed text-ink">
      {passageBlocks(text).map((block, i) => {
        if (block.kind === 'elision') {
          return (
            <div
              key={i}
              role="separator"
              aria-label="Text left out"
              className="flex items-center gap-3 text-[12px] text-muted"
            >
              <span className="h-px flex-1 border-t border-dashed border-line" />
              <span aria-hidden="true">text left out</span>
              <span className="h-px flex-1 border-t border-dashed border-line" />
            </div>
          )
        }
        if (block.kind === 'table') {
          return (
            <div key={i} className="overflow-x-auto">
              <table
                aria-label="Table from the passage"
                className="border-collapse text-[12.5px] whitespace-nowrap"
              >
                <tbody>
                  {block.rows.map((row, r) => (
                    <tr key={r} className="border-b border-line last:border-b-0">
                      {row.map((cell, c) => (
                        <td
                          key={c}
                          className={`py-1 pr-3 empty:pr-0 ${c === 0 ? 'text-ink' : 'text-right font-mono text-ink'}`}
                        >
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
        return (
          <p key={i} className="break-words whitespace-pre-wrap">
            {block.text}
          </p>
        )
      })}
    </div>
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
