import { describe, expect, it } from 'vitest'
import {
  messageCitedFilings,
  messageDataPart,
  messageSources,
  messageText,
  type QueryScope,
  type ResearchMessage,
  type Source,
} from '@/lib/chat'

const appleSource: Source = {
  tag: 'S1',
  filingId: 'AAPL_10-K_2025-09-27',
  company: 'Apple Inc.',
  ticker: 'AAPL',
  formType: '10-K',
  reportPeriod: '2025-09-27',
  fiscalPeriod: 'FY2025',
  section: 'Risk Factors',
  item: '1A',
  label: 'AAPL 10-K FY2025, Risk Factors',
  text: 'a long passage',
}

const scope: QueryScope = {
  companies: [{ ticker: 'AAPL', name: 'Apple Inc.', coverage: 'tracked' }],
  sectorPhrases: [],
  timeWindow: { kind: 'latest', count: null, label: 'Latest Filing' },
  sections: ['Risk Factors'],
  metric: null,
}

/** An answer as `useChat` holds it: data parts first, then the streamed text. */
const answer: ResearchMessage = {
  id: 'm2',
  role: 'assistant',
  parts: [
    { type: 'data-query-scope', data: scope },
    { type: 'data-sources', data: { sources: [appleSource] } },
    { type: 'step-start' },
    { type: 'text', text: 'Apple faces ' },
    { type: 'text', text: 'tariffs [S1].' },
  ],
}

const question: ResearchMessage = {
  id: 'm1',
  role: 'user',
  parts: [{ type: 'text', text: 'What are Apple’s risk factors?' }],
}

describe('messageText', () => {
  it('joins a message’s text parts and skips every other part', () => {
    expect(messageText(answer)).toBe('Apple faces tariffs [S1].')
    expect(messageText(question)).toBe('What are Apple’s risk factors?')
  })

  it('reads an untrusted message from the browser without throwing', () => {
    expect(messageText({ parts: undefined })).toBe('')
    expect(messageText({ parts: 'not a list' })).toBe('')
    expect(
      messageText({ parts: [null, { type: 'text', text: 7 }, { type: 'text', text: 'ok' }] })
    ).toBe('ok')
  })
})

describe('messageDataPart', () => {
  it('returns the data of the part of the named type', () => {
    expect(messageDataPart(answer, 'query-scope')).toEqual(scope)
    expect(messageDataPart(answer, 'sources')).toEqual({ sources: [appleSource] })
  })

  it('returns null when the message has no part of that type', () => {
    expect(messageDataPart(answer, 'coverage-gaps')).toBeNull()
    expect(messageDataPart(question, 'sources')).toBeNull()
    expect(messageDataPart({ parts: undefined }, 'sources')).toBeNull()
  })
})

describe('messageSources', () => {
  it('lists the Sources an answer may cite', () => {
    expect(messageSources(answer)).toEqual([appleSource])
  })

  it('is empty for a message without Sources, or with a malformed Sources part', () => {
    expect(messageSources(question)).toEqual([])
    expect(messageSources({ parts: [{ type: 'data-sources', data: null }] })).toEqual([])
    expect(messageSources({ parts: [{ type: 'data-sources', data: { sources: 'S1' } }] })).toEqual(
      []
    )
  })
})

describe('messageCitedFilings', () => {
  it('maps each Source tag of an answer to the Filing it cited', () => {
    expect(messageCitedFilings(answer)).toEqual({ S1: 'AAPL_10-K_2025-09-27' })
  })

  it('is empty for a message without Sources', () => {
    expect(messageCitedFilings(question)).toEqual({})
  })

  it('skips a Source without a string tag and Filing ID', () => {
    const message = {
      parts: [
        {
          type: 'data-sources',
          data: {
            sources: [
              { tag: 'S1', filingId: 'TSLA_10-K_2025-12-31' },
              { tag: 'S2' },
              { tag: 3, filingId: 'NVDA_10-Q_2025-10-26' },
              null,
            ],
          },
        },
      ],
    }
    expect(messageCitedFilings(message)).toEqual({ S1: 'TSLA_10-K_2025-12-31' })
  })
})
