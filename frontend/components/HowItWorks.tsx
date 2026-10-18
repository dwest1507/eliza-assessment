import Link from 'next/link'
import type { ReactNode } from 'react'
import { HeadlineNumbers, HowAnswersAreMade, KnownLimits } from '@/components/Overview'
import TechnicalDetails, { TechnicalSection } from '@/components/TechnicalDetails'
import WhatsCovered from '@/components/WhatsCovered'
import { coverageSummary } from '@/lib/coverage'
import {
  type BriefSuiteResults,
  type CoverageCompany,
  type EvalExport,
  type FactTest,
  type GenerationRun,
  type GenerationSummary,
  type GeneratorChoice,
  type GeneratorComparison,
  type HoldoutResults,
  type RetrievalChoice,
  type RetrievalChoiceComparison,
  type RetrievalResults,
  type RetrievalSummary,
  type Screen,
  type SignTest,
  difference,
  pValue,
  quarterLabel,
  questionType,
  score,
  seconds,
  shippedRun,
  signed,
  usd,
} from '@/lib/evalExport'

type Thresholds = EvalExport['thresholds']

/**
 * The "How it works" page: a plain overview first (how an answer is made, "What's
 * covered", the shipped run's headline numbers and the known limits), then the sections
 * under "Technical details", each collapsed by default: the architecture, the evaluation scoreboard (the shipped run
 * beside its Control Run, the retrieval Arms and their screen, the Arm and settings
 * comparisons fact by fact, and the generator comparison), the Brief Suite's verdicts, the holdout run beside dev and the Corpus
 * coverage grid, all read from the evaluation export so the evidence sits in the product.
 */
