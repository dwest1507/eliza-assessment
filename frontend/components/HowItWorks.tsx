import Link from 'next/link'
import type { ReactNode } from 'react'
import {
  type CoverageCompany,
  type EvalExport,
  type GenerationRun,
  type GenerationSummary,
  type GeneratorChoice,
  type HoldoutResults,
  type RetrievalResults,
  type RetrievalSummary,
  type SignTest,
  quarterLabel,
  questionType,
  score,
  seconds,
  usd,
} from '@/lib/evalExport'

/**
 * The "How it works" page: the architecture, the evaluation scoreboard (with the generator
 * comparison), the holdout run and the Corpus coverage grid, all read from the evaluation
 * export so the evidence sits in the product.
 */
export default function HowItWorks({ data }: { data: EvalExport }) {
  return (
    <div className="min-h-dvh text-ink">
      <header className="sticky top-0 z-30 flex items-center gap-4 border-b border-line bg-canvas/80 px-5 py-3 backdrop-blur-xl">
        <h1 className="text-[15px] font-semibold tracking-tight">
          How it works<span className="text-accent">.</span>
        </h1>
        <p className="hidden font-mono text-[11px] tracking-widest text-muted lg:block">
          The architecture, the evaluation scores and the Filings behind every answer
        </p>
        <Link
          href="/"
          className="ml-auto text-[13px] text-muted transition-colors duration-200 hover:text-ink"
        >
          ← Back to the workspace
        </Link>
      </header>

      <main className="mx-auto flex max-w-5xl flex-col gap-20 px-5 py-14">
        <Architecture data={data} />
        <Scoreboard data={data} />
        {data.holdout && <Holdout holdout={data.holdout} />}
        <CoverageGrid data={data} />
      </main>
    </div>
  )
}

function Section({
  id,
  title,
  intro,
  children,
}: {
  id: string
  title: string
  intro: ReactNode
  children: ReactNode
}) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-4">
      <div>
        <div className="mb-3 flex items-center gap-3">
          <span className="h-px w-10 bg-accent/50" aria-hidden="true" />
          <span className="font-mono text-[11px] tracking-widest text-accent">{id}</span>
        </div>
        <h2 id={id} className="headline text-2xl font-semibold tracking-[-0.02em] md:text-3xl">
          {title}
        </h2>
        <p className="mt-2 max-w-3xl text-[14px] leading-relaxed text-muted">{intro}</p>
      </div>
      {children}
    </section>
  )
}

// --- Architecture -----------------------------------------------------------------------

interface Stage {
  name: string
  text: ReactNode
}

