import { gapWording, type CoverageGap } from '@/lib/chat'

/**
 * The Coverage Gaps of one answer: what the Filings cannot answer, in the same wording
 * every time. Shown above the answer as well as stated in it, so they cannot be missed;
 * the answer's own closing Coverage note sits in its full analysis, so the default view
 * states each gap here. The heading is plain words, with the domain term as its hover
 * text and as the callout's accessible name.
 */
export default function CoverageGaps({ gaps }: { gaps: CoverageGap[] }) {
  return (
    <aside
      role="note"
      aria-label="Coverage Gaps"
      className="rounded-xl border border-amber-400/25 bg-amber-400/[0.07] px-3.5 py-2.5 text-[13px] text-amber-100"
    >
      <h3 title="Coverage Gaps" className="mb-1 text-[12px] font-semibold text-amber-300">
        What these Filings can’t answer
      </h3>
      <ul className="flex flex-col gap-1">
        {gaps.map((gap) => (
          <li key={gap.text} className="leading-snug">
            <strong className="font-semibold text-amber-50">{gap.label}</strong>
            {': '}
            {gapWording(gap)}
          </li>
        ))}
      </ul>
    </aside>
  )
}
