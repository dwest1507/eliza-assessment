import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import HowItWorks from '@/components/HowItWorks'
import Workspace from '@/components/Workspace'
import { coverageSummary } from '@/lib/coverage'
import type { EvalExport } from '@/lib/evalExport'
import fixture from './fixtures/eval-export.json'

const EXPORT: EvalExport = fixture

const TECHNICAL_SECTIONS = ['Architecture', 'Evaluation scoreboard', 'The holdout run']

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

  it('marks in the retrieval table which challengers went on to paid answer runs, with no separate screen table', async () => {
    render(<HowItWorks data={EXPORT} />)
    await openSection('Evaluation scoreboard')

    const scoreboard = section('Evaluation scoreboard')
    expect(within(scoreboard).queryByRole('table', { name: /The screen/ })).not.toBeInTheDocument()
    const table = within(scoreboard).getByRole('table', { name: /Retrieval/ })
    expect(within(table).getByRole('columnheader', { name: 'Paid run' })).toBeInTheDocument()
    expect(within(table).getByRole('row', { name: /^hybrid/ })).toHaveTextContent(
      'no: needs a second API call'
    )
    expect(within(table).getByRole('row', { name: /dense-local/ })).toHaveTextContent('no: behind')
    expect(within(table).getByRole('row', { name: /rerank/ })).toHaveTextContent(/yes$/)
    expect(scoreboard).toHaveTextContent('Went on to paid answer runs: hybrid-local, rerank.')
    expect(scoreboard).toHaveTextContent('fts5 still ships')
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
    // The export holds the latest round's comparison only, so no note dates it.
    expect(scoreboard).not.toHaveTextContent('stands as recorded')
  })

  it('leaves the generator comparison out when it has not run', async () => {
    render(<HowItWorks data={{ ...EXPORT, generatorChoice: null }} />)
    await openSection('Evaluation scoreboard')

    expect(screen.queryByRole('table', { name: /Choosing the generator/ })).not.toBeInTheDocument()
  })

  it('shows no Arm or settings comparison, only the latest scoreboard', async () => {
    render(<HowItWorks data={EXPORT} />)
    await openSection('Evaluation scoreboard')

    const scoreboard = section('Evaluation scoreboard')
    expect(within(scoreboard).queryByRole('table', { name: /Choosing the Arm/ })).toBeNull()
    expect(within(scoreboard).queryByRole('table', { name: /Choosing the chunk size/ })).toBeNull()
    expect(within(scoreboard).queryByRole('table', { name: /facts stated by where/ })).toBeNull()
  })

  it('shows the latest holdout run beside dev, with its small-sample caveat', async () => {
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
    // Only the latest holdout run: one row of answers, beside dev's.
    const [luna] = within(answers).getAllByRole('row', { name: /gpt-6-luna/ })
    expect(within(answers).getAllByRole('row', { name: /gpt-6-luna/ })).toHaveLength(1)
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

  it('gives the holdout run’s headline numbers, each with a plain meaning', () => {
    render(<HowItWorks data={EXPORT} />)

    const numbers = section('How well it answers')
    const facts = within(numbers).getByRole('listitem', { name: /key facts/i })
    expect(facts).toHaveTextContent('About 74%') // the holdout's Fact Recall 0.741
    expect(within(facts).getByTitle('Fact Recall')).toBeInTheDocument()
    const claims = within(numbers).getByRole('listitem', { name: /claims backed/i })
    expect(claims).toHaveTextContent('About 95%') // the holdout's Faithfulness 0.952
    expect(within(claims).getByTitle('Faithfulness')).toBeInTheDocument()
    for (const item of [facts, claims]) {
      expect(within(item).getByRole('paragraph')).toHaveTextContent(/\w+.*\./)
    }
    // The shipped run on dev, which "Technical details" shows, stays out of the headline.
    expect(numbers).not.toHaveTextContent('72%')
    expect(numbers).not.toHaveTextContent('93%')
  })

  it('says what’s missing in words, with no rate, since few questions turn on it', () => {
    render(<HowItWorks data={EXPORT} />)

    const numbers = section('How well it answers')
    const gaps = within(numbers).getByRole('listitem', { name: /information is missing/i })
    expect(within(gaps).getByTitle('Coverage Gaps')).toBeInTheDocument()
    expect(gaps).toHaveTextContent('the answer says so instead of filling it in')
    expect(gaps).not.toHaveTextContent('%')
  })

  it('words the headline numbers as directional, on the questions kept apart', () => {
    render(<HowItWorks data={EXPORT} />)

    const numbers = section('How well it answers')
    expect(numbers).toHaveTextContent('20 test questions kept apart until the end')
    expect(numbers).toHaveTextContent('a rough guide')
    expect(numbers).not.toHaveTextContent(/points?\b/)
    expect(within(numbers).getByRole('link', { name: /full results/i })).toHaveAttribute(
      'href',
      '#holdout'
    )
  })

  it('gives the shipped run’s numbers on dev when there is no holdout run', () => {
    // The Control Run listed first must not be taken for the shipped run.
    const [shipped, control, haiku] = EXPORT.generation
    render(
      <HowItWorks data={{ ...EXPORT, generation: [control, haiku, shipped], holdout: null }} />
    )

    const numbers = section('How well it answers')
    expect(within(numbers).getByRole('listitem', { name: /key facts/i })).toHaveTextContent(
      'About 72%' // Fact Recall 0.717
    )
    expect(within(numbers).getByRole('listitem', { name: /claims backed/i })).toHaveTextContent(
      'About 93%' // Faithfulness 0.928
    )
    expect(numbers).not.toHaveTextContent('71%') // the Control Run's Fact Recall
    expect(numbers).toHaveTextContent('60 test questions written in advance')
    expect(within(numbers).getByRole('link', { name: /full scoreboard/i })).toHaveAttribute(
      'href',
      '#scoreboard'
    )
  })

  it('leaves the headline numbers out until answers have been scored', () => {
    render(<HowItWorks data={{ ...EXPORT, generation: [], holdout: null }} />)

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

  it('leaves the human check of the grading out of the known limits', () => {
    render(<HowItWorks data={EXPORT} />)

    expect(section('Known limits')).not.toHaveTextContent(/checked by a person/i)
    expect(section('Known limits')).not.toHaveTextContent(/a person checked/i)
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
  it('shows exactly the architecture, the evaluation scoreboard and the holdout run', () => {
    render(<HowItWorks data={EXPORT} />)

    // Each section's heading is its toggle, after a hidden ▸.
    const headings = screen
      .getAllByRole('heading', { level: 2 })
      .map((h) => h.textContent?.replace('▸', ''))
    expect(headings.slice(headings.indexOf('Technical details') + 1)).toEqual(TECHNICAL_SECTIONS)
    expect(screen.queryByRole('region', { name: 'The Brief Suite' })).toBeNull()
    expect(screen.queryByRole('region', { name: 'Corpus coverage' })).toBeNull()
    expect(document.body).not.toHaveTextContent(/brief suite/i)
  })

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

    const heading = within(section('The holdout run')).getByRole('button', {
      name: 'The holdout run',
    })
    await user.click(heading)
    expect(heading).toHaveAttribute('aria-expanded', 'true')
    expect(within(section('The holdout run')).getAllByRole('table')[0]).toBeVisible()
    // The other sections stay closed.
    expect(within(section('Evaluation scoreboard')).queryByRole('table')).not.toBeInTheDocument()

    await user.click(heading)
    expect(heading).toHaveAttribute('aria-expanded', 'false')
    expect(within(section('The holdout run')).queryByRole('table')).not.toBeInTheDocument()
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
    expect(within(section('The holdout run')).queryByRole('table')).not.toBeInTheDocument()

    act(() => {
      window.history.replaceState(null, '', '/how-it-works#holdout')
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(within(section('The holdout run')).getAllByRole('table')[0]).toBeVisible()
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
      window.history.replaceState(null, '', '/how-it-works#holdout')
      render(<HowItWorks data={EXPORT} />)

      await waitFor(() =>
        expect(scrolled).toContain(screen.getByRole('heading', { name: 'The holdout run' }))
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
    render(<Workspace coverage={coverageSummary(EXPORT.companies)} />)

    const line = screen.getByText(/companies covered/)
    expect(line).toHaveTextContent(
      '4 companies covered · 3 with two or more years of quarterly filings'
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
