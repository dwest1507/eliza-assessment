import { describe, expect, it } from 'vitest'
import type { QueryScope } from '@/lib/chat'
import { followUps } from '@/lib/followUps'

const LATEST = { kind: 'latest', count: null, label: 'latest' }

function scope(overrides: Partial<QueryScope>): QueryScope {
  return {
    companies: [],
    sectorPhrases: [],
    timeWindow: LATEST,
    sections: [],
    metric: null,
    ...overrides,
  }
}

const APPLE = { ticker: 'AAPL', name: 'Apple Inc', coverage: 'tracked' }
const TESLA = { ticker: 'TSLA', name: 'Tesla Inc', coverage: 'tracked' }
const MICROSOFT = { ticker: 'MSFT', name: 'Microsoft Corporation', coverage: 'tracked' }
const JPMORGAN = { ticker: 'JPM', name: 'JPMorgan Chase & Co', coverage: 'snapshot' }

/** A question that asks how something changed, or over a span of periods. */
const TREND = /\bchang(?:ed|ing|es?)\b|\blast\s+\w+\s+(?:years?|quarters?)\b/i

describe('followUps', () => {
  it("suggests one Company's risks, revenue trend and outlook, by its short name", () => {
    expect(followUps(scope({ companies: [APPLE] }), "Summarize Apple's latest 10-K")).toEqual([
      "What are Apple's main risk factors?",
      "How has Apple's revenue changed over the last two years?",
      "What does Apple's latest filing say about its outlook?",
    ])
  })

  it('names a Company without its legal suffix or a leading "The"', () => {
    const disney = { ticker: 'DIS', name: 'The Walt Disney Company', coverage: 'tracked' }
    const amazon = { ticker: 'AMZN', name: 'Amazon.com Inc', coverage: 'tracked' }
    const goldman = { ticker: 'GS', name: 'Goldman Sachs Group Inc', coverage: 'snapshot' }
    expect(followUps(scope({ companies: [disney] }), 'q')[0]).toBe(
      "What are Walt Disney's main risk factors?"
    )
    expect(followUps(scope({ companies: [amazon] }), 'q')[0]).toBe(
      "What are Amazon's main risk factors?"
    )
    expect(followUps(scope({ companies: [goldman] }), 'q')[0]).toBe(
      "What are Goldman Sachs' main risk factors?"
    )
  })

  it('suggests no trend for a Snapshot Company, asking for its latest revenue instead', () => {
    const suggestions = followUps(scope({ companies: [JPMORGAN] }), "What are JPMorgan's risks?")
    expect(suggestions).toEqual([
      "What are JPMorgan Chase's main risk factors?",
      "What was JPMorgan Chase's revenue in its latest filing?",
      "What does JPMorgan Chase's latest filing say about its outlook?",
    ])
    expect(suggestions.filter((s) => TREND.test(s))).toEqual([])
  })

  it('suggests no trend for a Company whose coverage is unknown', () => {
    const unknown = { ...APPLE, coverage: null }
    expect(followUps(scope({ companies: [unknown] }), 'q').filter((s) => TREND.test(s))).toEqual([])
  })

  it('compares several Companies', () => {
    expect(
      followUps(scope({ companies: [APPLE, TESLA] }), "Compare Apple and Tesla's risk factors")
    ).toEqual([
      'How do the main risk factors of Apple and Tesla compare?',
      'How does revenue compare between Apple and Tesla in their latest filings?',
      'How do Apple and Tesla describe their outlook in their latest filings?',
    ])
    const three = followUps(scope({ companies: [APPLE, TESLA, MICROSOFT] }), 'q')
    expect(three.slice(0, 2)).toEqual([
      'How do the main risk factors of Apple, Tesla and Microsoft compare?',
      'How does revenue compare across Apple, Tesla and Microsoft in their latest filings?',
    ])
  })

  it('suggests no trend when comparing a Snapshot Company', () => {
    const suggestions = followUps(scope({ companies: [APPLE, JPMORGAN] }), 'q')
    expect(suggestions).toHaveLength(3)
    expect(suggestions.filter((s) => TREND.test(s))).toEqual([])
  })

  it('asks for the main risks of the group a Sector phrase names', () => {
    const pharma = {
      phrase: 'Pharmaceutical companies',
      column: 'industry' as const,
      values: ['Pharmaceuticals', 'Biotechnology'],
      tickers: ['JNJ', 'PFE'],
    }
    const companies = [
      { ticker: 'JNJ', name: 'Johnson & Johnson', coverage: 'tracked' },
      { ticker: 'PFE', name: 'Pfizer Inc', coverage: 'tracked' },
    ]
    expect(
      followUps(
        scope({ companies, sectorPhrases: [pharma] }),
        'How do pharmaceutical companies describe drug pricing?'
      )
    ).toEqual(['What are the main risk factors for pharmaceutical companies?'])
  })

  it('puts "the" before a Sector phrase naming a sector or industry', () => {
    const energy = {
      phrase: 'energy sector',
      column: 'sector' as const,
      values: ['Energy'],
      tickers: ['XOM'],
    }
    const exxon = { ticker: 'XOM', name: 'Exxon Mobil Corporation', coverage: 'tracked' }
    expect(followUps(scope({ companies: [exxon], sectorPhrases: [energy] }), 'q')).toEqual([
      'What are the main risk factors for the energy sector?',
    ])
  })

  it('follows a Sector phrase with the Companies named outside it', () => {
    const banks = {
      phrase: 'banks',
      column: 'industry' as const,
      values: ['Banks'],
      tickers: ['JPM'],
    }
    expect(followUps(scope({ companies: [JPMORGAN, APPLE], sectorPhrases: [banks] }), 'q')).toEqual(
      [
        'What are the main risk factors for banks?',
        "What are Apple's main risk factors?",
        "How has Apple's revenue changed over the last two years?",
      ]
    )
  })

  it('drops a suggestion equal to the question just asked', () => {
    const asked = '  what are apple’s MAIN   risk factors '
    expect(followUps(scope({ companies: [APPLE] }), asked)).toEqual([
      "How has Apple's revenue changed over the last two years?",
      "What does Apple's latest filing say about its outlook?",
    ])
  })

  it('suggests nothing when the question names no Company or group', () => {
    expect(followUps(scope({}), 'What are the main risks?')).toEqual([])
  })
})