function Architecture({ data }: { data: EvalExport }) {
  const shipped = data.retrieval.arms.find((arm) => arm.shipped)?.name
  const generator =
    data.generation.find((run) => run.model === data.generatorChoice?.chosen) ?? data.generation[0]
  const filings = data.coverage.companies.reduce((n, c) => n + c.filings.length, 0)

  const builtOnce: Stage[] = [
    {
      name: 'Corpus',
      text: `${filings} cleaned 10-K and 10-Q Filings of ${data.coverage.companies.length} Companies, split into Sections at their Item headings.`,
    },
    {
      name: 'Index',
      text: 'Chunks that never cross a Section, tagged with Filing metadata, in one SQLite file: an FTS5 table beside the Financial Facts store.',
    },
  ]
  const perQuestion: Stage[] = [
    {
      name: 'Query Scope',
      text: 'Rules, no LLM: Companies by name or ticker, Sector phrases through the curated Sector table, time windows anchored on each Company’s latest Filing, Section hints and metric words. A follow-up inherits what it does not name.',
    },
    {
      name: 'Retrieval',
      text: (
        <>
          <code className="font-mono text-[12.5px]">bm25()</code> search inside hard filters on
          Company and period, each Company with its own share of the context budget. Risk and change
          questions are routed; repeated text is dropped.
          {shipped && (
            <>
              {' '}
              Shipped Arm: <code className="font-mono text-[12.5px]">{shipped}</code>.
            </>
          )}
        </>
      ),
    },
    {
      name: 'Answer Context',
      text: 'Numbered Sources [S1]…[Sn], the Financial Facts table and the Coverage Gaps, computed by code in fixed wordings, rendered into one fixed prompt template.',
    },
    {
      name: 'Answer Call',
      text: generator ? (
        <>
          The one generative LLM request per message:{' '}
          <code className="font-mono text-[12.5px]">{generator.model}</code>, prompt{' '}
          {generator.promptVersion}. The Query Scope and Sources stream first, so citations are
          clickable while the answer arrives.
        </>
      ) : (
        'The one generative LLM request per message, streamed. The Query Scope and Sources stream first, so citations are clickable while the answer arrives.'
      ),
    },
  ]
  const measured: Stage[] = [
    {
      name: 'Golden Set',
      text: `${data.goldenSet.cases} labelled questions (version ${data.goldenSet.version}) with expected Sources, Required Facts and Coverage Gaps, split into dev and holdout by a hash rule.`,
    },
    {
      name: 'Harnesses',
      text: 'Retrieval: hit@k, recall@k and MRR, with no LLM call. Generation: citation, figure and Coverage Gap checks in code, Fact Recall and Faithfulness judged by a pinned Jev version, cost and latency.',
    },
  ]

  return (
    <Section
      id="architecture"
      title="Architecture"
      intro="Each question gets exactly one generative LLM request, the Answer Call. Everything before it is deterministic: the same conversation always gets the same Sources and the same Coverage Gaps, so every claim can be traced and every stage measured."
    >
      <Lane label="Built once, from the Corpus" stages={builtOnce} />
      <Lane label="For every question" stages={perQuestion} emphasis />
      <Lane label="Measured on the Golden Set" stages={measured} />
    </Section>
  )
}

