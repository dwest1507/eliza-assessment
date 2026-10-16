import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { STARTERS } from '@/lib/starters'

interface GoldenCase {
  id: string
  question: string
  history: unknown[]
  starter: { order: number; label: string } | null
}

const goldenSet: { cases: GoldenCase[] } = JSON.parse(
  readFileSync(join(__dirname, '../../data/eval/golden_set.json'), 'utf-8')
)

describe('starter prompts', () => {
  it('are exactly the Golden Set starters, in their order, so every demo prompt is measured', () => {
    const expected = goldenSet.cases
      .filter((c) => c.starter !== null)
      .sort((a, b) => a.starter!.order - b.starter!.order)
      .map((c) => ({ caseId: c.id, label: c.starter!.label, question: c.question }))

    expect(STARTERS).toEqual(expected)
  })

  it('are single-turn questions, so each can open a conversation', () => {
    const byId = new Map(goldenSet.cases.map((c) => [c.id, c]))
    for (const starter of STARTERS) {
      expect(byId.get(starter.caseId)?.history).toEqual([])
    }
  })
})
