import type { QueryScope, SearchedPlace } from '@/lib/chat'

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

const WHOLE = 'Whole Filing'

/**
 * The chips for where retrieval searched: one per Section, in the order it was first
 * searched, then the Filings searched whole, each counting its Filings and naming them
 * in its title.
 */
export function searchedChips(searched: SearchedPlace[]): Chip[] {
  const filings = new Map<string, string[]>()
  for (const place of searched) {
    const name = place.section ?? WHOLE
    filings.set(name, [...(filings.get(name) ?? []), place.filingId])
  }
  const names = [...filings.keys()].filter((name) => name !== WHOLE)
  if (filings.has(WHOLE)) names.push(WHOLE)
  return names.map((name) => {
    const ids = filings.get(name) ?? []
    const count = `${ids.length} Filing${ids.length === 1 ? '' : 's'}`
    const searchedIn = name === WHOLE ? 'Searched whole' : 'Searched in'
    return { text: `${name} · ${count}`, title: `${searchedIn}: ${ids.join(', ')}` }
  })
}

const CHIP =
  'rounded-full border border-white/[0.10] px-2.5 py-0.5 font-mono text-[12px] tracking-wide text-muted'

function ChipList({ label, chips }: { label: string; chips: Chip[] }) {
  return (
    <ul aria-label={label} className="flex flex-wrap gap-1.5">
      {chips.map((chip) => (
        <li key={`${chip.title}:${chip.text}`} title={chip.title} className={CHIP}>
          {chip.text}
        </li>
      ))}
    </ul>
  )
}

/**
 * What the rules resolved from the question, and where retrieval searched for it, shown
 * at the top of its answer's "Sources" disclosure so it can be disputed.
 */
export default function QueryScopeChips({ scope }: { scope: QueryScope }) {
  const searched = searchedChips(scope.searched ?? [])
  return (
    <div className="flex flex-col gap-1.5">
      <ChipList label="Query Scope" chips={scopeChips(scope)} />
      {searched.length > 0 && <ChipList label="Searched in" chips={searched} />}
    </div>
  )
}
