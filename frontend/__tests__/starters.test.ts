import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { STARTERS } from '@/lib/starters'

interface LabelledCase {
  id: string
  question: string
  history: unknown[]
  starter: { order: number; label: string } | null
  /** A Brief Suite case's Golden Set version 1 case, whose starter it takes over. */
  replaces?: string
}

function cases(file: string): LabelledCase[] {
  const data: { cases: LabelledCase[] } = JSON.parse(
    readFileSync(join(__dirname, '../../data/eval', file), 'utf-8')
  )
  return data.cases
}

const goldenSet = cases('golden_set.json')
const briefSuite = cases('brief_suite.json')

describe('starter prompts', () => {
  it('are exactly the Golden Set and Brief Suite starters, in their order, so every demo prompt is measured', () => {
    // A Brief Suite case takes over the starter of the version 1 case it replaces.
    const replaced = new Set(briefSuite.map((c) => c.replaces))
    const expected = [...goldenSet.filter((c) => !replaced.has(c.id)), ...briefSuite]
      .filter((c) => c.starter !== null)
      .sort((a, b) => a.starter!.order - b.starter!.order)
      .map((c) => ({ caseId: c.id, label: c.starter!.label, question: c.question }))

    expect(STARTERS).toEqual(expected)
  })

  it('point the brief questions at Brief Suite cases', () => {
    const brief = new Set(briefSuite.map((c) => c.id))
    expect(STARTERS.filter((s) => brief.has(s.caseId)).map((s) => s.caseId)).toEqual([
      'brief-risk-aapl-tsla-jpm',
      'brief-outlook-nvda-revenue-two-years',
      'brief-sector-pharma-regulatory',
    ])
  })

  it('are single-turn questions, so each can open a conversation', () => {
    const byId = new Map([...goldenSet, ...briefSuite].map((c) => [c.id, c]))
    for (const starter of STARTERS) {
      expect(byId.get(starter.caseId)?.history).toEqual([])
    }
  })
})
