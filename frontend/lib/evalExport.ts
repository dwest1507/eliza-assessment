/**
 * The evaluation export (`data/eval-export.json`), written by `make eval-export` from
 * the harnesses' latest reports and the Corpus: what the "How it works" page and the
 * Calendar tab show. Its results are the latest round's only; `docs/evaluation.md` keeps
 * the history. Its shape is `backend/src/edgar_eval/export.py`'s.
 */

/** One retrieval Arm's mean scores over a group of cases. Keys of `hitAt` and `recallAt` are k. */
export interface RetrievalSummary {
  cases: number
  hitAt: Record<string, number>
  recallAt: Record<string, number>
  hitAll: number
  recallAll: number
  mrr: number
  meanSources: number
  /** Evidence Reached: the Required Facts whose evidence quote reached the Answer Context,
   * of those scored. Null in a report that does not record it (version 1's). */
  facts: number | null
  factsReached: number | null
  /** Mean tokens of Source text per Answer Context; null when not recorded. */
  meanSourceTokens: number | null
}

export interface RetrievalArm {
  name: string
  shipped: boolean
  /** False for an Arm that makes an API call at query time besides the Answer Call: under
   * the one-call rule it can't ship, though it is measured. */
  shippable: boolean
  overall: RetrievalSummary
  byType: ({ questionType: string } & RetrievalSummary)[]
  /** The cases with no expected Source in the top `k`. */
  missed: string[]
}

/** A challenger Arm against the Shipped Arm, by McNemar's exact test: on Evidence Reached
 * per Required Fact (version 2, one-sided) or on hit@10 per case (version 1). */
export interface ArmComparison {
  arm: string
  shippedArm: string
  metric: string
  /** The Required Facts paired; null for a comparison by case (version 1). */
  facts: number | null
  /** Facts (or cases) only the challenger reached. */
  challengerOnly: number
  /** Facts (or cases) only the Shipped Arm reached. */
  shippedOnly: number
  /** Two-sided, version 1's; kept beside the one-sided p-values. */
  pValue: number
  pAhead: number | null
  pBehind: number | null
  /** `ahead`, `behind` or `indistinguishable`: one-sided under version 2's thresholds. */
  verdict: string
}

/** One candidate as the free screen on Evidence Reached saw it (ADR 0011). */
export interface ScreenedCandidate {
  name: string
  facts: number
  factsReached: number
  gained: number
  lost: number
  pBehind: number
  kept: boolean
  shippable: boolean
  reason: string
}

/** Which challengers went on to paid Answer Calls, at most `limit`, and why. */
export interface Screen {
  shipped: string
  limit: number
  kept: string[]
  candidates: ScreenedCandidate[]
}

export interface RetrievalResults {
  /** `evidence reached` (version 2) or `hit@10` (version 1). */
  gatingMetric: string
  /** The k recall and the missed cases are reported at. */
  k: number
  ks: number[]
  scoredCases: number
  unscored: string[]
  arms: RetrievalArm[]
  comparisons: ArmComparison[]
  /** Null for a version 1 report, which was not screened. */
  screen: Screen | null
}

/** One generator's scores over a group of cases; null when there was nothing to score. */
export interface GenerationSummary {
  cases: number
  citationsValid: number
  figuresExact: number
  coverageGapsStated: number | null
  structureFollowed: number | null
  meanWords: number | null
  /** Over the must-state Required Facts under version 2. */
  factRecall: number | null
  /** Recall of the detail facts; null under version 1, whose facts are all must-state. */
  detailRecall: number | null
  faithfulness: number | null
  /** Answers with at least one Contradicted Claim; null when not recorded. */
  answersContradicted: number | null
  /** Answers cut off at the token cap; null when not recorded. */
  truncated: number | null
  judgmentsFailed: number | null
  meanCostUsd: number | null
  totalCostUsd: number | null
  meanLatencyS: number
  maxLatencyS: number
  meanFirstTokenS: number | null
  meanInputTokens: number | null
  meanOutputTokens: number | null
  judgeCostUsd: number
}

