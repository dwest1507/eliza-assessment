import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import HowItWorks from '@/components/HowItWorks'
import Workspace from '@/components/Workspace'
import type { EvalExport } from '@/lib/evalExport'
import fixture from './fixtures/eval-export.json'

const EXPORT: EvalExport = fixture

function section(name: string) {
  return screen.getByRole('region', { name })
}

describe('the "How it works" page', () => {
  it('shows the architecture, from the question to one Answer Call', () => {
    render(<HowItWorks data={EXPORT} />)

    const architecture = section('Architecture')
    for (const stage of ['Query Scope', 'Retrieval', 'Answer Context', 'Answer Call']) {
      expect(within(architecture).getByRole('heading', { name: stage })).toBeInTheDocument()
    }
    // The live choices come from the export: the Shipped Arm, the generator and its prompt.
    expect(architecture).toHaveTextContent('fts5')
    expect(architecture).toHaveTextContent('gpt-6-luna')
    expect(architecture).toHaveTextContent('prompt v2')
  })

  it('shows each retrieval Arm on the scoreboard, with its comparison to the Shipped Arm', () => {
    render(<HowItWorks data={EXPORT} />)

    const table = within(section('Evaluation scoreboard')).getByRole('table', {
      name: /Retrieval/,
    })
    const shipped = within(table).getByRole('row', { name: /fts5/ })
    expect(shipped).toHaveTextContent('shipped')
    expect(shipped).toHaveTextContent('0.71') // hit@10, the gating metric
    expect(shipped).toHaveTextContent('0.59') // MRR
    const dense = within(table).getByRole('row', { name: /dense/ })
    expect(dense).toHaveTextContent('indistinguishable')
    expect(section('Evaluation scoreboard')).toHaveTextContent('17 of 20 dev cases')
  })

  it('shows each generator on the scoreboard with its scores, cost and latency', () => {
    render(<HowItWorks data={EXPORT} />)

    const table = within(section('Evaluation scoreboard')).getByRole('table', {
      name: /Answers/,
    })
    const luna = within(table).getByRole('row', { name: /gpt-6-luna/ })
    expect(luna).toHaveTextContent('0.55') // Fact Recall
    expect(luna).toHaveTextContent('0.93') // Faithfulness
    expect(luna).toHaveTextContent('$0.0026')
    expect(luna).toHaveTextContent('6.1 s')
    expect(section('Evaluation scoreboard')).toHaveTextContent('jev-1.13.0')
  })

  it('says how to score answers when the generation harness has not run', () => {
    render(<HowItWorks data={{ ...EXPORT, generation: [] }} />)

    expect(section('Evaluation scoreboard')).toHaveTextContent('make eval-generation')
    expect(screen.queryByRole('table', { name: /Answers/ })).not.toBeInTheDocument()
  })

  it('shows the Corpus coverage grid: each Company’s Filings by Report Period', () => {
    render(<HowItWorks data={EXPORT} />)

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

  it('links back to the workspace', () => {
    render(<HowItWorks data={EXPORT} />)

    expect(screen.getByRole('link', { name: /workspace/i })).toHaveAttribute('href', '/')
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
})
