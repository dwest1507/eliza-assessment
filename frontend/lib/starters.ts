/**
 * The starter prompts shown on an empty conversation.
 *
 * Every starter is a labelled case with a `starter` object, so every demo prompt is
 * measured and none was picked after seeing results. The brief's three example questions
 * are Brief Suite cases (`data/eval/brief_suite.json`); the other three are Golden Set
 * cases (`data/eval/golden_set.json`). This copy keeps the front-end self-contained;
 * `__tests__/starters.test.ts` fails if it drifts from either file.
 */
export interface Starter {
  /** The Brief Suite or Golden Set case id. */
  caseId: string
  /** The button text. */
  label: string
  /** The question sent when the starter is clicked. */
  question: string
}

export const STARTERS: Starter[] = [
  {
    caseId: 'brief-risk-aapl-tsla-jpm',
    label: 'Compare the risk factors of Apple, Tesla and JPMorgan',
    question:
      'What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?',
  },
  {
    caseId: 'brief-outlook-nvda-revenue-two-years',
    label: "How has NVIDIA's revenue and outlook changed?",
    question: "How has NVIDIA's revenue and growth outlook changed over the last two years?",
  },
  {
    caseId: 'brief-sector-pharma-regulatory',
    label: 'Regulatory risks at the major pharmaceutical companies',
    question:
      'What regulatory risks do the major pharmaceutical companies face, and how are they addressing them?',
  },
  {
    caseId: 'sector-banks-risks',
    label: 'What are the main risks facing the major banks?',
    question: 'What are the main risks facing the major banks?',
  },
  {
    caseId: 'trend-jpm-revenue-snapshot',
    label: "How has JPMorgan's revenue changed over two years?",
    question: "How has JPMorgan's revenue changed over the last two years?",
  },
  {
    caseId: 'missing-wells-fargo-vs-jpm',
    label: 'Compare JPMorgan and Wells Fargo',
    question: 'Compare the risk factors of JPMorgan and Wells Fargo.',
  },
]
