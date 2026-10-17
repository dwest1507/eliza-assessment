import { act, render, screen, waitFor, within } from '@testing-library/react'
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

/** A Source the answer was given but does not cite. */
const UNCITED_SOURCE = {
  tag: 'S3',
  filingId: 'MSFT_10-K_2025-06-30',
  company: 'Microsoft Corporation',
  ticker: 'MSFT',
  formType: '10-K',
  reportPeriod: '2025-06-30',
  fiscalPeriod: 'FY2025',
  section: 'Risk Factors',
  item: 'Item 1A',
  label: 'MSFT 10-K FY2025, Risk Factors (Item 1A).',
  text: 'Our global operations subject us to potential trade restrictions.',
}

const ANSWER = [
  'Apple and Tesla both face **trade policy** risk. ',
  'Apple depends on outsourcing partners [S1]; ',
  'Tesla is exposed to tariffs [S2].',
]

/**
 * An answer in the prompt's fixed structure: the direct answer, the per-Company detail
 * and the closing Coverage note, each a paragraph, streamed one paragraph at a time.
 */
const LONG_ANSWER = [
  'Apple and Tesla both face **trade policy** risk [S1].\n\n',
  '**Apple.** Apple depends on outsourcing partners.\n\n',
  '**Tesla.** Tesla is exposed to tariffs [S2].\n\nCoverage: Wells Fargo is not in the Filings provided.',
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

/** One part of the API's UI message stream. */
type StreamPart = { type: string } & Record<string, unknown>

/** The parts the chat API streams for one answer, in its order. */
function uiMessageParts(
  answer: string[] = ANSWER,
  scope: object = QUERY_SCOPE,
  sources: object[] = SOURCES,
  gaps: object[] = [],
  messageId = 'msg-1'
): StreamPart[] {
  return [
    { type: 'start', messageId },
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
}

const encoder = new TextEncoder()

function encode(parts: StreamPart[]): Uint8Array {
  return encoder.encode(parts.map((p) => `data: ${JSON.stringify(p)}\n\n`).join(''))
}

function streamResponse(stream: ReadableStream<Uint8Array>): Response {
  return new Response(stream, {
    headers: {
      'content-type': 'text/event-stream',
      'x-vercel-ai-ui-message-stream': 'v1',
    },
  })
}

/** The API's UI message stream for one answer, sent whole. */
function uiMessageStream(...args: Parameters<typeof uiMessageParts>): Response {
  return heldUiMessageStream(() => false, ...args).response
}

/**
 * The API's UI message stream for one answer, held open after the first part that
 * `holdAfter` matches, so a test can see the answer in progress; `release` sends the rest.
 */
function heldUiMessageStream(
  holdAfter: (part: StreamPart) => boolean,
  ...args: Parameters<typeof uiMessageParts>
): { response: Response; release: () => void } {
  const parts = uiMessageParts(...args)
  const held = parts.findIndex(holdAfter)
  const cut = held === -1 ? parts.length : held + 1
  let rest: () => void = () => {}
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encode(parts.slice(0, cut)))
      rest = () => {
        controller.enqueue(encode(parts.slice(cut)))
        controller.enqueue(encoder.encode('data: [DONE]\n\n'))
        controller.close()
      }
      if (held === -1) rest()
    },
  })
  return { response: streamResponse(stream), release: () => act(() => rest()) }
}

const fetchMock = vi.fn()

