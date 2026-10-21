import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import HowItWorks from '@/components/HowItWorks'
import Workspace from '@/components/Workspace'
import { coverageSummary } from '@/lib/coverage'
import type { EvalExport } from '@/lib/evalExport'
import fixture from './fixtures/eval-export.json'

const EXPORT: EvalExport = fixture

const TECHNICAL_SECTIONS = [
  'Architecture',
  'Evaluation scoreboard',
  'The Brief Suite',
  'The holdout run',
  'Corpus coverage',
]

function section(name: string) {
  return screen.getByRole('region', { name })
}

/** Opens a technical section by clicking its heading, as a reader would, and returns it. */
async function openSection(name: string) {
  await userEvent.setup().click(within(section(name)).getByRole('button', { name }))
  return section(name)
}

afterEach(() => {
  window.history.replaceState(null, '', '/')
})

describe('the "How it works" page', () => {
  it('shows the architecture, from the question to one Answer Call', async () => {
    render(<HowItWorks data={EXPORT} />)
    await openSection('Architecture')

    const architecture = section('Architecture')
    for (const stage of ['Query Scope', 'Retrieval', 'Answer Context', 'Answer Call']) {
      expect(within(architecture).getByRole('heading', { name: stage })).toBeInTheDocument()
    }
    // The live choices come from the export: the Shipped Arm, the generator and its prompt.
    expect(architecture).toHaveTextContent('fts5')
    expect(architecture).toHaveTextContent('gpt-6-luna')
    expect(architecture).toHaveTextContent('prompt v7')
  })

  it('says which Golden Set it describes and words its verdicts as directional', async () => {
    render(<HowItWorks data={EXPORT} />)
    await openSection('Evaluation scoreboard')
    await openSection('Architecture')

    const scoreboard = section('Evaluation scoreboard')
    expect(scoreboard).toHaveTextContent('Golden Set version 2’s dev split')
    expect(scoreboard).toHaveTextContent(
      'Verdicts are directional: one-sided p < 0.10 for ahead and p < 0.20 for behind, fixed before running'
    )
    expect(section('Architecture')).toHaveTextContent('80 labelled questions (version 2)')
  })

  it('gates retrieval on Evidence Reached, with each Arm’s one-sided verdict', async () => {
    render(<HowItWorks data={EXPORT} />)
    await openSection('Evaluation scoreboard')

    const table = within(section('Evaluation scoreboard')).getByRole('table', {
      name: /Retrieval/,
    })
    const shipped = within(table).getByRole('row', { name: /fts5/ })
    expect(shipped).toHaveTextContent('shipped')
    expect(shipped).toHaveTextContent('740 of 939') // Evidence Reached, the gate
    expect(shipped).toHaveTextContent('0.93') // hit@10, still reported
    expect(shipped).toHaveTextContent('0.78') // MRR
    const local = within(table).getByRole('row', { name: /dense-local/ })
    expect(local).toHaveTextContent('behind (74 facts gained, 94 lost')
    expect(local).toHaveTextContent('p behind = 0.071')
    const hosted = within(table).getByRole('row', { name: /^hybrid/ })
    expect(hosted).toHaveTextContent('can’t ship')
    expect(hosted).toHaveTextContent('ahead (72 facts gained, 11 lost, p ahead = < 0.001')
    expect(section('Evaluation scoreboard')).toHaveTextContent('57 of 60 dev cases')
    expect(section('Evaluation scoreboard')).toHaveTextContent('The gate is Evidence Reached')
  })

  it('shows the screen: which challengers went on, and why each was kept or dropped', async () => {
    render(<HowItWorks data={EXPORT} />)
    await openSection('Evaluation scoreboard')

    const table = within(section('Evaluation scoreboard')).getByRole('table', {
      name: /The screen/,
    })
    const hosted = within(table).getByRole('row', { name: /^hybrid/ })
    expect(hosted).toHaveTextContent('no: API call at query time')
    expect(hosted).toHaveTextContent('available if the one-call limit is lifted')
    expect(within(table).getByRole('row', { name: /dense-local/ })).toHaveTextContent(
      'dropped: behind on Evidence Reached'
    )
    expect(within(table).getByRole('row', { name: /rerank/ })).toHaveTextContent('kept')
    expect(section('Evaluation scoreboard')).toHaveTextContent('Go on: hybrid-local, rerank.')
  })

  it('shows a version 1 export as version 1 gated it, with its two-sided rule', async () => {
    const v1Retrieval = {
      ...EXPORT.retrieval,
      gatingMetric: 'hit@10',
      screen: null,
      comparisons: [
        {
          ...EXPORT.retrieval.comparisons[1],
          metric: 'hit@10',
          facts: null,
          pAhead: null,
          pBehind: null,
          challengerOnly: 0,
          shippedOnly: 0,
          pValue: 1,
          verdict: 'indistinguishable',
        },
      ],
    }
    render(
      <HowItWorks
        data={{
          ...EXPORT,
          goldenSet: { version: 1, cases: 30, splitCases: 20 },
          thresholds: null,
          retrieval: v1Retrieval,
          generatorChoice: null,
        }}
      />
    )
    await openSection('Evaluation scoreboard')

    const scoreboard = section('Evaluation scoreboard')
    expect(scoreboard).toHaveTextContent('Version 1’s rule: verdicts are two-sided')
    expect(scoreboard).toHaveTextContent('Gating metric hit@10, as version 1 gated it')
    const table = within(scoreboard).getByRole('table', { name: /Retrieval/ })
    expect(within(table).getByRole('row', { name: /rerank/ })).toHaveTextContent(
      'indistinguishable (0 won, 0 lost, p = 1.00)'
    )
    expect(within(scoreboard).queryByRole('table', { name: /The screen/ })).not.toBeInTheDocument()
  })

  it('shows the shipped run beside its Control Run, with each generator’s scores and cost', async () => {
    render(<HowItWorks data={EXPORT} />)
    await openSection('Evaluation scoreboard')

    const table = within(section('Evaluation scoreboard')).getByRole('table', {
      name: /Answers/,
    })
    const [shipped, control] = within(table).getAllByRole('row', { name: /gpt-6-luna/ })
    expect(shipped).toHaveTextContent('shipped')
    expect(shipped).toHaveTextContent('0.72') // Fact Recall
    expect(shipped).toHaveTextContent('0.48') // detail recall
    expect(shipped).toHaveTextContent('0.93') // Faithfulness
    expect(shipped).toHaveTextContent('$0.0028')
    expect(shipped).toHaveTextContent('8.2 s')
    expect(control).toHaveTextContent('Control Run')
    expect(control).not.toHaveTextContent('shipped')
    expect(control).toHaveTextContent('0.71')
    expect(section('Evaluation scoreboard')).toHaveTextContent('jev-1.13.0')
    expect(section('Evaluation scoreboard')).toHaveTextContent('probability 0.6 or more')
  })

  it('shows the generator comparison with its Control Run and bootstrap intervals', async () => {
    render(<HowItWorks data={EXPORT} />)
    await openSection('Evaluation scoreboard')

    const scoreboard = section('Evaluation scoreboard')
    const answers = within(scoreboard).getByRole('table', { name: /Answers/ })
    expect(within(answers).getByRole('row', { name: /claude-haiku-5-5/ })).not.toHaveTextContent(
      'shipped'
    )

    const table = within(scoreboard).getByRole('table', { name: /Choosing the generator/ })
    const haiku = within(table).getByRole('row', { name: /claude-haiku-5-5/ })
    expect(haiku).toHaveTextContent(
      'behind (5 higher, 35 lower, p ahead = 1.000, p behind = < 0.001)'
    )
    expect(haiku).toHaveTextContent('−0.337 [−0.436, −0.241]') // Fact Recall's interval
    expect(haiku).toHaveTextContent('no')
    const control = within(table).getByRole('row', { name: /Control Run/ })
    expect(control).toHaveTextContent('indistinguishable (11 higher, 10 lower')
    expect(control).toHaveTextContent('−0.005 [−0.058, +0.039]')
    expect(scoreboard).toHaveTextContent('These verdicts are directional')
    expect(scoreboard).toHaveTextContent('Chosen: gpt-6-luna')
    // The comparison predates the measurement fixes that re-scored the shipped run above.
    expect(scoreboard).toHaveTextContent(
      'This comparison was scored on the earlier measurement and stands as recorded'
    )
  })

  it('leaves the generator comparison out when it has not run', async () => {
    render(<HowItWorks data={{ ...EXPORT, generatorChoice: null }} />)
    await openSection('Evaluation scoreboard')

    expect(screen.queryByRole('table', { name: /Choosing the generator/ })).not.toBeInTheDocument()
  })

  it('shows the Arm comparison fact by fact, beside its Control Run', async () => {
    render(<HowItWorks data={EXPORT} />)
    await openSection('Evaluation scoreboard')

    const scoreboard = section('Evaluation scoreboard')
    const table = within(scoreboard).getByRole('table', { name: /Choosing the Arm/ })
    const rerank = within(table).getByRole('row', { name: /rerank/ })
    // Fact by fact: the must-state facts stated, the difference and its one-sided p-values.
    expect(rerank).toHaveTextContent(
      'indistinguishable (+7: 228 against 221 of 316 must-state facts, p ahead = 0.189, p behind = 0.836)'
    )
    expect(rerank).toHaveTextContent('+0.123 [−0.123, +0.368]') // per case, with its interval
    // Case by case, the guardrail, beside it.
    expect(rerank).toHaveTextContent('indistinguishable (15 higher, 10 lower')
    expect(rerank).toHaveTextContent('no')
    // The Control Run's fact-level verdict.
    const control = within(table).getByRole('row', { name: /Control Run/ })
    expect(control).toHaveTextContent('indistinguishable (+1: 222 against 221 of 316')
    expect(scoreboard).toHaveTextContent('one-sided case-cluster bootstrap')
    expect(scoreboard).toHaveTextContent('Chosen: fts5.')
  })

  it('splits the facts each Arm states by where their evidence reached', async () => {
    render(<HowItWorks data={EXPORT} />)
    await openSection('Evaluation scoreboard')

    const table = within(section('Evaluation scoreboard')).getByRole('table', {
      name: /Arm comparison: facts stated by where their evidence reached/,
    })
    const local = within(table).getByRole('row', { name: /hybrid-local/ })
    expect(local).toHaveTextContent('12 / 3 of 20') // reached by the challenger only
    expect(local).toHaveTextContent('187 / 195 of 243') // reached by both
    // The Control Run reaches what the shipped run reaches, so it has no one-sided group.
    const control = within(table).getByRole('row', { name: /Control Run/ })
    expect(control).toHaveTextContent('–201 / 199 of 248')
  })

  it('shows a comparison made before the fact-level test case by case, as recorded', async () => {
    render(<HowItWorks data={EXPORT} />)
    await openSection('Evaluation scoreboard')

    const scoreboard = section('Evaluation scoreboard')
    const table = within(scoreboard).getByRole('table', { name: /Choosing the chunk size/ })
    const setting = within(table).getByRole('row', { name: /chunks-600-budget-48000/ })
    expect(setting).toHaveTextContent('–indistinguishable (12 higher, 9 lower')
    expect(scoreboard).toHaveTextContent(
      'Decided under ADR 0011’s per-case rule, before the fact-level test, and stands as recorded'
    )
    expect(scoreboard).toHaveTextContent('Chosen: chunks-600-budget-32000.')
    expect(
      within(scoreboard).queryByRole('table', { name: /Settings comparison: facts stated/ })
    ).not.toBeInTheDocument()
  })

  it('leaves the Arm and settings comparisons out when they have not run', async () => {
    render(<HowItWorks data={{ ...EXPORT, armChoice: null, settingsChoice: null }} />)
    await openSection('Evaluation scoreboard')

    expect(screen.queryByRole('table', { name: /Choosing the Arm/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('table', { name: /Choosing the chunk size/ })).not.toBeInTheDocument()
  })

  it('shows the Brief Suite’s verdict case by case', async () => {
    render(<HowItWorks data={EXPORT} />)
    await openSection('The Brief Suite')

    const brief = section('The Brief Suite')
    expect(brief).toHaveTextContent('1 of 3 cases pass')
    expect(brief).toHaveTextContent('at least 4 of 5 runs')
    const table = within(brief).getByRole('table', { name: /Brief Suite/ })
    const first = within(table).getByRole('row', { name: /brief-risk-aapl-tsla-jpm/ })
    expect(first).toHaveTextContent('brief')
    expect(first).toHaveTextContent('fail')
    const pharma = within(table).getByRole('row', { name: /brief-sector-pharma-regulatory/ })
    expect(pharma).toHaveTextContent('fail' + '9' + '8' + '8')
    const variant = within(table).getByRole('row', { name: /brief-followup-nvda-net-income/ })
    expect(variant).toHaveTextContent('pass')
    expect(variant).not.toHaveTextContent('brief ')
  })

  it('leaves the Brief Suite out until it has run', () => {
    render(<HowItWorks data={{ ...EXPORT, briefSuite: null }} />)

    expect(screen.queryByRole('region', { name: 'The Brief Suite' })).not.toBeInTheDocument()
  })

  it('shows the holdout run beside dev, with its small-sample caveat', async () => {
    render(<HowItWorks data={EXPORT} />)
    await openSection('The holdout run')

    const holdout = section('The holdout run')
    expect(holdout).toHaveTextContent('one case moves a share by 0.05')
    const retrieval = within(holdout).getByRole('table', { name: /Retrieval/ })
    const fts5 = within(retrieval).getByRole('row', { name: /^fts5/ })
    expect(fts5).toHaveTextContent('0.89') // hit@10
    expect(fts5).toHaveTextContent('261 of 319') // Evidence Reached
    expect(within(retrieval).getByRole('row', { name: /dev, fts5/ })).toHaveTextContent(
      '740 of 939'
    )
    expect(holdout).toHaveTextContent('19 of 20 holdout cases')
    const answers = within(holdout).getByRole('table', { name: /Answers/ })
    const luna = within(answers).getByRole('row', { name: /gpt-6-luna/ })
    expect(luna).toHaveTextContent('0.74') // Fact Recall
    expect(luna).toHaveTextContent('0.95') // Faithfulness
    expect(luna).toHaveTextContent('prompt v7')
    expect(within(answers).getByRole('row', { name: /dev, shipped run/ })).toHaveTextContent('0.72')
    expect(within(answers).getByRole('row', { name: /dev, Control Run/ })).toHaveTextContent('0.71')
  })

  it('leaves the holdout out until it has been scored', () => {
    render(<HowItWorks data={{ ...EXPORT, holdout: null }} />)

    expect(screen.queryByRole('region', { name: 'The holdout run' })).not.toBeInTheDocument()
  })

  it('says how to score answers when the generation harness has not run', async () => {
    render(<HowItWorks data={{ ...EXPORT, generation: [] }} />)
    await openSection('Evaluation scoreboard')

    const scoreboard = section('Evaluation scoreboard')
    expect(scoreboard).toHaveTextContent('make eval-generation')
    expect(within(scoreboard).queryByRole('table', { name: /Answers/ })).not.toBeInTheDocument()
  })

  it('shows the Corpus coverage grid: each Company’s Filings by Report Period', async () => {
    render(<HowItWorks data={EXPORT} />)
    await openSection('Corpus coverage')

    const grid = within(section('Corpus coverage')).getByRole('table')
    expect(within(grid).getByRole('columnheader', { name: /Q3 2025/ })).toBeInTheDocument()
    const apple = within(grid).getByRole('row', { name: /AAPL/ })
    expect(apple).toHaveTextContent('Tracked')
    expect(within(apple).getByTitle(/AAPL_10-K_2025-09-27.*FY2025/)).toHaveTextContent('K')
    expect(within(apple).getByTitle(/AAPL_10-Q_2025-12-27.*Q1 FY2026/)).toHaveTextContent('Q')
    const jpm = within(grid).getByRole('row', { name: /JPM/ })
    expect(jpm).toHaveTextContent('Snapshot')
    expect(
      within(jpm)
        .getAllByRole('cell')
        .filter((c) => c.textContent === '')
    ).toHaveLength(1)
  })

  it('scrolls the coverage grid in its own area, which the keyboard can reach', async () => {
    render(<HowItWorks data={EXPORT} />)
    await openSection('Corpus coverage')

    const area = within(section('Corpus coverage')).getByRole('region', {
      name: 'Filings by Company and Report Period',
    })
    expect(within(area).getByRole('table')).toBeInTheDocument()
    area.focus()
    expect(area).toHaveFocus()
  })

  it('links back to the workspace', () => {
    render(<HowItWorks data={EXPORT} />)

    expect(screen.getByRole('link', { name: /workspace/i })).toHaveAttribute('href', '/')
  })
})

/** Domain terms of `CONTEXT.md` that the plain overview keeps to hover text. */
const JARGON =
  /\b(Filings?|Compan(?:y|ies)|Sources?|Answer Call|Answer Context|Query Scope|Coverage Gaps?|Fact Recall|Faithfulness|Golden Set|Tracked|Snapshot|Arms?|Corpus|dev|holdout|Jev|Control Run|FTS5|bm25)\b/

const OVERVIEW = ['How an answer is made', 'How well it answers', 'Known limits']

describe('the "How it works" overview', () => {
  it('opens with the overview, then "Technical details"', () => {
    render(<HowItWorks data={EXPORT} />)

    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
    expect(headings.slice(0, 5)).toEqual([
      'How an answer is made',
      'What’s covered',
      'How well it answers',
      'Known limits',
      'Technical details',
    ])
  })

  it('explains how an answer is made in three steps', () => {
    render(<HowItWorks data={EXPORT} />)

    const steps = within(section('How an answer is made')).getByRole('list')
    const names = within(steps)
      .getAllByRole('heading', { level: 3 })
      .map((h) => h.textContent)
    expect(names).toEqual([
      'Find the relevant filing passages',
      'One AI call writes the answer',
      'Every claim is cited',
    ])
  })

  it('gives the shipped run’s headline numbers, each with a plain meaning', () => {
    // The Control Run listed first must not be taken for the shipped run.
    const [shipped, control, haiku] = EXPORT.generation
    render(<HowItWorks data={{ ...EXPORT, generation: [control, haiku, shipped] }} />)

    const numbers = section('How well it answers')
    const facts = within(numbers).getByRole('listitem', { name: /key facts/i })
    expect(facts).toHaveTextContent('About 72%') // Fact Recall 0.717
    expect(within(facts).getByTitle('Fact Recall')).toBeInTheDocument()
    const claims = within(numbers).getByRole('listitem', { name: /claims backed/i })
    expect(claims).toHaveTextContent('About 93%') // Faithfulness 0.928
    expect(within(claims).getByTitle('Faithfulness')).toBeInTheDocument()
    const gaps = within(numbers).getByRole('listitem', { name: /missing information/i })
    expect(gaps).toHaveTextContent('100%') // Coverage Gaps stated 1.0
    expect(within(gaps).getByTitle('Coverage Gaps stated')).toBeInTheDocument()
    for (const item of [facts, claims, gaps]) {
      expect(within(item).getByRole('paragraph')).toHaveTextContent(/\w+.*\./)
    }
    expect(numbers).not.toHaveTextContent('71%') // the Control Run's Fact Recall
  })

  it('words the headline numbers as directional, on the questions they were measured on', () => {
    render(<HowItWorks data={EXPORT} />)

    const numbers = section('How well it answers')
    expect(numbers).toHaveTextContent('60 test questions')
    expect(numbers).toHaveTextContent('a rough guide')
    expect(within(numbers).getByRole('link', { name: /full scoreboard/i })).toHaveAttribute(
      'href',
      '#scoreboard'
    )
  })

  it('claims no per-question precision, since the gaps number rests on only some questions', () => {
    render(<HowItWorks data={EXPORT} />)

    const numbers = section('How well it answers')
    // Fact Recall and Faithfulness average every question, but Coverage Gaps stated is a
    // share of only the questions with a Coverage Gap, so no one step size holds for all.
    expect(numbers).not.toHaveTextContent(/points?\b/)
    expect(numbers).toHaveTextContent(
      'The share of missing information flagged is the roughest: it counts only the questions where the filings lack part of the answer, just some of the 60.'
    )
  })

  it('leaves the gaps caveat out when the gaps number is not shown', () => {
    const [shipped, ...rest] = EXPORT.generation
    const noGaps = { ...shipped, overall: { ...shipped.overall, coverageGapsStated: null } }
    render(<HowItWorks data={{ ...EXPORT, generation: [noGaps, ...rest] }} />)

    const numbers = section('How well it answers')
    expect(within(numbers).queryByRole('listitem', { name: /missing information/i })).toBeNull()
    expect(numbers).not.toHaveTextContent('missing information')
    expect(numbers).toHaveTextContent('a rough guide')
  })

  it('leaves the headline numbers out until answers have been scored', () => {
    render(<HowItWorks data={{ ...EXPORT, generation: [] }} />)

    expect(screen.queryByRole('region', { name: 'How well it answers' })).not.toBeInTheDocument()
    expect(section('Known limits')).toBeInTheDocument()
  })

  it('states the known limits plainly', () => {
    render(<HowItWorks data={EXPORT} />)

    const limits = within(section('Known limits')).getAllByRole('listitem')
    expect(limits).toHaveLength(4)
    const text = limits.map((li) => li.textContent).join(' ')
    expect(text).toMatch(/only from the filings/i)
    expect(text).toMatch(/guidance/i)
    expect(text).toMatch(/only a few filings/i)
    expect(text).toMatch(/one AI call/i)
  })

  it('keeps domain terms out of the overview’s text', () => {
    render(<HowItWorks data={EXPORT} />)

    for (const name of OVERVIEW) {
      expect(section(name).textContent).not.toMatch(JARGON)
    }
  })

  it('leaves the Brief Suite out of the overview', () => {
    render(<HowItWorks data={EXPORT} />)

    for (const name of [...OVERVIEW, 'What’s covered']) {
      expect(section(name).textContent).not.toMatch(/brief suite/i)
    }
  })
})

describe('the "How it works" technical details', () => {
  it('puts every technical section under "Technical details", each collapsed by default', () => {
    render(<HowItWorks data={EXPORT} />)

    expect(screen.getByRole('heading', { name: 'Technical details' })).toBeInTheDocument()
    for (const name of TECHNICAL_SECTIONS) {
      const region = section(name)
      expect(within(region).getByRole('button', { name })).toHaveAttribute('aria-expanded', 'false')
      expect(within(region).queryByRole('table')).not.toBeInTheDocument()
    }
    expect(within(section('Architecture')).queryByRole('heading', { name: 'Answer Call' })).toBe(
      null
    )
  })

  it('opens a section on clicking its heading, and closes it on clicking again', async () => {
    const user = userEvent.setup()
    render(<HowItWorks data={EXPORT} />)

    const heading = within(section('Corpus coverage')).getByRole('button', {
      name: 'Corpus coverage',
    })
    await user.click(heading)
    expect(heading).toHaveAttribute('aria-expanded', 'true')
    expect(within(section('Corpus coverage')).getByRole('table')).toBeVisible()
    // The other sections stay closed.
    expect(within(section('Evaluation scoreboard')).queryByRole('table')).not.toBeInTheDocument()

    await user.click(heading)
    expect(heading).toHaveAttribute('aria-expanded', 'false')
    expect(within(section('Corpus coverage')).queryByRole('table')).not.toBeInTheDocument()
  })

  it('opens every section with "Expand all" and closes them with "Collapse all"', async () => {
    const user = userEvent.setup()
    render(<HowItWorks data={EXPORT} />)

    await user.click(screen.getByRole('button', { name: 'Expand all' }))
    for (const name of TECHNICAL_SECTIONS) {
      expect(within(section(name)).getByRole('button', { name })).toHaveAttribute(
        'aria-expanded',
        'true'
      )
    }
    expect(within(section('The holdout run')).getAllByRole('table')).not.toHaveLength(0)

    await user.click(screen.getByRole('button', { name: 'Collapse all' }))
    for (const name of TECHNICAL_SECTIONS) {
      expect(within(section(name)).getByRole('button', { name })).toHaveAttribute(
        'aria-expanded',
        'false'
      )
    }
    expect(screen.getByRole('button', { name: 'Expand all' })).toBeInTheDocument()
  })

  it('opens the section a URL fragment names, on load and when the fragment changes', async () => {
    window.history.replaceState(null, '', '/how-it-works#scoreboard')
    render(<HowItWorks data={EXPORT} />)

    expect(
      within(section('Evaluation scoreboard')).getByRole('table', { name: /Retrieval/ })
    ).toBeVisible()
    expect(within(section('Corpus coverage')).queryByRole('table')).not.toBeInTheDocument()

    act(() => {
      window.history.replaceState(null, '', '/how-it-works#coverage')
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(within(section('Corpus coverage')).getByRole('table')).toBeVisible()
    // Following a link opens its section without closing the one already open.
    expect(
      within(section('Evaluation scoreboard')).getByRole('table', { name: /Retrieval/ })
    ).toBeVisible()
  })

  it('brings the section a fragment names into view once it is open', async () => {
    // With every section collapsed the page can be too short for the browser to reach a
    // late section's heading, so the page scrolls to it after opening it.
    const original = HTMLElement.prototype.scrollIntoView
    const scrolled: Element[] = []
    HTMLElement.prototype.scrollIntoView = function (this: HTMLElement) {
      scrolled.push(this)
    }
    try {
      window.history.replaceState(null, '', '/how-it-works#coverage')
      render(<HowItWorks data={EXPORT} />)

      await waitFor(() =>
        expect(scrolled).toContain(screen.getByRole('heading', { name: 'Corpus coverage' }))
      )
    } finally {
      HTMLElement.prototype.scrollIntoView = original
    }
  })
})

/** Types a search into "What's covered", replacing what was there, and returns the section. */
async function searchCovered(query: string) {
  const covered = section('What’s covered')
  const box = within(covered).getByRole('searchbox', { name: /search companies/i })
  const user = userEvent.setup()
  await user.clear(box)
  await user.type(box, query)
  return covered
}

describe('the "How it works" "What’s covered"', () => {
  it('opens with the summary line, at the anchor the workspace links to', () => {
    render(<HowItWorks data={EXPORT} />)

    const covered = section('What’s covered')
    expect(covered).toHaveAttribute('id', 'whats-covered')
    expect(covered).toHaveTextContent(
      '4 companies · 3 with two or more years of quarterly filings · 1 with a few filings'
    )
  })

  it.each([
    ['NVDA', 'NVIDIA Corporation'],
    ['nvidia', 'NVIDIA Corporation'],
    ['Google', 'Alphabet Inc'],
    ['jp morgan', 'JPMorgan Chase & Co'],
  ])('opens the right card on searching “%s”', async (query, company) => {
    render(<HowItWorks data={EXPORT} />)

    const covered = await searchCovered(query)

    const cards = within(covered).getAllByRole('article')
    expect(cards).toHaveLength(1)
    expect(cards[0]).toHaveAccessibleName(
      new RegExp(company.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    )
  })

  it('shows the card’s Sector, coverage badge and the shared Company Calendar', async () => {
    render(<HowItWorks data={EXPORT} />)

    const card = within(await searchCovered('NVDA')).getByRole('article')
    expect(card).toHaveTextContent('Information Technology')
    expect(within(card).getByText('Two or more years')).toHaveAttribute('title', 'Tracked Company')
    // The Company Calendar the workspace's Calendar tab shows.
    const calendar = within(card).getByRole('table', { name: 'NVDA fiscal calendar' })
    expect(within(calendar).getByRole('rowheader', { name: 'Q3 FY2026' })).toBeInTheDocument()
    expect(card).toHaveTextContent('Fiscal year ends late January')

    const snapshot = within(await searchCovered('JPM')).getByRole('article')
    expect(within(snapshot).getByText('A few filings')).toHaveAttribute('title', 'Snapshot Company')
  })

  it('asks about the Company in the workspace, filling the question in without sending it', async () => {
    render(<HowItWorks data={EXPORT} />)

    const card = within(await searchCovered('Google')).getByRole('article')
    const ask = within(card).getByRole('link', { name: 'Ask about this company' })
    expect(ask).toHaveAttribute(
      'href',
      `/?ask=${encodeURIComponent("What are Alphabet's main risk factors?")}`
    )
  })

  it('says plainly that a Company missing from the Corpus isn’t in the filings', async () => {
    render(<HowItWorks data={EXPORT} />)

    const covered = await searchCovered('Wells Fargo')

    expect(within(covered).queryByRole('article')).not.toBeInTheDocument()
    expect(within(covered).getByRole('status')).toHaveTextContent(
      'Wells Fargo isn’t in the filings'
    )
    // Its aliases and ticker find it too.
    expect(within(await searchCovered('Citi')).getByRole('status')).toHaveTextContent(
      'Citigroup isn’t in the filings'
    )
  })

  it('shows no match for a nonsense query', async () => {
    render(<HowItWorks data={EXPORT} />)

    const covered = await searchCovered('zzqx')

    expect(within(covered).queryByRole('article')).not.toBeInTheDocument()
    expect(within(covered).getByRole('status')).toHaveTextContent('No company matches “zzqx”')
  })

  it('lists the other Companies a search matches, each opening its card', async () => {
    render(<HowItWorks data={EXPORT} />)

    // "a" starts Alphabet and Apple, which tie, so the first alphabetically opens.
    const covered = await searchCovered('a')
    expect(within(covered).getByRole('article')).toHaveAccessibleName(/Alphabet/)
    const others = within(covered).getByRole('list', { name: 'Also matching' })

    await userEvent.setup().click(within(others).getByRole('button', { name: 'Apple Inc (AAPL)' }))

    expect(within(covered).getByRole('article')).toHaveAccessibleName(/Apple/)
  })

  it('shows all companies grouped by coverage, each row opening its card', async () => {
    render(<HowItWorks data={EXPORT} />)
    const user = userEvent.setup()
    const covered = section('What’s covered')
    expect(within(covered).queryByRole('list', { name: /two or more years/i })).toBeNull()

    await user.click(within(covered).getByRole('button', { name: 'Show all companies' }))

    const tracked = within(covered).getByRole('list', { name: /two or more years/i })
    expect(
      within(tracked)
        .getAllByRole('button')
        .map((b) => b.textContent)
    ).toEqual(['Alphabet Inc (GOOG)', 'Apple Inc (AAPL)', 'NVIDIA Corporation (NVDA)'])
    const snapshot = within(covered).getByRole('list', { name: /a few filings/i })
    expect(
      within(snapshot)
        .getAllByRole('button')
        .map((b) => b.textContent)
    ).toEqual(['JPMorgan Chase & Co (JPM)'])
    // Plain words, the domain terms on hover.
    expect(within(covered).getByTitle('Tracked Companies')).toBeInTheDocument()
    expect(within(covered).getByTitle('Snapshot Companies')).toBeInTheDocument()

    await user.click(within(snapshot).getByRole('button', { name: /JPM/ }))
    expect(within(covered).getByRole('article')).toHaveAccessibleName(/JPMorgan Chase/)
  })

  it('filters all companies by Sector', async () => {
    render(<HowItWorks data={EXPORT} />)
    const user = userEvent.setup()
    const covered = section('What’s covered')
    await user.click(within(covered).getByRole('button', { name: 'Show all companies' }))

    await user.selectOptions(
      within(covered).getByRole('combobox', { name: 'Sector' }),
      'Information Technology'
    )

    const tracked = within(covered).getByRole('list', { name: /two or more years/i })
    expect(
      within(tracked)
        .getAllByRole('button')
        .map((b) => b.textContent)
    ).toEqual(['Apple Inc (AAPL)', 'NVIDIA Corporation (NVDA)'])
    expect(within(covered).queryByRole('list', { name: /a few filings/i })).toBeNull()
  })
})

describe('the workspace', () => {
  it('links to the "How it works" page', () => {
    render(<Workspace />)

    expect(screen.getByRole('link', { name: 'How it works' })).toHaveAttribute(
      'href',
      '/how-it-works'
    )
  })

  it('says on the empty screen how many Companies are covered, linking to the list', () => {
    render(<Workspace coverage={coverageSummary(EXPORT.coverage)} />)

    const line = screen.getByText(/companies covered/)
    expect(line).toHaveTextContent(
      '2 companies covered · 1 with two or more years of quarterly filings'
    )
    expect(within(line).getByRole('link')).toHaveAttribute('href', '/how-it-works#whats-covered')
  })

  it('fills in the question “Ask about this company” links with, without sending it', () => {
    window.history.replaceState(
      null,
      '',
      `/?ask=${encodeURIComponent("What are Alphabet's main risk factors?")}`
    )

    render(<Workspace />)

    expect(screen.getByRole('textbox', { name: 'Question' })).toHaveValue(
      "What are Alphabet's main risk factors?"
    )
    // Nothing was sent: the empty screen's starter prompts still show.
    expect(screen.getByRole('list', { name: 'Starter prompts' })).toBeInTheDocument()
    // The question leaves the address, so a refresh doesn't fill it in again.
    expect(window.location.search).toBe('')
  })

  it('shows no coverage line without the coverage summary', () => {
    render(<Workspace />)

    expect(screen.queryByText(/companies covered/)).not.toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Starter prompts' })).toBeInTheDocument()
  })
})
