import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  citedSources,
  HISTORY_TURNS,
  MAX_MESSAGES,
  messageCitedFilings,
  messageDataPart,
  messageSources,
  messageText,
  promptMessages,
  rejectionReason,
  splitAnswer,
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

  it('skips a tag that is not a Source tag, so the history cannot set an object key', () => {
    const message = {
      parts: [
        {
          type: 'data-sources',
          data: {
            sources: [
              { tag: '__proto__', filingId: 'AAPL_10-K_2025-09-27' },
              { tag: 'constructor', filingId: 'AAPL_10-K_2025-09-27' },
              { tag: 'S1 ', filingId: 'AAPL_10-K_2025-09-27' },
              { tag: 'S2', filingId: 'TSLA_10-K_2025-12-31' },
            ],
          },
        },
      ],
    }
    const cited = messageCitedFilings(message)
    expect(cited).toEqual({ S2: 'TSLA_10-K_2025-12-31' })
    expect(Object.getPrototypeOf(cited)).toBe(Object.prototype)
  })
})

describe('citedSources', () => {
  /** The Sources an answer was given, S1 to S11, each as a minimal Source. */
  const given: Source[] = Array.from({ length: 11 }, (_, i) => ({
    ...appleSource,
    tag: `S${i + 1}`,
  }))
  const tags = (sources: Source[]) => sources.map((s) => s.tag)

  it('lists the Sources the answer cites, in tag order, not citation order', () => {
    expect(tags(citedSources('Tesla [S3] and Apple [S1].', given))).toEqual(['S1', 'S3'])
  })

  it('lists a tag cited more than once only once', () => {
    expect(tags(citedSources('Apple [S2] faces tariffs [S2] and [S2].', given))).toEqual(['S2'])
  })

  it('skips a cited tag that is not among the Sources', () => {
    expect(tags(citedSources('Apple [S1] and a made-up [S40].', given))).toEqual(['S1'])
  })

  it('reads a tag run like [S1][S2] and a grouped [S4, S11] as separate citations', () => {
    expect(tags(citedSources('Both [S1][S2], and [S4, S11].', given))).toEqual([
      'S1',
      'S2',
      'S4',
      'S11',
    ])
  })

  it('is empty when the answer cites nothing', () => {
    expect(citedSources('No citations here, nor S1 without brackets.', given)).toEqual([])
    expect(citedSources('', given)).toEqual([])
  })
})

describe('splitAnswer', () => {
  it('splits the opening paragraph from the rest at the first blank line', () => {
    const text =
      'Apple faces tariffs [S1].\nIt says so twice.\n\n**Apple.** Detail [S1].\n\nCoverage: none.'
    expect(splitAnswer(text)).toEqual({
      opening: 'Apple faces tariffs [S1].\nIt says so twice.',
      remainder: '**Apple.** Detail [S1].\n\nCoverage: none.',
    })
  })

  it('reads Windows line breaks and a blank line holding spaces as a paragraph break', () => {
    expect(splitAnswer('Apple faces tariffs.\r\n  \r\nDetail.\r\n')).toEqual({
      opening: 'Apple faces tariffs.',
      remainder: 'Detail.\r\n',
    })
  })

  it('skips blank lines before the opening', () => {
    expect(splitAnswer('\n\nApple faces tariffs.\n\nDetail.')).toEqual({
      opening: 'Apple faces tariffs.',
      remainder: 'Detail.',
    })
  })

  it('has no split when there is no remainder', () => {
    expect(splitAnswer('Apple faces tariffs [S1].')).toBeNull()
    expect(splitAnswer('Apple faces tariffs [S1].\n\n')).toBeNull()
    expect(splitAnswer('Apple faces tariffs [S1].\r\n\r\n  \n')).toBeNull()
    expect(splitAnswer('')).toBeNull()
  })

  it('has no split when the first block is a heading, list item or table row', () => {
    for (const opening of [
      '## Apple',
      '# Answer',
      '- Apple faces tariffs.',
      '* Apple faces tariffs.',
      '+ Apple faces tariffs.',
      '1. Apple faces tariffs.',
      '2) Apple faces tariffs.',
      '| Company | Risk |\n| --- | --- |\n| Apple | Tariffs |',
    ]) {
      expect(splitAnswer(`${opening}\n\nDetail [S1].`)).toBeNull()
    }
  })

  it('splits an opening that only mentions a number or a hash mark', () => {
    expect(splitAnswer('2024 revenue rose; #1 in its market.\n\nDetail.')).toEqual({
      opening: '2024 revenue rose; #1 in its market.',
      remainder: 'Detail.',
    })
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
