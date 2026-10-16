import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Workspace from '@/components/Workspace'
import { STARTERS } from '@/lib/starters'

/** The parts the chat API streams, in its order: the Query Scope and Sources first. */
const SOURCES = [
  {
    tag: 'S1',
    filingId: 'AAPL_10-K_2025-09-27',
    company: 'Apple Inc.',
    ticker: 'AAPL',
    formType: '10-K',
    reportPeriod: '2025-09-27',
    fiscalPeriod: 'FY2025',
    section: 'Risk Factors',
    item: 'Item 1A',
    label: 'AAPL 10-K FY2025, Risk Factors (Item 1A).',
    text: 'A significant majority of the Company’s manufacturing is performed by outsourcing partners.',
  },
  {
    tag: 'S2',
    filingId: 'TSLA_10-K_2025-12-31',
    company: 'Tesla, Inc.',
    ticker: 'TSLA',
    formType: '10-K',
    reportPeriod: '2025-12-31',
    fiscalPeriod: 'FY2025',
    section: 'Risk Factors',
    item: 'Item 1A',
    label: 'TSLA 10-K FY2025, Risk Factors (Item 1A).',
    text: 'We may be impacted by trade policies, political uncertainty and tariffs.',
  },
]

const ANSWER = [
  'Apple and Tesla both face **trade policy** risk. ',
  'Apple depends on outsourcing partners [S1]; ',
  'Tesla is exposed to tariffs [S2].',
]

const QUERY_SCOPE = {
  companies: [
    { ticker: 'AAPL', name: 'Apple Inc', coverage: 'tracked' },
    { ticker: 'TSLA', name: 'Tesla Inc', coverage: 'tracked' },
  ],
  sectorPhrases: [],
  timeWindow: { kind: 'latest', count: null, label: 'latest' },
  sections: ['Risk Factors'],
  metric: null,
}

/** A Facts Source: the Financial Facts taken from one Filing, sent with its rows. */
const FACTS_SOURCE = {
  tag: 'S1',
  filingId: 'NVDA_10-Q_2025-10-26',
  company: 'NVIDIA CORP',
  ticker: 'NVDA',
  formType: '10-Q',
  reportPeriod: '2025-10-26',
  fiscalPeriod: 'Q3 FY2026',
  section: 'Financial Facts',
  item: null,
  label: 'NVDA 10-Q Q3 FY2026, Financial Facts.',
  text: 'Revenue, 3 months ended 2025-10-26: $57,006 million (reported as "Revenue")',
  kind: 'facts',
  rows: [
    {
      metric: 'revenue',
      metricName: 'Revenue',
      segment: null,
      months: 3,
      reportPeriod: '2025-10-26',
      value: 57006000000,
      valueText: '$57,006 million',
      label: 'Revenue',
    },
    {
      metric: 'segment_revenue',
      metricName: 'Segment revenue: Compute & Networking',
      segment: 'Compute & Networking',
      months: 3,
      reportPeriod: '2025-10-26',
      value: 50908000000,
      valueText: '$50,908 million',
      label: 'Compute & Networking',
    },
  ],
}

function uiMessageStream(
  answer: string[] = ANSWER,
  scope: object = QUERY_SCOPE,
  sources: object[] = SOURCES,
  gaps: object[] = []
): Response {
  const parts = [
    { type: 'start', messageId: 'msg-1' },
    { type: 'data-query-scope', data: scope },
    { type: 'data-sources', data: { sources } },
    { type: 'data-coverage-gaps', data: { gaps } },
    { type: 'start-step' },
    { type: 'text-start', id: 'text-1' },
    ...answer.map((delta) => ({ type: 'text-delta', id: 'text-1', delta })),
    { type: 'text-end', id: 'text-1' },
    { type: 'finish-step' },
    { type: 'finish' },
  ]
  const body = parts.map((p) => `data: ${JSON.stringify(p)}\n\n`).join('') + 'data: [DONE]\n\n'
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(body))
      controller.close()
    },
  })
  return new Response(stream, {
    headers: {
      'content-type': 'text/event-stream',
      'x-vercel-ai-ui-message-stream': 'v1',
    },
  })
}

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockImplementation(async () => uiMessageStream())
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function sentMessages(call = 0): { role: string; parts: { type: string; text?: string }[] }[] {
  const [, init] = fetchMock.mock.calls[call]
  return JSON.parse(init.body).messages
}

