import type { ReactNode } from 'react'
import type { GenerationRun, GenerationSummary } from '@/lib/evalExport'

/*
 * The plain overview at the top of "How it works", for a reader who doesn't know the
 * system's terms: how an answer is made, the headline quality numbers and the known
 * limits. Domain terms appear only as hover text, so a technical reader can still match
 * the page to the docs and to "Technical details" below.
 */

function OverviewSection({
  id,
  title,
  intro,
  children,
}: {
  id: string
  title: string
  intro?: ReactNode
  children: ReactNode
}) {
  return (
    <section aria-labelledby={id} className="flex scroll-mt-20 flex-col gap-4">
      <div>
        <h2 id={id} className="headline text-2xl font-semibold tracking-[-0.02em] md:text-3xl">
          {title}
        </h2>
        {intro && <p className="mt-2 max-w-3xl text-[15px] leading-relaxed text-muted">{intro}</p>}
      </div>
      {children}
    </section>
  )
}

const STEPS: { title: string; text: string }[] = [
  {
    title: 'Find the relevant filing passages',
    text: 'Your question is matched against the annual and quarterly reports (10-Ks and 10-Qs) the covered companies filed with the SEC, and the passages that fit it best are picked out. Fixed rules, not AI, work out which companies and periods you mean.',
  },
  {
    title: 'One AI call writes the answer',
    text: 'Those passages go to an AI model in a single request. It writes the answer from them alone, not from anything else it may know.',
  },
  {
    title: 'Every claim is cited',
    text: 'Each statement carries a numbered link to the passage it came from, so you can open the filing text and check it yourself.',
  },
]

/** How an answer is made, in three steps. */
export function HowAnswersAreMade() {
  return (
    <OverviewSection id="how-answers-are-made" title="How an answer is made">
      <ol className="grid gap-3 md:grid-cols-3">
        {STEPS.map((step, i) => (
          <li key={step.title} className="card flex flex-col gap-2 p-4">
            <span aria-hidden="true" className="font-mono text-[12px] tracking-widest text-accent">
              Step {i + 1}
            </span>
            <h3 className="text-[16px] font-semibold text-white">{step.title}</h3>
            <p className="text-[15px] leading-relaxed text-muted">{step.text}</p>
          </li>
        ))}
      </ol>
    </OverviewSection>
  )
}

/** A share in [0, 1] as a rounded percentage, "About 72%", or "100%" when exact. */
function percent(value: number): string {
  const rounded = Math.round(value * 100)
  return value === 1 ? '100%' : `About ${rounded}%`
}

interface Headline {
  label: string
  /** The domain term, shown on hover. */
  term: string
  value: (summary: GenerationSummary) => number | null
  meaning: (value: number) => string
}

const HEADLINES: Headline[] = [
  {
    label: 'of the key facts stated',
    term: 'Fact Recall',
    value: (s) => s.factRecall,
    meaning: (v) =>
      `Each test question comes with the facts a good answer must state, and the answers stated about ${Math.round(v * 100)} of every 100 of them.`,
  },
  {
    label: 'of claims backed by their citation',
    term: 'Faithfulness',
    value: (s) => s.faithfulness,
    meaning: (v) =>
      `A separate AI checker compared each claim with the passage it cites and found about ${Math.round(v * 100)} of every 100 supported by it.`,
  },
]

/**
 * The headline quality numbers, each with one plain sentence, worded as directional: a
 * rough guide on a few dozen test questions, not an exact rate. They are the holdout run's
 * when there is one, the questions kept apart from every choice, the numbers the slide deck
 * and `docs/evaluation.md`'s "At a glance" quote; else the round's shipped run on dev.
 *
 * Saying what's missing is shown in words, with no rate: only a few of the holdout's
 * questions have a Coverage Gap (two in the final round), too few for a share to mean much.
 */