export interface GenerationRun {
  /** The report the run was read from, e.g. `generation-holdout.json`. */
  report: string
  model: string
  judgeModel: string
  promptVersion: string
  /** True for the round's Control Run: the shipped run's setup run again in the same
   * round (ADR 0011). */
  controlRun: boolean
  /** The probability at which Jev's verdict counts a Required Fact stated. */
  factCutoff: number | null
  /** Answers that passed every check; null when not recorded. */
  answersPassed: number | null
  overall: GenerationSummary
  byType: ({ questionType: string } & GenerationSummary)[]
  failing: { citations: string[]; figures: string[]; coverageGaps: string[] }
  errors: string[]
}

/** The mean paired difference, challenger minus shipped, with its bootstrap interval. */
export interface Difference {
  mean: number
  low: number
  high: number
  confidence: number
}

/** An exact sign test of a challenger against the shipped choice, case by case. */
export interface SignTest {
  /** Cases the challenger scored higher on. */
  challengerOnly: number
  /** Cases the shipped choice scored higher on. */
  shippedOnly: number
  /** Two-sided: what version 1 decided by. */
  pValue: number
  /** One-sided, version 2's; null in a version 1 choice file. */
  pAhead: number | null
  pBehind: number | null
  /** The cases paired and those left out (scored on one side only); null under version 1. */
  paired: number | null
  leftOut: number | null
  /** `ahead`, `behind` or `indistinguishable`. */
  verdict: string
  /** Shown, never decided on; null under version 1. */
  difference: Difference | null
}

/** A challenger (or the Control Run) against the shipped choice, case by case on each score. */
export interface RuleScores {
  cases: number
  factRecall: SignTest
  faithfulness: SignTest
  coverageGaps: SignTest
  /** Paired on "has no Contradicted Claim"; null under version 1's rule. */
  contradictedClaims: SignTest | null
  /** Whether the challenger qualifies under the rule it was compared by. */
  qualifies: boolean
}

/** A challenger generator (or the Control Run) against the shipped one. */
export interface GeneratorComparison extends RuleScores {
  model: string
}

/** The generator comparison (`make eval-generators`) and the generator the rule chose. */
export interface GeneratorChoice {
  shipped: string
  chosen: string
  /** True when the Control Run came out ahead of the shipped run: the shipped choice stands. */
  inconclusive: boolean
  reason: string | null
  /** The Control Run against the shipped run; null for version 1, which had none. */
  control: GeneratorComparison | null
  comparisons: GeneratorComparison[]
}

/** The holdout's latest run, shown beside a dev export. */
export interface HoldoutResults {
  splitCases: number
  /** Null when only answers were scored on the holdout. */
  retrieval: RetrievalResults | null
  /** The latest holdout generation run; null when only retrieval was scored. */
  generation: GenerationRun | null
}

/** A revenue Financial Fact in a Company Calendar: reported by one Filing, or derived. */
export interface CalendarRevenue {
  /** In whole US dollars. */
  value: number
  /** The Filing that reports it; for a derived fourth quarter, the 10-K whose year it splits. */
  filingId: string
  /** The row label as the Filing prints it, e.g. `Total net sales`; null when derived. */
  label: string | null
  /** How a derived figure was computed, e.g. `FY2025 less Q1–Q3 FY2025`; null when reported. */
  derived: string | null
}

/** One row of a Company Calendar: a fiscal quarter, or a fiscal year. */
export interface CalendarPeriod {
  /** `Q3 FY2026` or `FY2025`. */
  fiscalPeriod: string
  /** `quarter` or `year`. */
  kind: string
  /** The calendar months it covers, e.g. `Aug–Oct 2025` or `Feb 2024–Jan 2025`. */
  months: string
  /** The calendar year the period ends in. The rows are banded by fiscal year, read from
   * `fiscalPeriod`. */
  calendarYear: number
  /** The Filing that reports it (a fourth quarter's is the 10-K ending it), or null when
   * the Corpus has none. */
  filing: { filingId: string; formType: string; reportPeriod: string } | null
  /** Null for a period with no Filing, a Filing that yields no revenue figure, or a
   * fourth quarter whose year's three 10-Qs are not all in the Corpus. */
  revenue: CalendarRevenue | null
}