describe('Workspace', () => {
  it('shows the six starter prompts on an empty conversation', () => {
    render(<Workspace />)

    const starters = within(screen.getByRole('list', { name: 'Starter prompts' }))
    const buttons = starters.getAllByRole('button')
    expect(buttons.map((b) => b.textContent)).toEqual(STARTERS.map((s) => s.label))
    expect(buttons).toHaveLength(6)
  })

  it('sends a starter as soon as it is clicked and streams the answer as Markdown', async () => {
    const user = userEvent.setup()
    render(<Workspace />)

    const starter = STARTERS[0]
    await user.click(screen.getByRole('button', { name: starter.label }))

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/chat')
    const messages = sentMessages()
    expect(messages.at(-1)).toMatchObject({
      role: 'user',
      parts: [{ type: 'text', text: starter.question }],
    })

    expect(await screen.findByText('trade policy')).toContainHTML('trade policy')
    expect(screen.getByText('trade policy').tagName).toBe('STRONG')
    expect(screen.getByText(starter.question)).toBeInTheDocument()
    // The starters give way to the conversation.
    expect(screen.queryByRole('list', { name: 'Starter prompts' })).not.toBeInTheDocument()
  })

  it('sends a typed question', async () => {
    const user = userEvent.setup()
    render(<Workspace />)

    await user.type(
      screen.getByRole('textbox', { name: 'Question' }),
      'Compare Apple and Tesla{Enter}'
    )

    await screen.findByText('trade policy')
    expect(sentMessages().at(-1)?.parts).toEqual([
      { type: 'text', text: 'Compare Apple and Tesla' },
    ])
  })

  it('opens the Sources panel at the Source a citation names', async () => {
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('trade policy')

    expect(screen.queryByRole('complementary', { name: 'Sources' })).not.toBeInTheDocument()

    const answer = screen.getByRole('article', { name: 'Answer' })
    await user.click(within(answer).getByRole('link', { name: 'Source S2' }))

    const panel = await screen.findByRole('complementary', { name: 'Sources' })
    const source = within(panel).getByRole('region', { name: /^S2/ })
    const field = (name: string) => within(source).getByText(name).nextElementSibling?.textContent
    expect(field('Filing ID')).toBe('TSLA_10-K_2025-12-31')
    expect(field('Form Type')).toBe('10-K')
    expect(field('Report Period')).toBe('2025-12-31')
    expect(field('Fiscal Period')).toBe('FY2025')
    expect(field('Section')).toBe('Risk Factors')
    expect(field('Item')).toBe('Item 1A')
    expect(
      within(source).getByText(
        'We may be impacted by trade policies, political uncertainty and tariffs.'
      )
    ).toBeInTheDocument()
  })

  it('switches the panel to another Source when a second citation is clicked', async () => {
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('trade policy')

    const answer = screen.getByRole('article', { name: 'Answer' })
    await user.click(within(answer).getByRole('link', { name: 'Source S2' }))
    await user.click(within(answer).getByRole('link', { name: 'Source S1' }))

    const panel = screen.getByRole('complementary', { name: 'Sources' })
    expect(within(panel).getByRole('region', { name: /^S1/ })).toHaveTextContent(
      'AAPL_10-K_2025-09-27'
    )
    expect(within(panel).queryByRole('region', { name: /^S2/ })).not.toBeInTheDocument()

    await user.click(within(panel).getByRole('button', { name: 'Close Sources' }))
    expect(screen.queryByRole('complementary', { name: 'Sources' })).not.toBeInTheDocument()
  })

  it('sends only the conversation text back to the API on a follow-up', async () => {
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('trade policy')

    await user.type(screen.getByRole('textbox', { name: 'Question' }), 'And Microsoft?{Enter}')
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))

    const roles = sentMessages(1).map((m) => m.role)
    expect(roles).toEqual(['user', 'assistant', 'user'])
  })

  it('shows the Query Scope as chips above the answer', async () => {
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('trade policy')

    const answer = screen.getByRole('article', { name: 'Answer' })
    const chips = within(answer).getByRole('list', { name: 'Query Scope' })
    expect(
      within(chips)
        .getAllByRole('listitem')
        .map((chip) => chip.textContent)
    ).toEqual(['AAPL', 'TSLA', 'latest', 'Risk Factors'])
    expect(within(chips).getByText('AAPL').closest('li')).toHaveAttribute(
      'title',
      'Company: Apple Inc (tracked)'
    )
    // The chips come before the answer text.
    const text = within(answer).getByText('trade policy')
    expect(chips.compareDocumentPosition(text) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('shows a Sector phrase with the Companies it resolved to, and the metric', async () => {
    fetchMock.mockImplementation(async () =>
      uiMessageStream(ANSWER, {
        companies: [
          { ticker: 'BAC', name: 'Bank of America Corporation', coverage: 'tracked' },
          { ticker: 'JPM', name: 'JPMorgan Chase & Co', coverage: 'snapshot' },
        ],
        sectorPhrases: [
          { phrase: 'banks', column: 'industry', values: ['Banks'], tickers: ['BAC', 'JPM'] },
        ],
        timeWindow: { kind: 'years', count: 2, label: 'last 2 years' },
        sections: [],
        metric: 'net_income',
      })
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await user.type(
      screen.getByRole('textbox', { name: 'Question' }),
      'How has net income changed at the major banks over the last two years?{Enter}'
    )
    await screen.findByText('trade policy')

    const chips = within(screen.getByRole('article', { name: 'Answer' })).getByRole('list', {
      name: 'Query Scope',
    })
    expect(
      within(chips)
        .getAllByRole('listitem')
        .map((chip) => chip.textContent)
    ).toEqual(['“banks” → BAC, JPM', 'last 2 years', 'net income'])
    expect(within(chips).getByText('“banks” → BAC, JPM').closest('li')).toHaveAttribute(
      'title',
      'Sector phrase resolved through the Sector table (industry: Banks)'
    )
  })

  it('shows each Coverage Gap in a callout beside the answer', async () => {
    const gaps = [
      {
        kind: 'missing_company',
        label: 'Not in the Corpus',
        companies: ['Wells Fargo'],
        text: 'Not in the Corpus: Wells Fargo is not in the Filings provided, so this answer does not cover it.',
      },
      {
        kind: 'snapshot_trend',
        label: 'Trend unavailable',
        companies: ['JPM'],
        text: 'Trend unavailable: JPMorgan Chase is a Snapshot Company. The Corpus holds 4 JPMorgan Chase Filings.',
      },
    ]
    fetchMock.mockImplementation(async () => uiMessageStream(ANSWER, QUERY_SCOPE, SOURCES, gaps))
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('trade policy')

    const answer = screen.getByRole('article', { name: 'Answer' })
    const callout = within(answer).getByRole('note', { name: 'Coverage Gaps' })
    const items = within(callout).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(within(items[0]).getByText('Not in the Corpus')).toBeInTheDocument()
    expect(items[0]).toHaveTextContent(
      'Wells Fargo is not in the Filings provided, so this answer does not cover it.'
    )
    // The label is shown once, as the gap's heading, not repeated from its wording.
    expect(items[0].textContent?.match(/Not in the Corpus/g)).toHaveLength(1)
    expect(within(items[1]).getByText('Trend unavailable')).toBeInTheDocument()
    // The callout comes before the answer text, so it cannot be missed.
    const text = within(answer).getByText('trade policy')
    expect(callout.compareDocumentPosition(text) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('shows no Coverage Gap callout when the answer has none', async () => {
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('trade policy')

    expect(screen.queryByRole('note', { name: 'Coverage Gaps' })).not.toBeInTheDocument()
  })

  it('shows a Facts Source in the Sources panel as a table of its rows', async () => {
    fetchMock.mockImplementation(async () =>
      uiMessageStream(['NVIDIA reported **revenue** of $57,006 million [S1].'], QUERY_SCOPE, [
        FACTS_SOURCE,
      ])
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('revenue')

    const answer = screen.getByRole('article', { name: 'Answer' })
    await user.click(within(answer).getByRole('link', { name: 'Source S1' }))

    const panel = await screen.findByRole('complementary', { name: 'Sources' })
    const source = within(panel).getByRole('region', { name: /^S1/ })
    expect(within(source).getByText('Filing ID').nextElementSibling?.textContent).toBe(
      'NVDA_10-Q_2025-10-26'
    )
    const table = within(source).getByRole('table', { name: 'Financial Facts' })
    const rows = within(table)
      .getAllByRole('row')
      .map((row) =>
        within(row)
          .queryAllByRole('cell')
          .map((cell) => cell.textContent)
      )
      .filter((cells) => cells.length > 0)
    expect(rows).toEqual([
      ['Revenue', '3 months ended 2025-10-26', '$57,006 million', 'Revenue'],
      [
        'Segment revenue: Compute & Networking',
        '3 months ended 2025-10-26',
        '$50,908 million',
        'Compute & Networking',
      ],
    ])
  })

  it('says so when the answer cannot be loaded, without leaking the error', async () => {
    fetchMock.mockImplementation(async () => new Response('backend exploded', { status: 502 }))
    const user = userEvent.setup()
    render(<Workspace />)

    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))

    expect(await screen.findByRole('alert')).toHaveTextContent('The answer could not be loaded')
    expect(screen.queryByText(/exploded/)).not.toBeInTheDocument()
  })
})
