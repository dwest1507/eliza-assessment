import { gapWording, type CoverageGap } from '@/lib/chat'

/**
 * The Coverage Gaps of one answer: what the Filings cannot answer, in the same wording
 * every time. Shown beside the answer as well as stated in it, so they cannot be missed.
 */
export default function CoverageGaps({ gaps }: { gaps: CoverageGap[] }) {
  return (
    <aside
      role="note"
      aria-label="Coverage Gaps"
      className="rounded-xl border border-amber-400/25 bg-amber-400/[0.07] px-3.5 py-2.5 text-[13px] text-amber-100"
    >
      <h3 className="mb-1 font-mono text-[10.5px] tracking-widest text-amber-300 uppercase">
        Coverage Gaps
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