function Lane({
  label,
  stages,
  emphasis = false,
}: {
  label: string
  stages: Stage[]
  emphasis?: boolean
}) {
  return (
    <div>
      <h3 className="eyebrow mb-2">{label}</h3>
      <ol className="flex flex-col gap-2 md:flex-row md:items-stretch">
        {stages.map((stage, i) => (
          <li key={stage.name} className="flex flex-1 flex-col gap-2 md:flex-row md:items-center">
            {i > 0 && (
              <span aria-hidden="true" className="self-center text-muted md:px-0.5">
                <span className="md:hidden">↓</span>
                <span className="hidden md:inline">→</span>
              </span>
            )}
            <div
              className={`card h-full flex-1 px-3.5 py-3 ${
                emphasis
                  ? 'border-accent/30 shadow-[0_0_0_1px_rgba(14,165,233,0.12),0_8px_40px_rgba(0,0,0,0.4),0_0_60px_rgba(14,165,233,0.08)]'
                  : ''
              }`}
            >
              <h4 className="text-[14px] font-semibold text-white">{stage.name}</h4>
              <p className="mt-1 text-[13px] leading-relaxed text-muted">{stage.text}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

// --- Evaluation scoreboard ----------------------------------------------------------------

const th =
  'border-b border-line bg-raised px-3 py-1.5 text-left font-mono text-[11px] font-medium tracking-wide whitespace-nowrap text-muted'
const td = 'border-b border-line px-3 py-1.5 whitespace-nowrap tabular-nums'
const caption = 'mb-3 text-left text-[14px] font-semibold text-white'

function Scoreboard({ data }: { data: EvalExport }) {
  const { retrieval, split, goldenSet } = data
  return (
    <Section
      id="scoreboard"
      title="Evaluation scoreboard"
      intro={
        <>
          The harnesses’ latest results on the Golden Set’s {split} split, exported on{' '}
          {data.exportedOn}. Choices are tuned on dev; the holdout is scored once per final setup,
          never to choose{data.holdout ? ', and its run follows' : ''}. Scores are shares from 0 to
          1.
        </>
      }
    >
      <RetrievalTable retrieval={retrieval} split={split} splitCases={goldenSet.splitCases} />
      {data.generation.length > 0 ? (
        <GenerationTable
          runs={data.generation}
          split={split}
          shipped={data.generatorChoice?.chosen}
        />
      ) : (
        <p className="card px-4 py-3 text-[14px] text-muted">
          No answers have been scored on this split yet. Run{' '}
          <code className="font-mono text-[13px]">make eval-generation</code> (it calls the
          generator and the judge, so it costs money), then{' '}
          <code className="font-mono text-[13px]">make eval-export</code>.
        </p>
      )}
      {data.generatorChoice && <GeneratorChoiceTable choice={data.generatorChoice} />}
    </Section>
  )
}

function Holdout({ holdout }: { holdout: HoldoutResults }) {
  const { splitCases } = holdout
  return (
    <Section
      id="holdout"
      title="The holdout run"
      intro={
        <>
          The shipped setup, scored on the Golden Set’s {splitCases} holdout cases after every
          choice above was made on dev. The holdout is scored once per final setup and never used to
          choose: nothing was changed after it. On {splitCases} cases one case moves a share by{' '}
          {(1 / splitCases).toFixed(2)}, so it shows whether the dev choices overfitted badly, not
          that one split scores better than the other.
        </>
      }
    >
      {holdout.retrieval && (
        <RetrievalTable retrieval={holdout.retrieval} split="holdout" splitCases={splitCases} />
      )}
      {holdout.generation.length > 0 && (
        <GenerationTable runs={holdout.generation} split="holdout" />
      )}
    </Section>
  )
}

function RetrievalTable({
  retrieval,
  split,
  splitCases,
}: {
  retrieval: RetrievalResults
  split: string
  splitCases: number
}) {
  const verdicts = new Map(retrieval.comparisons.map((c) => [c.arm, c]))
  const shipped = retrieval.arms.find((arm) => arm.shipped)
  return (
    <div className="flex flex-col gap-3">
      <div className="card overflow-x-auto p-3">
        <table className="min-w-full border-collapse text-[13px]">
          <caption className={caption}>
            Retrieval: do the right Sections reach the Answer Call?
          </caption>
          <thead>
            <RetrievalHeader retrieval={retrieval} first="Arm" extra="Against the Shipped Arm" />
          </thead>
          <tbody>
            {retrieval.arms.map((arm) => {
              const c = verdicts.get(arm.name)
              return (
                <tr key={arm.name}>
                  <th scope="row" className={`${td} text-left font-medium`}>
                    <code className="font-mono">{arm.name}</code>
                    {arm.shipped && (
                      <span className="ml-2 rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 font-mono text-[10px] tracking-widest text-accent-strong">
                        shipped
                      </span>
                    )}
                  </th>
                  <RetrievalCells summary={arm.overall} retrieval={retrieval} />
                  <td className={td}>
                    {c
                      ? `${c.verdict} (${c.challengerOnly} won, ${c.shippedOnly} lost, p = ${c.pValue.toFixed(2)})`
                      : '–'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
          Scored on {retrieval.scoredCases} of {splitCases} {split} cases
          {retrieval.unscored.length > 0 &&
            `; ${retrieval.unscored.length} have no expected Source to find (a Company missing from the Corpus, General Electric today)`}
          . Gating metric {retrieval.gatingMetric}
          {retrieval.comparisons.length > 0 &&
            ': each challenger is compared with the Shipped Arm case by case by McNemar’s exact test, and called ahead or behind only at p < 0.05'}
          .
          {shipped && shipped.missed.length > 0 && (
            <>
              {' '}
              Missed by {shipped.name} at {retrieval.gatingMetric}: {shipped.missed.join(', ')}.
            </>
          )}
        </p>
      </div>
      {shipped && shipped.byType.length > 0 && (
        <details className="card p-3">
          <summary className="cursor-pointer text-[13px] font-medium">
            {shipped.name} by question type
          </summary>
          <div className="mt-2 overflow-x-auto">
            <table className="min-w-full border-collapse text-[13px]">
              <caption className="sr-only">{shipped.name} by question type</caption>
              <thead>
                <RetrievalHeader retrieval={retrieval} first="Question type" />
              </thead>
              <tbody>
                {shipped.byType.map((row) => (
                  <tr key={row.questionType}>
                    <th scope="row" className={`${td} text-left font-medium`}>
                      {questionType(row.questionType)}
                    </th>
                    <RetrievalCells summary={row} retrieval={retrieval} />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  )
}

function RetrievalHeader({
  retrieval,
  first,
  extra,
}: {
  retrieval: RetrievalResults
  first: string
  extra?: string
}) {
  return (
    <tr>
      <th className={th}>{first}</th>
      <th className={th}>Cases</th>
      {retrieval.ks.map((k) => (
        <th key={`hit${k}`} className={th}>
          hit@{k}
        </th>
      ))}
      <th className={th}>recall@{retrieval.gatingMetric.split('@')[1]}</th>
      <th className={th}>recall@all</th>
      <th className={th}>MRR</th>
      <th className={th}>Sources</th>
      {extra && <th className={th}>{extra}</th>}
    </tr>
  )
}

function RetrievalCells({
  summary,
  retrieval,
}: {
  summary: RetrievalSummary
  retrieval: RetrievalResults
}) {
  const gate = retrieval.gatingMetric.split('@')[1]
  return (
    <>
      <td className={td}>{summary.cases}</td>
      {retrieval.ks.map((k) => (
        <td key={k} className={`${td} ${String(k) === gate ? 'font-semibold' : ''}`}>
          {score(summary.hitAt[String(k)] ?? null)}
        </td>
      ))}
      <td className={td}>{score(summary.recallAt[gate] ?? null)}</td>
      <td className={td}>{score(summary.recallAll)}</td>
      <td className={td}>{score(summary.mrr)}</td>
      <td className={td}>{summary.meanSources.toFixed(1)}</td>
    </>
  )
}

const GENERATION_COLUMNS: [string, (s: GenerationSummary) => string][] = [
  ['Cases', (s) => String(s.cases)],
  ['Citations valid', (s) => score(s.citationsValid)],
  ['Figures exact', (s) => score(s.figuresExact)],
  ['Gaps stated', (s) => score(s.coverageGapsStated)],
  ['Fact Recall', (s) => score(s.factRecall)],
  ['Faithfulness', (s) => score(s.faithfulness)],
  ['$ per answer', (s) => usd(s.meanCostUsd)],
  ['Latency', (s) => seconds(s.meanLatencyS)],
  ['First text', (s) => seconds(s.meanFirstTokenS)],
]

function GenerationTable({
  runs,
  split,
  shipped,
}: {
  runs: GenerationRun[]
  split: string
  /** The generator the rule chose, marked on its row. */
  shipped?: string
}) {
  const judges = [...new Set(runs.map((run) => run.judgeModel))].join(', ')
  // Name the report when two runs share a generator, e.g. two holdout runs.
  const repeated = (run: GenerationRun) => runs.filter((r) => r.model === run.model).length > 1
  return (
    <div className="flex flex-col gap-3">
      <div className="card overflow-x-auto p-3">
        <table className="min-w-full border-collapse text-[13px]">
          <caption className={caption}>Answers: are they right, and what do they cost?</caption>
          <thead>
            <tr>
              <th className={th}>Generator</th>
              {GENERATION_COLUMNS.map(([name]) => (
                <th key={name} className={th}>
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.report}>
                <th scope="row" className={`${td} text-left font-medium`}>
                  <code className="font-mono">{run.model}</code>
                  {run.model === shipped && (
                    <span className="ml-2 rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 font-mono text-[10px] tracking-widest text-accent-strong">
                      shipped
                    </span>
                  )}
                  <span className="ml-2 text-[11.5px] text-muted">prompt {run.promptVersion}</span>
                  {repeated(run) && (
                    <span className="ml-2 font-mono text-[11.5px] text-muted">{run.report}</span>
                  )}
                </th>
                {GENERATION_COLUMNS.map(([name, value]) => (
                  <td key={name} className={td}>
                    {value(run.overall)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
          One real Answer Call per {split} case. Citations, figures and Coverage Gaps are checked in
          code; Fact Recall and Faithfulness are judged by {judges}, pinned to an exact version and
          from neither generator’s family. Cost is the list price of the tokens used, an upper
          bound. A dash means there was nothing to score.
        </p>
      </div>
      {runs.map(
        (run) =>
          run.byType.length > 0 && (
            <details key={run.report} className="card p-3">
              <summary className="cursor-pointer text-[13px] font-medium">
                {run.model} by question type{repeated(run) && ` (${run.report})`}
              </summary>
              <div className="mt-2 overflow-x-auto">
                <table className="min-w-full border-collapse text-[13px]">
                  <caption className="sr-only">{run.model} by question type</caption>
                  <thead>
                    <tr>
                      <th className={th}>Question type</th>
                      {GENERATION_COLUMNS.map(([name]) => (
                        <th key={name} className={th}>
                          {name}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {run.byType.map((row) => (
                      <tr key={row.questionType}>
                        <th scope="row" className={`${td} text-left font-medium`}>
                          {questionType(row.questionType)}
                        </th>
                        {GENERATION_COLUMNS.map(([name, value]) => (
                          <td key={name} className={td}>
                            {value(row)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )
      )}
    </div>
  )
}

function signTest(test: SignTest): string {
  return `${test.verdict} (${test.challengerOnly} higher, ${test.shippedOnly} lower, p = ${test.pValue.toFixed(2)})`
}

function GeneratorChoiceTable({ choice }: { choice: GeneratorChoice }) {
  return (
    <div className="card overflow-x-auto p-3">
      <table className="min-w-full border-collapse text-[13px]">
        <caption className={caption}>
          Choosing the generator: is a challenger distinguishably better?
        </caption>
        <thead>
          <tr>
            <th className={th}>Challenger vs {choice.shipped}</th>
            <th className={th}>Cases</th>
            <th className={th}>Fact Recall</th>
            <th className={th}>Faithfulness</th>
            <th className={th}>Coverage Gaps</th>
            <th className={th}>Qualifies</th>
          </tr>
        </thead>
        <tbody>
          {choice.comparisons.map((c) => (
            <tr key={c.model}>
              <th scope="row" className={`${td} text-left font-medium`}>
                <code className="font-mono">{c.model}</code>
              </th>
              <td className={td}>{c.cases}</td>
              <td className={td}>{signTest(c.factRecall)}</td>
              <td className={td}>{signTest(c.faithfulness)}</td>
              <td className={td}>{signTest(c.coverageGaps)}</td>
              <td className={td}>{c.qualifies ? 'yes' : 'no'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
        Each challenger is compared with {choice.shipped} on the cases both answered, by an exact
        sign test on each case’s score. It qualifies only if ahead on Fact Recall or Coverage Gaps
        and behind on none of Fact Recall, Faithfulness and Coverage Gaps, each at p &lt; 0.05; the
        cheapest qualifier wins.{' '}
        <span className="font-medium text-accent-strong">Chosen: {choice.chosen}.</span>
      </p>
    </div>
  )
}

// --- Corpus coverage grid -----------------------------------------------------------------

/** Whether `period` directly follows `previous` (`2025Q4` after `2025Q3`, `2026Q1` after `2025Q4`). */
function follows(previous: string, period: string): boolean {
  const index = (p: string) => {
    const [year, quarter] = p.split('Q').map(Number)
    return year * 4 + quarter
  }
  return index(period) === index(previous) + 1
}

function CoverageGrid({ data }: { data: EvalExport }) {
  const { periods, companies } = data.coverage
  const tracked = companies.filter((c) => c.coverage === 'tracked').length
  const skipped = periods.map((p, i) => i > 0 && !follows(periods[i - 1], p))
  return (
    <Section
      id="coverage"
      title="Corpus coverage"
      intro={
        <>
          Every Filing in the Corpus, by the calendar quarter its Report Period ends in. {tracked}{' '}
          Tracked Companies have at least two years of consecutive quarters, so trend questions can
          be answered; the other {companies.length - tracked} are Snapshot Companies, and a trend
          asked of one is stated as a Coverage Gap.
        </>
      }
    >
      <div className="card overflow-x-auto p-3">
        <table className="border-collapse text-[12px]">
          <caption className={caption}>Filings by Company and Report Period</caption>
          <thead>
            <tr>
              <th className={`${th} sticky left-0 z-10`}>Company</th>
              <th className={th}>Coverage</th>
              {periods.map((period, i) => (
                <th
                  key={period}
                  className={`${th} px-1 text-center font-medium ${skipped[i] ? 'border-l-2 border-l-muted/40' : ''}`}
                >
                  <span className="block text-[10.5px] text-muted">{period.slice(0, 4)}</span>
                  {`Q${period.slice(5)}`}
                  <span className="sr-only"> {quarterLabel(period)}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {companies.map((company) => (
              <CoverageRow
                key={company.ticker}
                company={company}
                periods={periods}
                skipped={skipped}
              />
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
          <span className="font-mono font-semibold text-accent">K</span> a 10-K,{' '}
          <span className="font-mono text-accent">Q</span> a 10-Q; hover a cell for its Filing ID
          and Fiscal Period. Quarters with no Filing are left out, and a thicker line marks the
          skip.
        </p>
      </div>
    </Section>
  )
}

function CoverageRow({
  company,
  periods,
  skipped,
}: {
  company: CoverageCompany
  periods: string[]
  skipped: boolean[]
}) {
  const snapshot = company.coverage !== 'tracked'
  return (
    <tr className={snapshot ? 'bg-white/[0.015]' : undefined}>
      <th
        scope="row"
        className="sticky left-0 z-10 border-b border-line bg-elevated px-3 py-1 text-left font-medium whitespace-nowrap"
        title={`${company.company}${company.sector ? `, ${company.sector}` : ''}`}
      >
        <span className="font-mono">{company.ticker}</span>
        <span className="ml-2 hidden font-normal text-muted lg:inline">{company.company}</span>
      </th>
      <td className="border-b border-line px-3 py-1 whitespace-nowrap text-muted">
        {snapshot ? 'Snapshot' : 'Tracked'}
      </td>
      {periods.map((period, i) => {
        const filings = company.filings.filter((f) => f.period === period)
        return (
          <td
            key={period}
            className={`border-b border-line px-1 py-1 text-center ${skipped[i] ? 'border-l-2 border-l-muted/40' : ''}`}
          >
            {filings.map((f) => (
              <abbr
                key={f.filingId}
                title={`${f.filingId}${f.fiscalPeriod ? `, ${f.fiscalPeriod}` : ''}`}
                className={`inline-block w-5 rounded font-mono no-underline ${
                  f.formType === '10-K'
                    ? 'bg-accent font-semibold text-on-accent'
                    : 'bg-accent/15 text-accent-strong'
                }`}
              >
                {f.formType === '10-K' ? 'K' : 'Q'}
              </abbr>
            ))}
          </td>
        )
      })}
    </tr>
  )
}
