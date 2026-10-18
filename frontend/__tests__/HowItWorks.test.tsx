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
  })

  it('leaves the generator comparison out when it has not run', async () => {
    render(<HowItWorks data={{ ...EXPORT, generatorChoice: null }} />)
    await openSection('Evaluation scoreboard')

    expect(screen.queryByRole('table', { name: /Choosing the generator/ })).not.toBeInTheDocument()
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

  it('lists what’s covered, grouped by how much history each Company has', () => {
    render(<HowItWorks data={EXPORT} />)

    const covered = section('What’s covered')
    expect(covered).toHaveAttribute('id', 'whats-covered')
    const tracked = within(covered).getByRole('list', { name: /two or more years/i })
    expect(
      within(tracked)
        .getAllByRole('listitem')
        .map((li) => li.textContent)
    ).toEqual(['Apple Inc. (AAPL)'])
    const snapshot = within(covered).getByRole('list', { name: /only a few filings/i })
    expect(
      within(snapshot)
        .getAllByRole('listitem')
        .map((li) => li.textContent)
    ).toEqual(['JPMorgan Chase & Co. (JPM)'])
    // Plain words by default, the domain terms on hover.
    expect(within(covered).getByTitle('Tracked Companies')).toBeInTheDocument()
    expect(within(covered).getByTitle('Snapshot Companies')).toBeInTheDocument()
  })

  it('lists every Company of the export in what’s covered', () => {
    render(<HowItWorks data={EXPORT} />)

    const covered = section('What’s covered')
    expect(within(covered).getAllByRole('listitem')).toHaveLength(EXPORT.coverage.companies.length)
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

  it('shows no coverage line without the coverage summary', () => {
    render(<Workspace />)

    expect(screen.queryByText(/companies covered/)).not.toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Starter prompts' })).toBeInTheDocument()
  })
})
