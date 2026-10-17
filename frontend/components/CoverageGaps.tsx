import { gapWording, type CoverageGap } from '@/lib/chat'
import { plainGapLabel, plainSegments } from '@/lib/plainWords'

/**
 * The Coverage Gaps of one answer: what the Filings cannot answer, in the same wording
 * every time. Shown above the answer as well as stated in it, so they cannot be missed;
 * the answer's own closing Coverage note sits in its full analysis, so the default view
 * states each gap here. The heading, each gap's label and the domain terms in its wording
 * are plain words, with the term or fixed label as hover text; the callout keeps "Coverage
 * Gaps" as its accessible name.
 */
export default function CoverageGaps({ gaps }: { gaps: CoverageGap[] }) {
  return (
    <aside
      role="note"
      aria-label="Coverage Gaps"
      className="rounded-xl border border-amber-400/25 bg-amber-400/[0.07] px-3.5 py-2.5 text-[14px] text-amber-100"
    >
      <h3 title="Coverage Gaps" className="mb-1 text-[12px] font-semibold text-amber-300">
        What these filings can’t answer
      </h3>
      <ul className="flex flex-col gap-1">
        {gaps.map((gap) => (
          <li key={gap.text} className="leading-snug">
            <strong
              title={plainGapLabel(gap) === gap.label ? undefined : gap.label}
              className="font-semibold text-amber-50"
            >
              {plainGapLabel(gap)}
            </strong>
            {': '}
            {plainSegments(gapWording(gap)).map((segment, i) =>
              segment.term ? (
                <span
                  key={i}
                  title={segment.term}
                  className="underline decoration-amber-300/50 decoration-dotted underline-offset-2"
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
