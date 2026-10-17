import type { QueryScope } from '@/lib/chat'

interface Chip {
  text: string
  title: string
}

/**
 * The chips for one answer's Query Scope, in reading order: each Sector phrase with the
 * Companies it resolved to, then the other Companies, the time window, the Section hints
 * and the metric. A Company a Sector phrase covers is shown in that phrase's chip only.
 */
export function scopeChips(scope: QueryScope): Chip[] {
  const chips: Chip[] = []
  const inPhrase = new Set<string>()
  for (const phrase of scope.sectorPhrases) {
    phrase.tickers.forEach((ticker) => inPhrase.add(ticker))
    chips.push({
      text: `“${phrase.phrase}” → ${phrase.tickers.join(', ') || 'no Company'}`,
      title: `Sector phrase resolved through the Sector table (${phrase.column}: ${phrase.values.join(', ')})`,
    })
  }
  for (const company of scope.companies) {
    if (inPhrase.has(company.ticker)) continue
    const coverage = company.coverage ? ` (${company.coverage})` : ''
    chips.push({ text: company.ticker, title: `Company: ${company.name}${coverage}` })
  }
  chips.push({ text: scope.timeWindow.label, title: 'Time window' })
  for (const section of scope.sections) {
    chips.push({ text: section, title: 'Section hint' })
  }
  if (scope.metric) {
    chips.push({ text: scope.metric.replaceAll('_', ' '), title: 'Metric' })
  }
  return chips
}

/**
 * What the rules resolved from the question, shown under its answer's "How this was
 * answered" so it can be disputed.
 */
export default function QueryScopeChips({ scope }: { scope: QueryScope }) {
  return (
    <ul aria-label="Query Scope" className="flex flex-wrap gap-1.5">
      {scopeChips(scope).map((chip) => (
        <li
          key={`${chip.title}:${chip.text}`}
          title={chip.title}
          className="rounded-full border border-white/[0.10] px-2.5 py-0.5 font-mono text-[11px] tracking-wide text-muted"
        >
          {chip.text}
        </li>
      ))}
    </ul>
  )
}