export function HeadlineNumbers({ run, heldOut }: { run: GenerationRun; heldOut: boolean }) {
  const { cases } = run.overall
  const headlines = HEADLINES.flatMap((h) => {
    const value = h.value(run.overall)
    return value === null ? [] : [{ ...h, value }]
  })
  return (
    <OverviewSection
      id="how-well-it-answers"
      title="How well it answers"
      intro={
        heldOut ? (
          <>
            Measured on {cases} test questions kept apart until the end, never used to build or tune
            it, answered once by the setup you are using. With that few questions, read each number
            as a rough guide, not an exact rate.
          </>
        ) : (
          <>
            Measured on {cases} test questions written in advance, answered by the setup you are
            using. With that few questions, read each number as a rough guide, not an exact rate.
          </>
        )
      }
    >
      <ul className="grid gap-3 md:grid-cols-3">
        {headlines.map((h) => {
          const id = `headline-${h.term.toLowerCase().replaceAll(' ', '-')}`
          return (
            <li key={h.term} aria-labelledby={id} className="card flex flex-col gap-2 p-4">
              <div id={id} className="flex flex-col gap-0.5">
                <span className="headline text-3xl font-semibold text-white">
                  {percent(h.value)}
                </span>
                <span title={h.term} className="cursor-help text-[14px] text-ink">
                  {h.label}
                </span>
              </div>
              <p className="text-[15px] leading-relaxed text-muted">{h.meaning(h.value)}</p>
            </li>
          )
        })}
        <li aria-labelledby="headline-coverage-gaps" className="card flex flex-col gap-2 p-4">
          <div id="headline-coverage-gaps" className="flex flex-col gap-0.5">
            <span className="headline text-3xl font-semibold text-white">Says so</span>
            <span title="Coverage Gaps" className="cursor-help text-[14px] text-ink">
              when information is missing
            </span>
          </div>
          <p className="text-[15px] leading-relaxed text-muted">
            When the filings can’t answer part of a question, such as a forecast they don’t contain
            or a company they don’t cover, the answer says so instead of filling it in. Too few test
            questions turn on this to give it a reliable rate.
          </p>
        </li>
      </ul>
      <p className="text-[14px] text-muted">
        <a
          href={heldOut ? '#holdout' : '#scoreboard'}
          className="text-accent-strong underline-offset-4 transition-colors duration-200 hover:underline"
        >
          {heldOut ? 'See these questions’ full results' : 'See the full scoreboard'}
        </a>{' '}
        under Technical details for how each number is measured.
      </p>
    </OverviewSection>
  )
}

const LIMITS: { title: string; text: string }[] = [
  {
    title: 'It answers only from the filings provided.',
    text: 'No news, analyst reports, later filings or general knowledge. If a company isn’t in the list above, it says so instead of answering.',
  },
  {
    title: 'It can’t give a company’s own forecasts.',
    text: 'Most companies publish their guidance in earnings releases, which aren’t among these filings. Outlook answers draw on management’s commentary in the filings and say the guidance itself is missing.',
  },
  {
    title: 'It can’t show a trend for companies with only a few filings.',
    text: 'Asked how something changed over time for one of them, it says the filings don’t cover enough periods.',
  },
  {
    title: 'It makes one AI call per question.',
    text: 'There is no second pass to check or extend an answer, so a question that needs several rounds of research gets one answer from the passages found first.',
  },
]

/** The known limits, consistent with `docs/assumptions.md` (1, 2, 7 and 9). */
export function KnownLimits() {
  return (
    <OverviewSection id="known-limits" title="Known limits">
      <ul className="grid gap-3 md:grid-cols-2">
        {LIMITS.map((limit) => (
          <li key={limit.title} className="card p-4 text-[15px] leading-relaxed">
            <span className="font-semibold text-white">{limit.title}</span>{' '}
            <span className="text-muted">{limit.text}</span>
          </li>
        ))}
      </ul>
    </OverviewSection>
  )
}
