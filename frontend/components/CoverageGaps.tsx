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
      className="rounded-md border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-[13px] text-amber-950"
    >
      <h3 className="mb-1 text-[12px] font-medium tracking-wide text-amber-800 uppercase">
        Coverage Gaps
      </h3>
      <ul className="flex flex-col gap-1">
        {gaps.map((gap) => (
          <li key={gap.text} className="leading-snug">
            <strong className="font-semibold">{gap.label}</strong>
            {': '}
            {gapWording(gap)}
          </li>
        ))}
      </ul>
    </aside>
  )
}