beforeEach(() => {
  sessionStorage.clear()
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

  it('keeps the conversation through a page refresh in the same session', async () => {
    const user = userEvent.setup()
    const { unmount } = render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('trade policy')
    unmount()

    render(<Workspace />)

    expect(await screen.findByText(STARTERS[0].question)).toBeInTheDocument()
    expect(screen.getByText('trade policy')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Starter prompts' })).not.toBeInTheDocument()
    // The restored answer is complete, so it shows its disclosures.
    const answer = screen.getByRole('article', { name: 'Answer' })
    expect(within(answer).getByRole('button', { name: 'Sources (2)' })).toBeInTheDocument()
    expect(
      within(answer).getByRole('button', { name: 'How this was answered' })
    ).toBeInTheDocument()
    // It keeps its Sources, so its citations still open the panel.
    await user.click(within(answer).getByRole('link', { name: 'Source S2' }))
    expect(await screen.findByRole('complementary', { name: 'Sources' })).toBeInTheDocument()

    // A follow-up after the refresh still carries the earlier turns.
    await user.type(screen.getByRole('textbox', { name: 'Question' }), 'And Microsoft?{Enter}')
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(sentMessages(1).map((m) => m.role)).toEqual(['user', 'assistant', 'user'])
  })

  it('starts a new conversation that clears the history', async () => {
    const user = userEvent.setup()
    const { unmount } = render(<Workspace />)
    expect(screen.queryByRole('button', { name: 'New conversation' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('trade policy')
    const answer = screen.getByRole('article', { name: 'Answer' })
    await user.click(within(answer).getByRole('link', { name: 'Source S1' }))

    await user.click(screen.getByRole('button', { name: 'New conversation' }))

    expect(screen.getByRole('list', { name: 'Starter prompts' })).toBeInTheDocument()
    expect(screen.queryByText('trade policy')).not.toBeInTheDocument()
    expect(screen.queryByRole('complementary', { name: 'Sources' })).not.toBeInTheDocument()

    // The next question starts afresh, with no earlier turns.
    await user.type(screen.getByRole('textbox', { name: 'Question' }), 'And Microsoft?{Enter}')
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(sentMessages(1).map((m) => m.role)).toEqual(['user'])

    // And a refresh does not bring the old conversation back.
    await screen.findByText('trade policy')
    await user.click(screen.getByRole('button', { name: 'New conversation' }))
    unmount()
    render(<Workspace />)
    expect(screen.getByRole('list', { name: 'Starter prompts' })).toBeInTheDocument()
    expect(screen.queryByText('trade policy')).not.toBeInTheDocument()
  })

  it('shows nothing under or above an answer while it streams, but its citations open the panel', async () => {
    const { response, release } = heldUiMessageStream(
      (part) => part.type === 'text-delta' && String(part.delta).includes('[S1]')
    )
    fetchMock.mockImplementation(async () => response)
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))

    const answer = await screen.findByRole('article', { name: 'Answer' })
    await within(answer).findByRole('link', { name: 'Source S1' })
    expect(within(answer).queryByRole('list', { name: 'Query Scope' })).not.toBeInTheDocument()
    expect(within(answer).queryByRole('button', { name: /^Sources/ })).not.toBeInTheDocument()
    expect(
      within(answer).queryByRole('button', { name: 'How this was answered' })
    ).not.toBeInTheDocument()
    expect(within(answer).queryByRole('button', { name: /^S\d/ })).not.toBeInTheDocument()

    await user.click(within(answer).getByRole('link', { name: 'Source S1' }))
    const panel = await screen.findByRole('complementary', { name: 'Sources' })
    expect(within(panel).getByRole('region', { name: /^S1/ })).toHaveTextContent(
      'AAPL_10-K_2025-09-27'
    )

    release()
    expect(await within(answer).findByRole('button', { name: 'Sources (2)' })).toBeInTheDocument()
    expect(
      within(answer).getByRole('button', { name: 'How this was answered' })
    ).toBeInTheDocument()
  })

  it('lists only the cited Sources, in tag order, under a collapsed "Sources (N)"', async () => {
    fetchMock.mockImplementation(async () =>
      uiMessageStream(
        ['Tesla is exposed to **tariffs** [S2]; Apple to its partners [S1], as Tesla [S2].'],
        QUERY_SCOPE,
        [...SOURCES, UNCITED_SOURCE]
      )
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    const toggle = await within(answer).findByRole('button', { name: 'Sources (2)' })

    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(within(answer).queryByRole('list', { name: 'Cited Sources' })).not.toBeInTheDocument()

    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const list = within(answer).getByRole('list', { name: 'Cited Sources' })
    expect(
      within(list)
        .getAllByRole('button')
        .map((chip) => chip.textContent)
    ).toEqual(['S1 AAPL 10-K FY2025, Risk Factors', 'S2 TSLA 10-K FY2025, Risk Factors'])

    await user.click(within(list).getByRole('button', { name: /^S2/ }))
    const panel = await screen.findByRole('complementary', { name: 'Sources' })
    expect(within(panel).getByRole('region', { name: /^S2/ })).toHaveTextContent(
      'TSLA_10-K_2025-12-31'
    )
  })

  it('shows no "Sources" list when the answer cites none', async () => {
    fetchMock.mockImplementation(async () =>
      uiMessageStream(['The Filings do not discuss **this** at all.'])
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    await within(answer).findByRole('button', { name: 'How this was answered' })

    expect(within(answer).queryByRole('button', { name: /^Sources/ })).not.toBeInTheDocument()
  })

  it('holds the Query Scope chips and every retrieved Source under "How this was answered"', async () => {
    fetchMock.mockImplementation(async () =>
      uiMessageStream(ANSWER, QUERY_SCOPE, [...SOURCES, UNCITED_SOURCE])
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    const toggle = await within(answer).findByRole('button', { name: 'How this was answered' })

    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(within(answer).queryByRole('list', { name: 'Query Scope' })).not.toBeInTheDocument()

    await user.click(toggle)
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
    const retrieved = within(answer).getByRole('list', { name: 'Retrieved Sources' })
    expect(
      within(retrieved)
        .getAllByRole('button')
        .map((chip) => chip.textContent)
    ).toEqual([
      'S1 AAPL 10-K FY2025, Risk Factors',
      'S2 TSLA 10-K FY2025, Risk Factors',
      'S3 MSFT 10-K FY2025, Risk Factors',
    ])

    // An uncited Source opens too, and joins the cited ones in the panel's switcher.
    await user.click(within(retrieved).getByRole('button', { name: /^S3/ }))
    const panel = await screen.findByRole('complementary', { name: 'Sources' })
    expect(within(panel).getByRole('region', { name: /^S3/ })).toHaveTextContent(
      'MSFT_10-K_2025-06-30'
    )
    const switcher = () =>
      within(within(panel).getByRole('navigation', { name: "This answer's Sources" }))
        .getAllByRole('button')
        .map((tab) => tab.textContent)
    expect(switcher()).toEqual(['S1', 'S2', 'S3'])

    // Opening a cited Source leaves the switcher with the cited Sources only.
    await user.click(within(answer).getByRole('link', { name: 'Source S1' }))
    expect(switcher()).toEqual(['S1', 'S2'])
  })

  it('shows only the opening paragraph until "Show full analysis" is clicked', async () => {
    fetchMock.mockImplementation(async () => uiMessageStream(LONG_ANSWER))
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    const toggle = await within(answer).findByRole('button', { name: 'Show full analysis' })

    expect(within(answer).getByText('trade policy')).toBeInTheDocument()
    expect(within(answer).queryByText(/outsourcing partners/)).not.toBeInTheDocument()
    expect(within(answer).queryByText(/Coverage:/)).not.toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(within(answer).queryByText(/still being written/)).not.toBeInTheDocument()

    await user.click(toggle)
    const hide = within(answer).getByRole('button', { name: 'Hide full analysis' })
    expect(hide).toHaveAttribute('aria-expanded', 'true')
    expect(within(answer).getByText(/outsourcing partners/)).toBeInTheDocument()
    expect(within(answer).getByText(/Coverage:/)).toBeInTheDocument()
    expect(within(answer).getByRole('link', { name: 'Source S2' })).toBeInTheDocument()

    await user.click(hide)
    expect(within(answer).queryByText(/outsourcing partners/)).not.toBeInTheDocument()
    // The Sources it cites are counted from the whole answer, not only the opening.
    expect(within(answer).getByRole('button', { name: 'Sources (2)' })).toBeInTheDocument()
  })

  it('opens the Sources panel from a citation in the short answer', async () => {
    fetchMock.mockImplementation(async () => uiMessageStream(LONG_ANSWER))
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    await within(answer).findByRole('button', { name: 'Show full analysis' })

    await user.click(within(answer).getByRole('link', { name: 'Source S1' }))

    const panel = await screen.findByRole('complementary', { name: 'Sources' })
    expect(within(panel).getByRole('region', { name: /^S1/ })).toHaveTextContent(
      'AAPL_10-K_2025-09-27'
    )
  })

  it('shows a Coverage Gap once by default, leaving the closing Coverage note to the full analysis', async () => {
    const gaps = [
      {
        kind: 'missing_company',
        label: 'Not in the Corpus',
        companies: ['Wells Fargo'],
        text: 'Not in the Corpus: Wells Fargo is not in the Filings provided, so this answer does not cover it.',
      },
    ]
    fetchMock.mockImplementation(async () =>
      uiMessageStream(LONG_ANSWER, QUERY_SCOPE, SOURCES, gaps)
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    const toggle = await within(answer).findByRole('button', { name: 'Show full analysis' })

    expect(answer.textContent?.match(/Wells Fargo is not in the Filings/g)).toHaveLength(1)
    await user.click(toggle)
    expect(answer.textContent?.match(/Wells Fargo is not in the Filings/g)).toHaveLength(2)
  })

  it('shows the whole answer, with no control, when it has one paragraph', async () => {
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    await within(answer).findByRole('button', { name: 'How this was answered' })

    expect(within(answer).getByText(/Tesla is exposed to tariffs/)).toBeInTheDocument()
    expect(within(answer).queryByRole('button', { name: /full analysis/ })).not.toBeInTheDocument()
  })

  it.each([
    ['a table', '| Company | Risk |\n| --- | --- |\n| Apple | Tariffs [S1] |\n\n'],
    ['a heading', '## Apple and Tesla [S1]\n\n'],
  ])('shows the whole answer, with no control, when it opens with %s', async (_, opening) => {
    fetchMock.mockImplementation(async () =>
      uiMessageStream([opening, '**Tesla.** Tesla is exposed to tariffs [S2].'])
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    await within(answer).findByRole('button', { name: 'How this was answered' })

    expect(within(answer).getByText(/Tesla is exposed to tariffs/)).toBeInTheDocument()
    expect(within(answer).queryByRole('button', { name: /full analysis/ })).not.toBeInTheDocument()
  })

  it('offers no control while only the opening has streamed', async () => {
    const { response, release } = heldUiMessageStream(
      (part) => part.type === 'text-delta',
      LONG_ANSWER
    )
    fetchMock.mockImplementation(async () => response)
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))

    const answer = await screen.findByRole('article', { name: 'Answer' })
    await within(answer).findByText('trade policy')
    expect(within(answer).queryByRole('button', { name: /full analysis/ })).not.toBeInTheDocument()

    release()
    expect(
      await within(answer).findByRole('button', { name: 'Show full analysis' })
    ).toBeInTheDocument()
  })

  it('expands mid-stream, showing the rest live and that it is still being written', async () => {
    const { response, release } = heldUiMessageStream(
      (part) => part.type === 'text-delta' && String(part.delta).includes('outsourcing'),
      LONG_ANSWER
    )
    fetchMock.mockImplementation(async () => response)
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))

    const answer = await screen.findByRole('article', { name: 'Answer' })
    const toggle = await within(answer).findByRole('button', { name: 'Show full analysis' })
    expect(within(answer).getByText(/still being written/)).toBeInTheDocument()
    expect(within(answer).queryByText(/outsourcing partners/)).not.toBeInTheDocument()

    await user.click(toggle)
    expect(within(answer).getByText(/outsourcing partners/)).toBeInTheDocument()
    expect(within(answer).queryByText(/Tesla is exposed/)).not.toBeInTheDocument()
    expect(within(answer).getByText(/still being written/)).toBeInTheDocument()

    release()
    expect(await within(answer).findByText(/Tesla is exposed/)).toBeInTheDocument()
    expect(within(answer).queryByText(/still being written/)).not.toBeInTheDocument()
    expect(within(answer).getByRole('button', { name: 'Hide full analysis' })).toBeInTheDocument()
  })

  it('keeps each answer expanded or collapsed on its own, and restores them collapsed', async () => {
    fetchMock
      .mockImplementationOnce(async () => uiMessageStream(LONG_ANSWER))
      .mockImplementationOnce(async () =>
        uiMessageStream(LONG_ANSWER, QUERY_SCOPE, SOURCES, [], 'msg-2')
      )
    const user = userEvent.setup()
    const { unmount } = render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByRole('button', { name: 'Show full analysis' })
    await user.type(screen.getByRole('textbox', { name: 'Question' }), 'And Microsoft?{Enter}')
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'Show full analysis' })).toHaveLength(2)
    )

    const [first, second] = screen.getAllByRole('article', { name: 'Answer' })
    await user.click(within(second).getByRole('button', { name: 'Show full analysis' }))
    expect(within(second).getByText(/outsourcing partners/)).toBeInTheDocument()
    expect(within(first).queryByText(/outsourcing partners/)).not.toBeInTheDocument()
    unmount()

    render(<Workspace />)
    const restored = await screen.findAllByRole('article', { name: 'Answer' })
    expect(restored).toHaveLength(2)
    for (const answer of restored) {
      expect(within(answer).getByRole('button', { name: 'Show full analysis' })).toHaveAttribute(
        'aria-expanded',
        'false'
      )
      expect(within(answer).queryByText(/outsourcing partners/)).not.toBeInTheDocument()
    }
  })

  it('shows a cited tag that is not among the Sources as unavailable', async () => {
    fetchMock.mockImplementation(async () =>
      uiMessageStream(['Apple relies on **partners** [S1] and [S7].'])
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    await within(answer).findByRole('button', { name: 'Sources (1)' })

    expect(within(answer).getByText('S7')).toHaveAttribute(
      'title',
      "Not among this answer's Sources"
    )
    expect(within(answer).queryByRole('link', { name: 'Source S7' })).not.toBeInTheDocument()
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
    const answer = screen.getByRole('article', { name: 'Answer' })
    await user.click(await within(answer).findByRole('button', { name: 'How this was answered' }))

    const chips = within(answer).getByRole('list', { name: 'Query Scope' })
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
    // Headed in plain words, keeping the domain term as its accessible name and hover text.
    const heading = within(callout).getByRole('heading', {
      name: 'What these Filings can’t answer',
    })
    expect(heading).toHaveAttribute('title', 'Coverage Gaps')
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

  it("shows the API's reason when it rejects the question", async () => {
    const reason = 'Message 2 of the conversation is longer than 20,000 characters.'
    fetchMock.mockImplementation(async () => Response.json({ detail: reason }, { status: 400 }))
    const user = userEvent.setup()
    render(<Workspace />)

    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(reason)
    expect(alert).not.toHaveTextContent('make dev')
    // A rejected question would be rejected again, so there is nothing to retry.
    expect(within(alert).queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })

  it('says so plainly when the answer cannot be loaded, without leaking the error', async () => {
    fetchMock.mockImplementation(async () => new Response('backend exploded', { status: 502 }))
    const user = userEvent.setup()
    render(<Workspace />)

    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent("The answer couldn't be loaded. Please try again.")
    expect(alert).not.toHaveTextContent('make dev')
    expect(within(alert).getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    expect(screen.queryByText(/exploded/)).not.toBeInTheDocument()
  })

  it('re-sends the last question on "Try again" and shows the new answer', async () => {
    fetchMock.mockImplementationOnce(async () => new Response('backend exploded', { status: 502 }))
    const user = userEvent.setup()
    render(<Workspace />)
    const starter = STARTERS[0]
    await user.click(screen.getByRole('button', { name: starter.label }))
    const alert = await screen.findByRole('alert')

    await user.click(within(alert).getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('trade policy')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    // The same question, sent once: not retyped, not duplicated.
    const resent = sentMessages(1)
    expect(resent).toHaveLength(1)
    expect(resent[0]).toMatchObject({
      role: 'user',
      parts: [{ type: 'text', text: starter.question }],
    })
    expect(screen.getAllByText(starter.question)).toHaveLength(1)
  })
})

describe('Follow-up suggestions', () => {
  /** The API's stream for one answer, under its own message id, so two answers differ. */
  function answerStream(messageId: string, ...args: Parameters<typeof uiMessageParts>) {
    const parts = uiMessageParts(...args).map((part) =>
      part.type === 'start' ? { ...part, messageId } : part
    )
    return streamResponse(
      new ReadableStream({
        start(controller) {
          controller.enqueue(encode(parts))
          controller.enqueue(encoder.encode('data: [DONE]\n\n'))
          controller.close()
        },
      })
    )
  }

  const suggestionsOf = (list: HTMLElement) =>
    within(list)
      .getAllByRole('button')
      .map((button) => button.textContent)

  it('suggests follow-ups once the answer is complete, never while it streams', async () => {
    const { response, release } = heldUiMessageStream((part) => part.type === 'text-delta')
    fetchMock.mockImplementation(async () => response)
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))

    await screen.findByText(/trade policy/)
    expect(screen.queryByRole('list', { name: 'Suggested follow-ups' })).not.toBeInTheDocument()

    release()
    const list = await screen.findByRole('list', { name: 'Suggested follow-ups' })
    expect(suggestionsOf(list)).toEqual([
      'How do the main risk factors of Apple and Tesla compare?',
      'How does revenue compare between Apple and Tesla in their latest filings?',
      'How do Apple and Tesla describe their outlook in their latest filings?',
    ])
  })

  it('suggests no trend for a Snapshot Company', async () => {
    const scope = {
      ...QUERY_SCOPE,
      companies: [{ ticker: 'JPM', name: 'JPMorgan Chase & Co', coverage: 'snapshot' }],
    }
    fetchMock.mockImplementation(async () => uiMessageStream(ANSWER, scope))
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))

    const list = await screen.findByRole('list', { name: 'Suggested follow-ups' })
    const suggestions = suggestionsOf(list)
    expect(suggestions).toContain("What was JPMorgan Chase's revenue in its latest filing?")
    expect(suggestions.filter((s) => /changed|last two years/.test(s ?? ''))).toEqual([])
  })

  it('sends a suggestion on click, and shows suggestions only under the latest answer', async () => {
    const second = {
      ...QUERY_SCOPE,
      companies: [{ ticker: 'AAPL', name: 'Apple Inc', coverage: 'tracked' }],
    }
    const held = heldUiMessageStream((part) => part.type === 'text-delta', ANSWER, second)
    fetchMock
      .mockImplementationOnce(async () => answerStream('msg-0'))
      .mockImplementationOnce(async () => held.response)
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))

    const first = await screen.findByRole('list', { name: 'Suggested follow-ups' })
    const suggestion = 'How do the main risk factors of Apple and Tesla compare?'
    await user.click(within(first).getByRole('button', { name: suggestion }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(sentMessages(1).at(-1)).toMatchObject({
      role: 'user',
      parts: [{ type: 'text', text: suggestion }],
    })
    // The question is in the thread, and no suggestion shows while its answer streams.
    expect(await screen.findByText(suggestion)).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByRole('article', { name: 'Answer' })).toHaveLength(2))
    expect(screen.queryByRole('list', { name: 'Suggested follow-ups' })).not.toBeInTheDocument()

    held.release()
    const lists = await screen.findAllByRole('list', { name: 'Suggested follow-ups' })
    expect(lists).toHaveLength(1)
    expect(suggestionsOf(lists[0])).toEqual([
      "What are Apple's main risk factors?",
      "How has Apple's revenue changed over the last two years?",
      "What does Apple's latest filing say about its outlook?",
    ])
    // Under the latest answer, not the first one.
    const answers = screen.getAllByRole('article', { name: 'Answer' })
    expect(answers[1].compareDocumentPosition(lists[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    )
  })

  it('shows no suggestions once a later question fails', async () => {
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    expect(await screen.findByRole('list', { name: 'Suggested follow-ups' })).toBeInTheDocument()

    fetchMock.mockImplementation(async () => new Response('backend exploded', { status: 502 }))
    await user.type(screen.getByRole('textbox', { name: 'Question' }), 'And Microsoft?{Enter}')
    await screen.findByRole('alert')
    expect(screen.queryByRole('list', { name: 'Suggested follow-ups' })).not.toBeInTheDocument()
  })
})