export default function HowItWorks({ data }: { data: EvalExport }) {
  const shipped = shippedRun(data)
  return (
    <div className="min-h-dvh text-ink">
      <header className="sticky top-0 z-30 flex items-center gap-4 border-b border-line bg-canvas/80 px-5 py-3 backdrop-blur-xl">
        <h1 className="text-[15px] font-semibold tracking-tight">
          How it works<span className="text-accent">.</span>
        </h1>
        <p className="hidden font-mono text-[12px] tracking-widest text-muted lg:block">
          How answers are made, what’s covered and how far to trust them
        </p>
        <Link
          href="/"
          className="ml-auto text-[13px] text-muted transition-colors duration-200 hover:text-ink"
        >
          ← Back to the workspace
        </Link>
      </header>

      <main className="flex flex-col gap-20 px-5 py-14">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-16">
          <HowAnswersAreMade />
          <WhatsCovered summary={coverageSummary(data.coverage)} />
          {shipped && <HeadlineNumbers run={shipped} />}
          <KnownLimits />
        </div>
        <TechnicalDetails
          heading={
            <div>
              <h2 className="headline text-3xl font-semibold tracking-[-0.02em] md:text-4xl">
                Technical details
              </h2>
              <p className="mt-2 max-w-3xl text-[14px] leading-relaxed text-muted">
                The architecture, the evaluation scores and the Filings behind every answer. Open a
                section by its heading, or all of them at once.
              </p>
            </div>
          }
        >
          <Architecture data={data} />
          <Scoreboard data={data} />
          {data.briefSuite && <BriefSuite brief={data.briefSuite} />}
          {data.holdout && <Holdout holdout={data.holdout} dev={data} />}
          <CoverageGrid data={data} />
        </TechnicalDetails>
      </main>
    </div>
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
    data.generation.find((run) => run.model === data.generatorChoice?.chosen && !run.controlRun) ??
    data.generation[0]
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
  const evidence = data.retrieval.gatingMetric === 'evidence reached'
  const measured: Stage[] = [
    {
      name: 'Golden Set',
      text: `${data.goldenSet.cases} labelled questions (version ${data.goldenSet.version}) with expected Sources, Required Facts and Coverage Gaps, split into dev and holdout by a hash rule${data.goldenSet.version >= 2 ? ' and frozen, each case recording its split' : ''}.`,
    },
    ...(data.briefSuite
      ? [
          {
            name: 'Brief Suite',
            text: `The brief’s three example questions and variants of each, ${data.briefSuite.cases.length} cases outside the split, each answered ${data.briefSuite.runs} times and passed or failed on its own.`,
          },
        ]
      : []),
    {
      name: 'Harnesses',
      text: evidence
        ? 'Retrieval: Evidence Reached per Required Fact (the gate), with hit@k, recall@k and MRR, and no LLM call. Generation: citation, figure and Coverage Gap checks in code, must-state Fact Recall and Faithfulness judged by a pinned Jev version, Contradicted Claims, cost and latency.'
        : 'Retrieval: hit@k, recall@k and MRR, with no LLM call. Generation: citation, figure and Coverage Gap checks in code, Fact Recall and Faithfulness judged by a pinned Jev version, cost and latency.',
    },
  ]

  return (
    <TechnicalSection
      id="architecture"
      title="Architecture"
      intro="Each question gets exactly one generative LLM request, the Answer Call. Everything before it is deterministic: the same conversation always gets the same Sources and the same Coverage Gaps, so every claim can be traced and every stage measured."
    >
      <Lane label="Built once, from the Corpus" stages={builtOnce} />
      <Lane label="For every question" stages={perQuestion} emphasis />
      <Lane label="Measured on the Golden Set" stages={measured} />
    </TechnicalSection>
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

/** A header cell without its background, for the coverage grid's fixed header, which sets an opaque one. */
const thBare =
  'border-b border-line px-3 py-1.5 text-left font-mono text-[12px] font-medium tracking-wide whitespace-nowrap text-muted'
const th = `${thBare} bg-raised`
const td = 'border-b border-line px-3 py-1.5 whitespace-nowrap tabular-nums'
const caption = 'mb-3 text-left text-[14px] font-semibold text-white'
const note = 'mt-2 text-[12.5px] leading-relaxed text-muted'
const badge =
  'ml-2 rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 font-mono text-[12px] tracking-widest text-accent-strong'
const quietBadge =
  'ml-2 rounded-full border border-line px-2 py-0.5 font-mono text-[12px] tracking-widest text-muted'

/** How a version's verdicts are worded: directional under version 2, as the docs word them. */
function verdictRule(thresholds: Thresholds): string {
  return thresholds
    ? `Verdicts are directional: one-sided p < ${thresholds.aheadP.toFixed(2)} for ahead and p < ${thresholds.behindP.toFixed(2)} for behind, fixed before running`
    : 'Version 1’s rule: verdicts are two-sided, ahead or behind only at p < 0.05'
}

function Scoreboard({ data }: { data: EvalExport }) {
  const { retrieval, split, goldenSet, thresholds } = data
  return (
    <TechnicalSection
      id="scoreboard"
      title="Evaluation scoreboard"
      intro={
        <>
          The harnesses’ latest results on Golden Set version {goldenSet.version}’s {split} split,
          exported on {data.exportedOn}. Choices are tuned on dev; the holdout is scored once per
          final setup, never to choose{data.holdout ? ', and its run follows' : ''}. Scores are
          shares from 0 to 1. {verdictRule(thresholds)}.
        </>
      }
    >
      <RetrievalTable
        retrieval={retrieval}
        split={split}
        splitCases={goldenSet.splitCases}
        thresholds={thresholds}
      />
      {retrieval.screen && <ScreenTable screen={retrieval.screen} thresholds={thresholds} />}
      {data.generation.length > 0 ? (
        <GenerationTable
          runs={data.generation}
          split={split}
          shipped={data.generatorChoice?.chosen ?? data.generation[0].model}
        />
      ) : (
        <p className="card px-4 py-3 text-[14px] text-muted">
          No answers have been scored on this split yet. Run{' '}
          <code className="font-mono text-[13px]">make eval-generation</code> (it calls the
          generator and the judge, so it costs money), then{' '}
          <code className="font-mono text-[13px]">make eval-export</code>.
        </p>
      )}
      {data.armChoice && <RetrievalChoiceTables choice={data.armChoice} thresholds={thresholds} />}
      {data.settingsChoice && (
        <RetrievalChoiceTables choice={data.settingsChoice} thresholds={thresholds} />
      )}
      {data.generatorChoice && (
        <GeneratorChoiceTable choice={data.generatorChoice} thresholds={thresholds} />
      )}
    </TechnicalSection>
  )
}

function BriefSuite({ brief }: { brief: BriefSuiteResults }) {
  const failing = brief.cases.filter((c) => !c.passed)
  const missed = failing.flatMap((c) => c.missed)
  const notReached = missed.filter((f) => f.evidenceReachedRuns === 0).length
  return (
    <TechnicalSection
      id="brief-suite"
      title="The Brief Suite"
      intro={
        <>
          The brief’s three example questions and variants of each, outside the dev/holdout split,
          each answered {brief.runs} times by <code className="font-mono">{brief.model}</code>{' '}
          (prompt {brief.promptVersion}). A case passes when every must-state Required Fact is
          stated in at least {brief.passRuns} of {brief.runs} runs and no run has a Contradicted
          Claim. Verdicts are reported case by case, never averaged:{' '}
          <span className="font-medium text-accent-strong">
            {brief.casesPassed} of {brief.cases.length} cases pass.
          </span>
        </>
      }
    >
      <div className="card overflow-x-auto p-3">
        <table className="min-w-full border-collapse text-[13px]">
          <caption className={caption}>Brief Suite: does each brief question pass?</caption>
          <thead>
            <tr>
              <th className={th}>Case</th>
              <th className={th}>Verdict</th>
              <th className={th}>Must-state facts</th>
              <th className={th}>Missed</th>
              <th className={th}>Of them, evidence never reached</th>
              <th className={th}>Runs with a Contradicted Claim</th>
            </tr>
          </thead>
          <tbody>
            {brief.cases.map((c) => (
              <tr key={c.caseId}>
                <th scope="row" className={`${td} text-left font-medium`} title={c.question}>
                  <code className="font-mono">{c.caseId}</code>
                  {c.briefQuestion && <span className={badge}>brief</span>}
                </th>
                <td className={`${td} ${c.passed ? 'font-semibold text-accent-strong' : ''}`}>
                  {c.passed ? 'pass' : 'fail'}
                </td>
                <td className={td}>{c.mustState}</td>
                <td className={td}>{c.missed.length}</td>
                <td className={td}>{c.missed.filter((f) => f.evidenceReachedRuns === 0).length}</td>
                <td className={td}>{c.contradictedRuns.length}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className={note}>
          A missed fact is stated in fewer than {brief.passRuns} runs. Of the {missed.length}{' '}
          must-state facts the {failing.length} failing cases miss, {notReached} have evidence that
          never reached the Answer Context in any run: retrieval misses, which no generator could
          state from the Sources. Hover a case for its question.
        </p>
      </div>
    </TechnicalSection>
  )
}

function Holdout({ holdout, dev }: { holdout: HoldoutResults; dev: EvalExport }) {
  const { splitCases } = holdout
  // The round's shipped run and Control Run on dev, shown beside the holdout's answers.
  const devRuns = dev.generation.filter(
    (run) => run.controlRun || run.report === `generation-${dev.split}.json`
  )
  const devArm = dev.retrieval.arms.find((arm) => arm.shipped)
  return (
    <TechnicalSection
      id="holdout"
      title="The holdout run"
      intro={
        <>
          The shipped setup, scored on Golden Set version {dev.goldenSet.version}’s {splitCases}{' '}
          holdout cases after every choice above was made on dev, shown beside dev. The holdout is
          scored once per final setup and never used to choose: nothing was changed after it. On{' '}
          {splitCases} cases one case moves a share by {(1 / splitCases).toFixed(2)}, so it shows
          whether the dev choices overfitted badly, not that one split scores better than the other.
        </>
      }
    >
      {holdout.retrieval && (
        <RetrievalTable
          retrieval={holdout.retrieval}
          split="holdout"
          splitCases={splitCases}
          thresholds={dev.thresholds}
          beside={
            devArm ? { label: `${dev.split}, ${devArm.name}`, summary: devArm.overall } : undefined
          }
        />
      )}
      {holdout.generation.length > 0 && (
        <GenerationTable
          runs={holdout.generation}
          split="holdout"
          beside={devRuns.map((run) => ({
            label: `${dev.split}, ${run.controlRun ? 'Control Run' : 'shipped run'}`,
            run,
          }))}
        />
      )}
    </TechnicalSection>
  )
}

function RetrievalTable({
  retrieval,
  split,
  splitCases,
  thresholds,
  beside,
}: {
  retrieval: RetrievalResults
  split: string
  splitCases: number
  thresholds: Thresholds
  /** Another split's Shipped Arm, shown as an extra row for comparison. */
  beside?: { label: string; summary: RetrievalSummary }
}) {
  const verdicts = new Map(retrieval.comparisons.map((c) => [c.arm, c]))
  const shipped = retrieval.arms.find((arm) => arm.shipped)
  const evidence = retrieval.gatingMetric === 'evidence reached'
  const unshippable = retrieval.arms.some((arm) => !arm.shippable)
  return (
    <div className="flex flex-col gap-3">
      <div className="card overflow-x-auto p-3">
        <table className="min-w-full border-collapse text-[13px]">
          <caption className={caption}>
            Retrieval: do the right Sections reach the Answer Call?
          </caption>
          <thead>
            <RetrievalHeader
              retrieval={retrieval}
              first="Arm"
              extra={retrieval.comparisons.length > 0 ? 'Against the Shipped Arm' : undefined}
            />
          </thead>
          <tbody>
            {retrieval.arms.map((arm) => {
              const c = verdicts.get(arm.name)
              return (
                <tr key={arm.name}>
                  <th scope="row" className={`${td} text-left font-medium`}>
                    <code className="font-mono">{arm.name}</code>
                    {arm.shipped && <span className={badge}>shipped</span>}
                    {!arm.shippable && <span className={quietBadge}>API call: can’t ship</span>}
                  </th>
                  <RetrievalCells summary={arm.overall} retrieval={retrieval} />
                  {retrieval.comparisons.length > 0 && (
                    <td className={td}>
                      {c
                        ? c.pAhead !== null && c.pBehind !== null
                          ? `${c.verdict} (${c.challengerOnly} facts gained, ${c.shippedOnly} lost, p ahead = ${pValue(c.pAhead)}, p behind = ${pValue(c.pBehind)})`
                          : `${c.verdict} (${c.challengerOnly} won, ${c.shippedOnly} lost, p = ${c.pValue.toFixed(2)})`
                        : '–'}
                    </td>
                  )}
                </tr>
              )
            })}
            {beside && (
              <tr>
                <th scope="row" className={`${td} text-left font-medium text-muted`}>
                  {beside.label}
                </th>
                <RetrievalCells summary={beside.summary} retrieval={retrieval} />
                {retrieval.comparisons.length > 0 && <td className={td}>–</td>}
              </tr>
            )}
          </tbody>
        </table>
        <p className={note}>
          Scored on {retrieval.scoredCases} of {splitCases} {split} cases
          {retrieval.unscored.length > 0 &&
            `; ${retrieval.unscored.length} have no expected Source to find (a Company missing from the Corpus)`}
          .{' '}
          {evidence ? (
            <>
              The gate is Evidence Reached: the Required Facts whose evidence quote reaches the
              Answer Context.
              {retrieval.comparisons.length > 0 &&
                ` Each challenger is compared with the Shipped Arm fact by fact by McNemar’s exact test, one-sided${thresholds ? ` (ahead at p < ${thresholds.aheadP.toFixed(2)}, behind at p < ${thresholds.behindP.toFixed(2)}, fixed before running)` : ''}.`}{' '}
              hit@k, recall@k and MRR are reported, not gated on.
            </>
          ) : (
            <>
              Gating metric {retrieval.gatingMetric}
              {retrieval.comparisons.length > 0 &&
                ', as version 1 gated it: each challenger is compared with the Shipped Arm case by case by McNemar’s exact test, and called ahead or behind only at p < 0.05'}
              .
            </>
          )}
          {unshippable &&
            ' An Arm that makes an API call at query time is measured but can’t ship: the Answer Call is a question’s only API call.'}
          {shipped && shipped.missed.length > 0 && (
            <>
              {' '}
              Missed by {shipped.name} at hit@{retrieval.k}: {shipped.missed.join(', ')}.
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
      <th className={th}>recall@{retrieval.k}</th>
      <th className={th}>recall@all</th>
      <th className={th}>MRR</th>
      <th className={th}>Sources</th>
      {retrieval.gatingMetric === 'evidence reached' && <th className={th}>Evidence Reached</th>}
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
  const gate = retrieval.gatingMetric.startsWith('hit@')
    ? retrieval.gatingMetric.split('@')[1]
    : null
  return (
    <>
      <td className={td}>{summary.cases}</td>
      {retrieval.ks.map((k) => (
        <td key={k} className={`${td} ${String(k) === gate ? 'font-semibold' : ''}`}>
          {score(summary.hitAt[String(k)] ?? null)}
        </td>
      ))}
      <td className={td}>{score(summary.recallAt[String(retrieval.k)] ?? null)}</td>
      <td className={td}>{score(summary.recallAll)}</td>
      <td className={td}>{score(summary.mrr)}</td>
      <td className={td}>{summary.meanSources.toFixed(1)}</td>
      {retrieval.gatingMetric === 'evidence reached' && (
        <td className={`${td} font-semibold`}>
          {summary.facts !== null && summary.factsReached !== null
            ? `${summary.factsReached} of ${summary.facts}`
            : '–'}
        </td>
      )}
    </>
  )
}

function ScreenTable({ screen, thresholds }: { screen: Screen; thresholds: Thresholds }) {
  return (
    <div className="card overflow-x-auto p-3">
      <table className="min-w-full border-collapse text-[13px]">
        <caption className={caption}>
          The screen: which challengers go on to paid Answer Calls?
        </caption>
        <thead>
          <tr>
            <th className={th}>Candidate</th>
            <th className={th}>Can ship</th>
            <th className={th}>Evidence Reached</th>
            <th className={th}>Gained / lost</th>
            <th className={th}>p behind</th>
            <th className={th}>Screen</th>
          </tr>
        </thead>
        <tbody>
          {screen.candidates.map((c) => (
            <tr key={c.name}>
              <th scope="row" className={`${td} text-left font-medium`}>
                <code className="font-mono">{c.name}</code>
              </th>
              <td className={td}>{c.shippable ? 'yes' : 'no: API call at query time'}</td>
              <td className={td}>
                {c.factsReached} of {c.facts}
              </td>
              <td className={td}>
                {c.gained} / {c.lost}
              </td>
              <td className={td}>{pValue(c.pBehind)}</td>
              <td className={`${td} whitespace-normal`}>{c.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className={note}>
        Free, before any paid run: each candidate is compared with {screen.shipped} on Evidence
        Reached, and goes on only if not behind
        {thresholds ? ` (one-sided p < ${thresholds.behindP.toFixed(2)})` : ''} and able to ship; at
        most {screen.limit} go on, the most Evidence Reached first.{' '}
        <span className="font-medium text-accent-strong">
          Go on: {screen.kept.join(', ') || 'none'}.
        </span>
      </p>
    </div>
  )
}

const GENERATION_COLUMNS: [string, (s: GenerationSummary) => string][] = [
  ['Cases', (s) => String(s.cases)],
  ['Citations valid', (s) => score(s.citationsValid)],
  ['Figures exact', (s) => score(s.figuresExact)],
  ['Gaps stated', (s) => score(s.coverageGapsStated)],
  ['Fact Recall', (s) => score(s.factRecall)],
  ['Detail recall', (s) => score(s.detailRecall)],
  ['Faithfulness', (s) => score(s.faithfulness)],
  ['Contradicted', (s) => (s.answersContradicted === null ? '–' : String(s.answersContradicted))],
  ['$ per answer', (s) => usd(s.meanCostUsd)],
  ['Latency', (s) => seconds(s.meanLatencyS)],
  ['First text', (s) => seconds(s.meanFirstTokenS)],
]

function GenerationTable({
  runs,
  split,
  shipped,
  beside = [],
}: {
  runs: GenerationRun[]
  split: string
  /** The generator the rule chose, marked on its row. */
  shipped?: string
  /** Another split's runs, shown as extra rows for comparison. */
  beside?: { label: string; run: GenerationRun }[]
}) {
  const judges = [...new Set(runs.map((run) => run.judgeModel))].join(', ')
  const cutoffs = [...new Set(runs.map((run) => run.factCutoff).filter((c) => c !== null))]
  const versioned = runs.some((run) => run.overall.detailRecall !== null)
  // Name the report when two runs share a generator, e.g. two holdout runs.
  const repeated = (run: GenerationRun) =>
    !run.controlRun && runs.filter((r) => r.model === run.model && !r.controlRun).length > 1
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
                  {run.controlRun ? (
                    <span className={quietBadge}>Control Run</span>
                  ) : (
                    run.model === shipped && <span className={badge}>shipped</span>
                  )}
                  <span className="ml-2 text-[12px] text-muted">prompt {run.promptVersion}</span>
                  {repeated(run) && (
                    <span className="ml-2 font-mono text-[12px] text-muted">{run.report}</span>
                  )}
                </th>
                {GENERATION_COLUMNS.map(([name, value]) => (
                  <td key={name} className={td}>
                    {value(run.overall)}
                  </td>
                ))}
              </tr>
            ))}
            {beside.map(({ label, run }) => (
              <tr key={`beside-${run.report}`}>
                <th scope="row" className={`${td} text-left font-medium text-muted`}>
                  {label}
                </th>
                {GENERATION_COLUMNS.map(([name, value]) => (
                  <td key={name} className={`${td} text-muted`}>
                    {value(run.overall)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p className={note}>
          One real Answer Call per {split} case. Citations, figures and Coverage Gaps are checked in
          code; Fact Recall and Faithfulness are judged by {judges}, pinned to an exact version and
          from neither generator’s family
          {versioned &&
            `. Fact Recall is over the must-state Required Facts${cutoffs.length ? `, a fact counting as stated at Jev’s probability ${cutoffs.join(', ')} or more` : ''}; detail recall is shown beside it; Contradicted counts the answers with a Contradicted Claim, each of which fails`}
          {runs.some((run) => run.controlRun) &&
            '. The Control Run is the shipped choice run again: its distance from the shipped run is the noise every comparison is read against'}
          . Cost is the list price of the tokens used, an upper bound. A dash means there was
          nothing to score.
        </p>
      </div>
      {runs.map(
        (run) =>
          run.byType.length > 0 &&
          !run.controlRun && (
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

function signTest(test: SignTest | null): ReactNode {
  if (!test) return '–'
  if (test.pAhead === null || test.pBehind === null) {
    return `${test.verdict} (${test.challengerOnly} higher, ${test.shippedOnly} lower, p = ${test.pValue.toFixed(2)})`
  }
  return (
    <>
      {test.verdict} ({test.challengerOnly} higher, {test.shippedOnly} lower, p ahead ={' '}
      {pValue(test.pAhead)}, p behind = {pValue(test.pBehind)})
      {test.difference && (
        <span className="block text-[12px] text-muted">{difference(test.difference)}</span>
      )}
    </>
  )
}

function factTest(test: FactTest | null): ReactNode {
  if (!test) return '–'
  return (
    <>
      {test.verdict} ({signed(test.totalDifference)}: {test.challengerStated} against{' '}
      {test.shippedStated} of {test.facts} must-state facts, p ahead = {pValue(test.pAhead)}, p
      behind = {pValue(test.pBehind)})
      {test.difference && (
        <span className="block text-[12px] text-muted">per case {difference(test.difference)}</span>
      )}
    </>
  )
}

/** How each comparison's facts are split by where their evidence reached, in the export's order. */
const EVIDENCE_LABELS: Record<string, string> = {
  challenger_only: 'Reached by the challenger only',
  shipped_only: 'By the shipped choice only',
  both: 'By both',
  neither: 'By neither',
  unrecorded: 'Not recorded',
}

const RETRIEVAL_RULES: Record<string, { what: string; caption: string; label: string }> = {
  arms: {
    what: 'Arm',
    caption: 'Choosing the Arm: do a challenger’s answers state more facts?',
    label: 'Arm comparison',
  },
  settings: {
    what: 'setting',
    caption: 'Choosing the chunk size and context budget: do a setting’s answers state more facts?',
    label: 'Settings comparison',
  },
}

/** The Arm or settings comparison: each challenger and the Control Run against the shipped
 * choice, fact by fact (ADR 0015) beside the per-case sign tests, then the facts stated split
 * by where their evidence reached. A choice file made before the fact-level test shows its
 * per-case verdicts only, as recorded. */
function RetrievalChoiceTables({
  choice,
  thresholds,
}: {
  choice: RetrievalChoice
  thresholds: Thresholds
}) {
  const rule = RETRIEVAL_RULES[choice.rule] ?? RETRIEVAL_RULES.arms
  const rows = [
    ...(choice.control ? [{ label: 'Control Run', c: choice.control }] : []),
    ...choice.comparisons.map((c) => ({ label: c.name, c })),
  ]
  const factLevel = rows.some(({ c }) => c.statedFacts !== null)
  const resamples = rows.find(({ c }) => c.statedFacts)?.c.statedFacts?.resamples
  const unshippable = choice.comparisons.some((c) => !c.shippable)
  const ahead = thresholds ? ` (p < ${thresholds.aheadP.toFixed(2)})` : ''
  const behind = thresholds ? ` (p < ${thresholds.behindP.toFixed(2)})` : ''
  const name = (label: string, c: RetrievalChoiceComparison) =>
    c === choice.control ? (
      <>
        Control Run
        <span className="ml-2 text-[12px] text-muted">{choice.shipped} again</span>
      </>
    ) : (
      <>
        <code className="font-mono">{label}</code>
        {!c.shippable && <span className={quietBadge}>API call: can’t ship</span>}
      </>
    )
  return (
    <div className="flex flex-col gap-3">
      <div className="card overflow-x-auto p-3">
        <table className="min-w-full border-collapse text-[13px]">
          <caption className={caption}>{rule.caption}</caption>
          <thead>
            <tr>
              <th className={th}>Against {choice.shipped}</th>
              <th className={th}>Cases</th>
              <th className={th}>Fact Recall fact by fact</th>
              <th className={th}>Fact Recall case by case</th>
              <th className={th}>Faithfulness</th>
              <th className={th}>Coverage Gaps</th>
              <th className={th}>No Contradicted Claim</th>
              <th className={th}>Qualifies</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ label, c }) => (
              <tr key={label}>
                <th scope="row" className={`${td} text-left font-medium`}>
                  {name(label, c)}
                </th>
                <td className={td}>{c.cases}</td>
                <td className={td}>{factTest(c.statedFacts)}</td>
                <td className={td}>{signTest(c.factRecall)}</td>
                <td className={td}>{signTest(c.faithfulness)}</td>
                <td className={td}>{signTest(c.coverageGaps)}</td>
                <td className={td}>{signTest(c.contradictedClaims)}</td>
                <td className={td}>{c === choice.control ? '–' : c.qualifies ? 'yes' : 'no'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className={note}>
          {factLevel ? (
            <>
              Each challenger {rule.what} is compared with {choice.shipped} on the cases both
              scored. It qualifies only if ahead on Fact Recall fact by fact{ahead}: the must-state
              facts its answers state, summed over the paired cases, tested by a one-sided
              case-cluster bootstrap
              {resamples
                ? ` (whole cases resampled ${resamples.toLocaleString('en-US')} times from a fixed seed)`
                : ''}
              . It must also be behind on none of Fact Recall case by case (an exact sign test),
              Faithfulness, Coverage Gaps and Contradicted Claims{behind}; the cheapest qualifier
              wins. Under each fact-level verdict, the mean difference in facts stated per case and
              its 95% bootstrap interval, shown and not decided on. If the Control Run came out
              ahead of the shipped run fact by fact, the comparison would be inconclusive and{' '}
              {choice.shipped} would stand.
            </>
          ) : (
            <>
              Decided under ADR 0011’s per-case rule, before the fact-level test, and stands as
              recorded: a challenger {rule.what} qualifies only if ahead on Fact Recall case by case
              {ahead} and behind on none of Fact Recall, Faithfulness, Coverage Gaps and
              Contradicted Claims{behind}, each by an exact sign test, one-sided. Its choice file
              records no fact-level result.
            </>
          )}
          {unshippable &&
            ' A challenger whose Arm makes an API call at query time is compared but never chosen.'}{' '}
          {choice.inconclusive && <>Inconclusive: {choice.reason}. </>}
          <span className="font-medium text-accent-strong">Chosen: {choice.chosen}.</span>
        </p>
      </div>
      {factLevel && <EvidenceTable label={rule.label} rows={rows} />}
    </div>
  )
}

function EvidenceTable({
  label,
  rows,
}: {
  label: string
  rows: { label: string; c: RetrievalChoiceComparison }[]
}) {
  const statuses = Object.keys(EVIDENCE_LABELS).filter((status) =>
    rows.some(({ c }) => c.byEvidence?.some((g) => g.status === status && g.facts > 0))
  )
  return (
    <div className="card overflow-x-auto p-3">
      <table className="min-w-full border-collapse text-[13px]">
        <caption className={caption}>{label}: facts stated by where their evidence reached</caption>
        <thead>
          <tr>
            <th className={th}>Stated, challenger / shipped</th>
            {statuses.map((status) => (
              <th key={status} className={th}>
                {EVIDENCE_LABELS[status]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ label: name, c }) => (
            <tr key={name}>
              <th scope="row" className={`${td} text-left font-medium`}>
                {name === 'Control Run' ? name : <code className="font-mono">{name}</code>}
              </th>
              {statuses.map((status) => {
                const group = c.byEvidence?.find((g) => g.status === status)
                return (
                  <td key={status} className={td}>
                    {group && group.facts > 0
                      ? `${group.challengerStated} / ${group.shippedStated} of ${group.facts}`
                      : '–'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className={note}>
        Each paired must-state fact once, by whose Answer Context its evidence quote reached, with
        how many each side’s answers state. A fact only the challenger reached is a retrieval gain;
        one both reached measures how each side’s generator used the same evidence.
      </p>
    </div>
  )
}

function GeneratorChoiceRow({ c }: { c: GeneratorComparison }) {
  return (
    <>
      <td className={td}>{c.cases}</td>
      <td className={td}>{signTest(c.factRecall)}</td>
      <td className={td}>{signTest(c.faithfulness)}</td>
      <td className={td}>{signTest(c.coverageGaps)}</td>
      <td className={td}>{signTest(c.contradictedClaims)}</td>
    </>
  )
}

function GeneratorChoiceTable({
  choice,
  thresholds,
}: {
  choice: GeneratorChoice
  thresholds: Thresholds
}) {
  return (
    <div className="card overflow-x-auto p-3">
      <table className="min-w-full border-collapse text-[13px]">
        <caption className={caption}>
          Choosing the generator: is a challenger distinguishably better?
        </caption>
        <thead>
          <tr>
            <th className={th}>Against {choice.shipped}</th>
            <th className={th}>Cases</th>
            <th className={th}>Fact Recall</th>
            <th className={th}>Faithfulness</th>
            <th className={th}>Coverage Gaps</th>
            <th className={th}>No Contradicted Claim</th>
            <th className={th}>Qualifies</th>
          </tr>
        </thead>
        <tbody>
          {choice.control && (
            <tr>
              <th scope="row" className={`${td} text-left font-medium`}>
                Control Run
                <span className="ml-2 text-[12px] text-muted">{choice.shipped} again</span>
              </th>
              <GeneratorChoiceRow c={choice.control} />
              <td className={td}>–</td>
            </tr>
          )}
          {choice.comparisons.map((c) => (
            <tr key={c.model}>
              <th scope="row" className={`${td} text-left font-medium`}>
                <code className="font-mono">{c.model}</code>
              </th>
              <GeneratorChoiceRow c={c} />
              <td className={td}>{c.qualifies ? 'yes' : 'no'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className={note}>
        {thresholds ? (
          <>
            Each challenger is compared with {choice.shipped} on the cases both scored, by an exact
            sign test on each case’s score, one-sided. It qualifies only if ahead on Fact Recall or
            Coverage Gaps (p &lt; {thresholds.aheadP.toFixed(2)}) and behind on none of Fact Recall,
            Faithfulness, Coverage Gaps and Contradicted Claims (p &lt;{' '}
            {thresholds.behindP.toFixed(2)}); the cheapest qualifier wins. These verdicts are
            directional: one-sided, at thresholds fixed before running. Under each verdict, the mean
            paired difference (challenger minus shipped) and its 95% bootstrap interval, shown and
            not decided on. If the Control Run came out ahead of the shipped run, the comparison
            would be inconclusive and the shipped generator would stand. This comparison was scored
            on the earlier measurement and stands as recorded: it set the challenger’s run against a
            shipped run and Control Run scored before the measurement fixes, not against the newer
            ones in the answers table.
          </>
        ) : (
          <>
            Version 1’s rule: each challenger is compared with {choice.shipped} on the cases both
            answered, by an exact sign test on each case’s score. It qualifies only if ahead on Fact
            Recall or Coverage Gaps and behind on none of Fact Recall, Faithfulness and Coverage
            Gaps, each at two-sided p &lt; 0.05; the cheapest qualifier wins.
          </>
        )}{' '}
        {choice.inconclusive && <>Inconclusive: {choice.reason}. </>}
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

/** The grid's fixed header cells: the other headers' raised shade made opaque, so the cells
    scrolling beneath them stay readable. */
const fixedHeader = `${thBare} sticky top-0 bg-[color-mix(in_srgb,white_6%,var(--color-elevated))]`
/** The Company column, fixed at a set width (padding included) so the coverage column can sit beside it. */
const companyColumn = 'sticky left-0 w-20 min-w-20 lg:w-64 lg:min-w-64'
const coverageColumn = 'sticky left-20 lg:left-64'

function CoverageGrid({ data }: { data: EvalExport }) {
  const { periods, companies } = data.coverage
  const tracked = companies.filter((c) => c.coverage === 'tracked').length
  const skipped = periods.map((p, i) => i > 0 && !follows(periods[i - 1], p))
  return (
    <TechnicalSection
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
      <div className="card p-3">
        {/* Its own scroll area, no taller than the screen, so both scrollbars stay in reach;
            the header row and the Company and coverage columns stay fixed while it scrolls. */}
        <div
          role="region"
          aria-labelledby="coverage-grid"
          tabIndex={0}
          className="max-h-[70dvh] overflow-auto rounded-lg focus-visible:outline-2 focus-visible:outline-accent"
        >
          <table className="border-separate border-spacing-0 text-[12px]">
            <caption id="coverage-grid" className={caption}>
              Filings by Company and Report Period
            </caption>
            <thead>
              <tr>
                <th className={`${fixedHeader} ${companyColumn} z-30`}>Company</th>
                <th className={`${fixedHeader} ${coverageColumn} z-30`}>Coverage</th>
                {periods.map((period, i) => (
                  <th
                    key={period}
                    className={`${fixedHeader} z-20 px-1 text-center font-medium ${skipped[i] ? 'border-l-2 border-l-muted/40' : ''}`}
                  >
                    <span className="block text-[12px] text-muted">{period.slice(0, 4)}</span>
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
        </div>
        <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
          <span className="font-mono font-semibold text-accent">K</span> a 10-K,{' '}
          <span className="font-mono text-accent">Q</span> a 10-Q; hover a cell for its Filing ID
          and Fiscal Period. Quarters with no Filing are left out, and a thicker line marks the
          skip.
        </p>
      </div>
    </TechnicalSection>
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
        className={`${companyColumn} z-10 border-b border-line bg-elevated px-3 py-1 text-left font-medium whitespace-nowrap`}
        title={`${company.company}${company.sector ? `, ${company.sector}` : ''}`}
      >
        <div className="w-14 truncate lg:w-58">
          <span className="font-mono">{company.ticker}</span>
          <span className="ml-2 hidden font-normal text-muted lg:inline">{company.company}</span>
        </div>
      </th>
      <td
        className={`${coverageColumn} z-10 border-b border-line bg-elevated px-3 py-1 whitespace-nowrap text-muted`}
      >
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
