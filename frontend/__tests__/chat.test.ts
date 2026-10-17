import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  HISTORY_TURNS,
  MAX_MESSAGES,
  messageCitedFilings,
  messageDataPart,
  messageSources,
  messageText,
  promptMessages,
  rejectionReason,
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

describe('the turn limit', () => {
  it("is the prompt's history limit, read from the backend, plus the question", () => {
    const prompt = readFileSync(join(__dirname, '../../backend/src/edgar_rag/_prompt.py'), 'utf-8')
    const match = prompt.match(/^HISTORY_TURNS = (\d+)$/m)

    expect(match).not.toBeNull()
    expect(HISTORY_TURNS).toBe(Number(match![1]))
    expect(MAX_MESSAGES).toBe(HISTORY_TURNS + 1)
  })
})

describe('promptMessages', () => {
  const conversation = (count: number) => Array.from({ length: count }, (_, i) => ({ id: i }))

  it('keeps a conversation the prompt can use whole', () => {
    expect(promptMessages(conversation(MAX_MESSAGES))).toEqual(conversation(MAX_MESSAGES))
  })

  it('drops the oldest messages beyond the turns the prompt uses', () => {
    const sent = promptMessages(conversation(MAX_MESSAGES + 3))

    expect(sent).toHaveLength(MAX_MESSAGES)
    expect(sent[0]).toEqual({ id: 3 })
    expect(sent.at(-1)).toEqual({ id: MAX_MESSAGES + 2 })
  })
})

describe('rejectionReason', () => {
  const rejected = (statusCode: number, responseBody: string) =>
    Object.assign(new Error(responseBody), { statusCode, responseBody })

  it("is the API's reason when it rejects a request", () => {
    const error = rejected(400, JSON.stringify({ detail: 'The question is empty.' }))

    expect(rejectionReason(error)).toBe('The question is empty.')
  })

  it.each([
    ['a server failure', rejected(502, 'backend exploded')],
    ['a server failure with a reason', rejected(503, JSON.stringify({ detail: 'down' }))],
    ['a body that is not JSON', rejected(400, 'Bad Request')],
    ['a reason that is not text', rejected(422, JSON.stringify({ detail: [{ msg: 'x' }] }))],
    ['an error without a status', new Error('network down')],
    ['no error', undefined],
  ])('is null for %s', (_, error) => {
    expect(rejectionReason(error)).toBeNull()
  })
})
