import { gapWording, type CoverageGap } from '@/lib/chat'
import { plainGapLabel, plainSegments } from '@/lib/plainWords'

/**
 * The Coverage Gaps of one answer, shown as Coverage notes below it once it is complete:
 * what the Filings cannot answer, in the same wording every time (ADR 0016). The product
 * shows every gap here, so the answer leads with its finding and mentions a gap only where
 * it leaves part of the question unanswered. Neutral, not a warning: a gap informs the
 * answer rather than leading it. Each gap's label and the domain terms in its wording are
 * plain words, with the term or fixed label as hover text.
 */
export default function CoverageGaps({ gaps }: { gaps: CoverageGap[] }) {
  return (
    <aside
      role="note"
      aria-label="Coverage notes"
      className="rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[13px] text-muted"
    >
      <h3 title="Coverage Gaps" className="mb-1 text-[12px] font-semibold text-ink">
        Coverage notes
      </h3>
      <ul className="flex flex-col gap-1">
        {gaps.map((gap) => (
          <li key={gap.text} className="leading-snug">
            <strong
              title={plainGapLabel(gap) === gap.label ? undefined : gap.label}
              className="font-semibold text-ink"
            >
              {plainGapLabel(gap)}
            </strong>
            {': '}
            {plainSegments(gapWording(gap)).map((segment, i) =>
              segment.term ? (
                <span
                  key={i}
                  title={segment.term}
                  className="underline decoration-line decoration-dotted underline-offset-2"
                >
                  {segment.text}
                </span>
              ) : (
                segment.text
              )
            )}
          </li>
        ))}
      </ul>
    </aside>
  )
}