/**
 * A Company Calendar: a Company's fiscal quarters and years from its first Filing in the
 * Corpus to its latest, newest first, each fiscal year just before its fourth quarter.
 */
export interface CompanyCalendar {
  ticker: string
  company: string
  /** The names besides its Filings' one that a question names it by, from the Query
   * Scope parser's alias table: "Alphabet" and "Google" for Alphabet Inc. */
  commonNames: string[]
  sector: string | null
  /** `tracked` or `snapshot`. */
  coverage: string | null
  /** When its fiscal year ends, e.g. `late January` or `December 31`. */
  fiscalYearEnd: string | null
  periods: CalendarPeriod[]
}

/** A notable Company not in the Corpus, from the curated list. */
export interface MissingCompany {
  name: string
  ticker: string
  aliases: string[]
  sector: string
}

export interface EvalExport {
  exportedOn: string
  /** The Golden Set split the results are for: `dev`, `holdout` or `all`. */
  split: string
  goldenSet: { version: number; cases: number; splitCases: number }
  /** Version 2's one-sided thresholds (ADR 0011), fixed before running; null for version
   * 1, which decided at two-sided p < 0.05. */
  thresholds: { aheadP: number; behindP: number } | null
  retrieval: RetrievalResults
  /** The latest round's shipped run, its Control Run and each challenger generator's run,
   * those of the shipped run's round; empty until `make eval-generation` has run. */
  generation: GenerationRun[]
  /** Null until `make eval-generators` has run in the shipped run's round. */
  generatorChoice: GeneratorChoice | null
  /** Null until the holdout is scored, and for a holdout export itself. */
  holdout: HoldoutResults | null
  /** Every Company's Company Calendar, by ticker. */
  companies: CompanyCalendar[]
  /** The notable Companies not in the Corpus. */
  missingCompanies: MissingCompany[]
}

/**
 * The round's shipped run: the split's `generation-<split>.json` report, else the chosen
 * generator's run, never the Control Run; null until answers have been scored.
 */
export function shippedRun(data: EvalExport): GenerationRun | null {
  const runs = data.generation.filter((run) => !run.controlRun)
  return (
    runs.find((run) => run.report === `generation-${data.split}.json`) ??
    runs.find((run) => run.model === data.generatorChoice?.chosen) ??
    runs[0] ??
    null
  )
}

/** A score in [0, 1] to two decimals, or a dash when there was nothing to score. */
export function score(value: number | null): string {
  return value === null ? '–' : value.toFixed(2)
}

/** A p-value to three decimals, or `< 0.001`. */
export function pValue(value: number): string {
  return value < 0.001 ? '< 0.001' : value.toFixed(3)
}

/** A mean difference with its interval, e.g. `−0.005 [−0.058, +0.039]`. */
export function difference(d: Difference): string {
  const signed = (x: number) => `${x < 0 ? '−' : '+'}${Math.abs(x).toFixed(3)}`
  return `${signed(d.mean)} [${signed(d.low)}, ${signed(d.high)}]`
}

/** A cost in US dollars to four decimals, or a dash when unknown. */
export function usd(value: number | null): string {
  return value === null ? '–' : `$${value.toFixed(4)}`
}

/** A duration in seconds to one decimal, or a dash when unknown. */
export function seconds(value: number | null): string {
  return value === null ? '–' : `${value.toFixed(1)} s`
}

/** A question type such as `figure_trend` as `figure trend`. */
export function questionType(kind: string): string {
  return kind.replaceAll('_', ' ')
}
