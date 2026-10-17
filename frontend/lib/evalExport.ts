/**
 * The evaluation export (`data/eval-export.json`), written by `make eval-export` from
 * the harnesses' latest reports and the Corpus: what the "How it works" page shows.
 * Its shape is `backend/src/edgar_eval/export.py`'s.
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
}

export interface RetrievalArm {
  name: string
  shipped: boolean
  overall: RetrievalSummary
  byType: ({ questionType: string } & RetrievalSummary)[]
  /** The cases with no expected Source at the gating metric. */
  missed: string[]
}

/** A challenger Arm against the Shipped Arm, by McNemar's exact test. */
export interface ArmComparison {
  arm: string
  shippedArm: string
  metric: string
  challengerOnly: number
  shippedOnly: number
  pValue: number
  /** `ahead`, `behind` or `indistinguishable`. */
  verdict: string
}

export interface RetrievalResults {
  gatingMetric: string
  ks: number[]
  scoredCases: number
  unscored: string[]
  arms: RetrievalArm[]
  comparisons: ArmComparison[]
}

/** One generator's scores over a group of cases; null when there was nothing to score. */
export interface GenerationSummary {
  cases: number
  citationsValid: number
  figuresExact: number
  coverageGapsStated: number | null
  factRecall: number | null
  faithfulness: number | null
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
  overall: GenerationSummary
  byType: ({ questionType: string } & GenerationSummary)[]
  failing: { citations: string[]; figures: string[]; coverageGaps: string[] }
  errors: string[]
}

/** An exact sign test of a challenger against the shipped choice, case by case. */
export interface SignTest {
  /** Cases the challenger scored higher on. */
  challengerOnly: number
  /** Cases the shipped choice scored higher on. */
  shippedOnly: number
  pValue: number
  /** `ahead`, `behind` or `indistinguishable`. */
  verdict: string
}

/** A challenger generator against the shipped one, on the cases both answered. */
export interface GeneratorComparison {
  model: string
  cases: number
  factRecall: SignTest
  faithfulness: SignTest
  coverageGaps: SignTest
  /** Whether the challenger qualifies under the generator rule (ADR 0009). */
  qualifies: boolean
}

/** The generator comparison (`make eval-generators`) and the generator the rule chose. */
export interface GeneratorChoice {
  shipped: string
  chosen: string
  comparisons: GeneratorComparison[]
}

/** The holdout's reports, shown beside a dev export. */
export interface HoldoutResults {
  splitCases: number
  /** Null when only answers were scored on the holdout. */
  retrieval: RetrievalResults | null
  /** Every holdout generation run, the first first. */
  generation: GenerationRun[]
}

export interface CoverageFiling {
  /** The calendar quarter whose end the Report Period stands for, e.g. `2025Q3`. */
  period: string
  filingId: string
  formType: string
  reportPeriod: string
  fiscalPeriod: string | null
}

export interface CoverageCompany {
  ticker: string
  company: string
  sector: string | null
  /** `tracked` or `snapshot`. */
  coverage: string | null
  filings: CoverageFiling[]
}

export interface EvalExport {
  exportedOn: string
  /** The Golden Set split the results are for: `dev`, `holdout` or `all`. */
  split: string
  goldenSet: { version: number; cases: number; splitCases: number }
  retrieval: RetrievalResults
  /** One run per generator; empty until `make eval-generation` has run. */
  generation: GenerationRun[]
  /** Null until `make eval-generators` has run on the split. */
  generatorChoice: GeneratorChoice | null
  /** Null until the holdout is scored, and for a holdout export itself. */
  holdout: HoldoutResults | null
  coverage: { periods: string[]; companies: CoverageCompany[] }
}

/** A score in [0, 1] to two decimals, or a dash when there was nothing to score. */
export function score(value: number | null): string {
  return value === null ? '–' : value.toFixed(2)
}

/** A cost in US dollars to four decimals, or a dash when unknown. */
export function usd(value: number | null): string {
  return value === null ? '–' : `$${value.toFixed(4)}`
}

/** A duration in seconds to one decimal, or a dash when unknown. */
export function seconds(value: number | null): string {
  return value === null ? '–' : `${value.toFixed(1)} s`
}

/** `2025Q3` as `Q3 2025`. */
export function quarterLabel(period: string): string {
  const [year, quarter] = period.split('Q')
  return `Q${quarter} ${year}`
}

/** A question type such as `figure_trend` as `figure trend`. */
export function questionType(kind: string): string {
  return kind.replaceAll('_', ' ')
}
