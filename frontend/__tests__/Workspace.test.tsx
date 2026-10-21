import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Workspace from '@/components/Workspace'
import evalExport from '@/data/eval-export.json'
import type { EvalExport } from '@/lib/evalExport'
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
    calendarMonths: 'Oct 2024–Sep 2025',
    section: 'Risk Factors',
    item: 'Item 1A',
    label: 'AAPL 10-K FY2025 (Oct 2024–Sep 2025), Risk Factors (Item 1A).',
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
    calendarMonths: 'Jan–Dec 2025',
    section: 'Risk Factors',
    item: 'Item 1A',
    label: 'TSLA 10-K FY2025 (Jan–Dec 2025), Risk Factors (Item 1A).',
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
  calendarMonths: 'Jul 2024–Jun 2025',
  section: 'Risk Factors',
  item: 'Item 1A',
  label: 'MSFT 10-K FY2025 (Jul 2024–Jun 2025), Risk Factors (Item 1A).',
  text: 'Our global operations subject us to potential trade restrictions.',
}

const ANSWER = [
  'Apple and Tesla both face **trade policy** risk. ',
  'Apple depends on outsourcing partners [S1]; ',
  'Tesla is exposed to tariffs [S2].',
]

/**
 * An answer in the prompt's structure: the direct answer, then the per-Company detail,
 * each a paragraph, streamed one paragraph at a time. From prompt v15 it has no closing
 * Coverage note: the workspace shows the Coverage Gaps below it (ADR 0016).
 */
const LONG_ANSWER = [
  'Apple and Tesla both face **trade policy** risk [S1].\n\n',
  '**Apple.** Apple depends on outsourcing partners.\n\n',
  '**Tesla.** Tesla is exposed to tariffs [S2].\n\nNeither gives a tariff forecast in these filings.',
]

/** A Coverage Gap as the chat API streams it: a Company not in the Corpus. */
const WELLS_FARGO_GAP = {
  kind: 'missing_company',
  label: 'Not in the Corpus',
  companies: ['Wells Fargo'],
  text: 'Not in the Corpus: Wells Fargo is not in the Filings provided, so this answer does not cover it.',
}

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
  calendarMonths: 'Aug–Oct 2025',
  section: 'Financial Facts',
  item: null,
  label: 'NVDA 10-Q Q3 FY2026 (Aug–Oct 2025), Financial Facts.',
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

  it('explains itself in plain words, without capitalised domain terms', () => {
    render(<Workspace />)

    const domainTerms =
      /\b(Company|Companies|Filings?|Sections?|Sources?|Corpus|Query Scope|Coverage Gaps?)\b/
    const subtitle = within(screen.getByRole('banner')).getByText(
      'Answers from companies’ 10-K and 10-Q filings, with every claim linked to its passage'
    )
    const heading = screen.getByRole('heading', { name: 'Ask a question about a public company' })
    const intro = screen.getByText(
      'Name a company or its ticker. Each answer links every claim to the filing passage it comes from, and says what the filings can’t answer.'
    )
    for (const copy of [subtitle, heading, intro]) {
      expect(copy.textContent).not.toMatch(domainTerms)
    }
    expect(screen.getByRole('textbox', { name: 'Question' })).toHaveAttribute(
      'placeholder',
      expect.not.stringMatching(domainTerms)
    )
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

    // The panel may have opened by itself, but on the Calendar.
    expect(screen.queryByRole('tabpanel', { name: 'Sources' })).not.toBeInTheDocument()

    const answer = screen.getByRole('article', { name: 'Answer' })
    await user.click(within(answer).getByRole('link', { name: 'Source S2' }))

    const panel = await screen.findByRole('tabpanel', { name: 'Sources' })
    const source = within(panel).getByRole('region', { name: /^S2/ })
    expect(within(source).getByRole('heading', { level: 3 })).toHaveTextContent(
      'S2Tesla 10-K, FY2025 (Jan–Dec 2025) · Risk Factors'
    )

    // The Filing metadata waits under a collapsed toggle.
    const details = within(source).getByRole('button', { name: 'Filing details' })
    expect(details).toHaveAttribute('aria-expanded', 'false')
    expect(within(source).queryByText('Filing ID')).not.toBeInTheDocument()
    await user.click(details)
    expect(details).toHaveAttribute('aria-expanded', 'true')

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

    const panel = screen.getByRole('tabpanel', { name: 'Sources' })
    expect(within(panel).getByRole('region', { name: /^S1/ })).toHaveTextContent(
      'A significant majority of the Company’s manufacturing'
    )
    expect(within(panel).queryByRole('region', { name: /^S2/ })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Close panel' }))
    expect(screen.queryByRole('complementary', { name: 'Side panel' })).not.toBeInTheDocument()
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
    // The restored answer is complete, so it shows its Sources disclosure.
    const answer = screen.getByRole('article', { name: 'Answer' })
    expect(within(answer).getByRole('button', { name: 'Sources (2)' })).toBeInTheDocument()
    // It keeps its Sources, so its citations still open the panel.
    await user.click(within(answer).getByRole('link', { name: 'Source S2' }))
    expect(await screen.findByRole('tabpanel', { name: 'Sources' })).toBeInTheDocument()

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
    expect(screen.queryByRole('complementary', { name: 'Side panel' })).not.toBeInTheDocument()

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
    expect(within(answer).queryByRole('button', { name: /^S\d/ })).not.toBeInTheDocument()

    await user.click(within(answer).getByRole('link', { name: 'Source S1' }))
    const panel = await screen.findByRole('tabpanel', { name: 'Sources' })
    expect(within(panel).getByRole('region', { name: /^S1/ })).toHaveTextContent(
      'Apple 10-K, FY2025 (Oct 2024–Sep 2025) · Risk Factors'
    )

    release()
    expect(await within(answer).findByRole('button', { name: 'Sources (2)' })).toBeInTheDocument()
  })

  it('holds the Query Scope chips, the cited Sources and a collapsed "Also retrieved (N)" under one "Sources"', async () => {
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

    // One disclosure, collapsed: "How this was answered" is gone.
    expect(within(answer).queryByRole('button', { name: /How this was answered/ })).toBeNull()
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(within(answer).queryByRole('list', { name: 'Query Scope' })).not.toBeInTheDocument()
    expect(within(answer).queryByRole('list', { name: 'Cited Sources' })).not.toBeInTheDocument()

    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    // The Query Scope chips come first, then the cited Sources in tag order.
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
    const cited = within(answer).getByRole('list', { name: 'Cited Sources' })
    expect(chips.compareDocumentPosition(cited) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(
      within(cited)
        .getAllByRole('button')
        .map((chip) => chip.textContent)
    ).toEqual([
      'S1 AAPL 10-K FY2025 (Oct 2024–Sep 2025), Risk Factors',
      'S2 TSLA 10-K FY2025 (Jan–Dec 2025), Risk Factors',
    ])

    // The Sources it was given but does not cite wait under their own collapsed toggle.
    const also = within(answer).getByRole('button', { name: 'Also retrieved (1)' })
    expect(also).toHaveAttribute('aria-expanded', 'false')
    expect(cited.compareDocumentPosition(also) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(within(answer).queryByRole('list', { name: 'Also retrieved' })).not.toBeInTheDocument()
    await user.click(also)
    const retrieved = within(answer).getByRole('list', { name: 'Also retrieved' })
    expect(
      within(retrieved)
        .getAllByRole('button')
        .map((chip) => chip.textContent)
    ).toEqual(['S3 MSFT 10-K FY2025 (Jul 2024–Jun 2025), Risk Factors'])

    // Each chip opens the Sources tab at its Source, an uncited one too.
    await user.click(within(cited).getByRole('button', { name: /^S2/ }))
    const panel = await screen.findByRole('tabpanel', { name: 'Sources' })
    expect(within(panel).getByRole('region', { name: /^S2/ })).toHaveTextContent(
      'Tesla 10-K, FY2025 (Jan–Dec 2025) · Risk Factors'
    )
    await user.click(within(retrieved).getByRole('button', { name: /^S3/ }))
    expect(within(panel).getByRole('region', { name: /^S3/ })).toHaveTextContent(
      'Microsoft 10-K, FY2025 (Jul 2024–Jun 2025) · Risk Factors'
    )
  })

  it('shows the Query Scope and the retrieved Sources when the answer cites none', async () => {
    fetchMock.mockImplementation(async () =>
      uiMessageStream(['The Filings do not discuss **this** at all.'])
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    await user.click(await within(answer).findByRole('button', { name: 'Sources' }))

    expect(within(answer).getByRole('list', { name: 'Query Scope' })).toBeInTheDocument()
    expect(within(answer).queryByRole('list', { name: 'Cited Sources' })).not.toBeInTheDocument()
    expect(within(answer).getByRole('button', { name: 'Also retrieved (2)' })).toBeInTheDocument()
  })

  it('numbers every retrieved Source in the panel, cited and uncited styled apart', async () => {
    fetchMock.mockImplementation(async () =>
      uiMessageStream(ANSWER, QUERY_SCOPE, [...SOURCES, UNCITED_SOURCE])
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    await user.click(await within(answer).findByRole('link', { name: 'Source S1' }))

    const panel = await screen.findByRole('tabpanel', { name: 'Sources' })
    const strip = within(panel).getByRole('navigation', { name: "This answer's Sources" })
    const tabs = within(strip).getAllByRole('button')
    expect(tabs.map((tab) => tab.textContent)).toEqual(['S1', 'S2', 'S3'])
    expect(strip.querySelector('ul')).toHaveClass('flex-wrap')
    // Cited tabs in the accent colour, the uncited one muted, each saying which it is.
    const [s1, s2, s3] = tabs
    expect(s1).toHaveAttribute('aria-pressed', 'true')
    expect(s1).toHaveAttribute('title', 'Cited: AAPL 10-K FY2025 (Oct 2024–Sep 2025), Risk Factors')
    expect(s2).toHaveClass('text-accent-strong')
    expect(s3).toHaveAttribute(
      'title',
      'Retrieved, not cited: MSFT 10-K FY2025 (Jul 2024–Jun 2025), Risk Factors'
    )
    expect(s3).toHaveClass('text-muted')
    expect(s3).not.toHaveClass('text-accent-strong')

    // An uncited Source opens with its number, and its header gives the tag and its label.
    await user.click(s3)
    expect(s3).toHaveAttribute('aria-pressed', 'true')
    const source = within(panel).getByRole('region', { name: /^S3/ })
    const heading = within(source).getByRole('heading', { level: 3 })
    expect(heading).toHaveTextContent('S3Microsoft 10-K, FY2025 (Jul 2024–Jun 2025) · Risk Factors')
    expect(heading).toHaveAttribute(
      'title',
      'MSFT 10-K FY2025 (Jul 2024–Jun 2025), Risk Factors (Item 1A).'
    )
    expect(source).toHaveTextContent(
      'Our global operations subject us to potential trade restrictions.'
    )
  })

  it("gives each Source's calendar months beside its fiscal period, in the header and the list", async () => {
    fetchMock.mockImplementation(async () =>
      uiMessageStream(ANSWER, QUERY_SCOPE, [...SOURCES, UNCITED_SOURCE])
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    await user.click(await within(answer).findByRole('link', { name: 'Source S1' }))

    const panel = await screen.findByRole('tabpanel', { name: 'Sources' })
    const heading = within(within(panel).getByRole('region', { name: /^S1/ })).getByRole(
      'heading',
      { level: 3 }
    )
    expect(heading).toHaveTextContent('S1Apple 10-K, FY2025 (Oct 2024–Sep 2025) · Risk Factors')

    const strip = within(panel).getByRole('navigation', { name: "This answer's Sources" })
    expect(
      within(strip)
        .getAllByRole('button')
        .map((tab) => tab.title)
    ).toEqual([
      'Cited: AAPL 10-K FY2025 (Oct 2024–Sep 2025), Risk Factors',
      'Cited: TSLA 10-K FY2025 (Jan–Dec 2025), Risk Factors',
      'Retrieved, not cited: MSFT 10-K FY2025 (Jul 2024–Jun 2025), Risk Factors',
    ])
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
    expect(within(answer).queryByText(/tariff forecast/)).not.toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(within(answer).queryByText(/still being written/)).not.toBeInTheDocument()

    await user.click(toggle)
    const hide = within(answer).getByRole('button', { name: 'Hide full analysis' })
    expect(hide).toHaveAttribute('aria-expanded', 'true')
    expect(within(answer).getByText(/outsourcing partners/)).toBeInTheDocument()
    expect(within(answer).getByText(/tariff forecast/)).toBeInTheDocument()
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

    const panel = await screen.findByRole('tabpanel', { name: 'Sources' })
    expect(within(panel).getByRole('region', { name: /^S1/ })).toHaveTextContent(
      'Apple 10-K, FY2025 (Oct 2024–Sep 2025) · Risk Factors'
    )
  })

  it('shows each Coverage Gap once, as a Coverage note below the answer, collapsed or not', async () => {
    fetchMock.mockImplementation(async () =>
      uiMessageStream(LONG_ANSWER, QUERY_SCOPE, SOURCES, [WELLS_FARGO_GAP])
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    const toggle = await within(answer).findByRole('button', { name: 'Show full analysis' })

    expect(answer.textContent?.match(/Wells Fargo is not in the filings/gi)).toHaveLength(1)
    await user.click(toggle)
    expect(answer.textContent?.match(/Wells Fargo is not in the filings/gi)).toHaveLength(1)
    // Below the whole answer, not between its opening and its full analysis.
    const notes = within(answer).getByRole('note', { name: 'Coverage notes' })
    const last = within(answer).getByText(/tariff forecast/)
    expect(last.compareDocumentPosition(notes) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('shows the Coverage notes only once the answer is complete, never above it', async () => {
    const { response, release } = heldUiMessageStream(
      (part) => part.type === 'text-delta',
      LONG_ANSWER,
      QUERY_SCOPE,
      SOURCES,
      [WELLS_FARGO_GAP]
    )
    fetchMock.mockImplementation(async () => response)
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))

    const answer = await screen.findByRole('article', { name: 'Answer' })
    await within(answer).findByText('trade policy')
    // The gaps arrived before the text, but nothing leads the answer with them.
    expect(within(answer).queryByRole('note', { name: 'Coverage notes' })).not.toBeInTheDocument()
    expect(answer.textContent).not.toMatch(/Wells Fargo/)

    release()
    const notes = await within(answer).findByRole('note', { name: 'Coverage notes' })
    const opening = within(answer).getByText('trade policy')
    expect(opening.compareDocumentPosition(notes) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('shows the whole answer, with no control, when it has one paragraph', async () => {
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    await within(answer).findByRole('button', { name: /^Sources/ })

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
    await within(answer).findByRole('button', { name: /^Sources/ })

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

  it('shows the Sections the answer was searched in, and the Filings searched whole', async () => {
    fetchMock.mockImplementation(async () =>
      uiMessageStream(ANSWER, {
        ...QUERY_SCOPE,
        searched: [
          { ticker: 'AAPL', filingId: 'AAPL_10-K_2025-09-27', section: 'Risk Factors' },
          { ticker: 'AAPL', filingId: 'AAPL_10-Q_2025-12-27', section: 'MD&A' },
          { ticker: 'TSLA', filingId: 'TSLA_10-K_2025-12-31', section: 'Risk Factors' },
          { ticker: 'TSLA', filingId: 'TSLA_10-Q_2025-09-30', section: null },
        ],
      })
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    await user.click(await within(answer).findByRole('button', { name: /^Sources/ }))

    const searched = within(answer).getByRole('list', { name: 'Searched in' })
    expect(
      within(searched)
        .getAllByRole('listitem')
        .map((place) => place.textContent)
    ).toEqual(['Risk Factors · 2 Filings', 'MD&A · 1 Filing', 'Whole Filing · 1 Filing'])
    expect(within(searched).getByText('Risk Factors · 2 Filings').closest('li')).toHaveAttribute(
      'title',
      'Searched in: AAPL_10-K_2025-09-27, TSLA_10-K_2025-12-31'
    )
    expect(within(searched).getByText('Whole Filing · 1 Filing').closest('li')).toHaveAttribute(
      'title',
      'Searched whole: TSLA_10-Q_2025-09-30'
    )
  })

  it('shows no searched places for an answer saved before they were sent', async () => {
    fetchMock.mockImplementation(async () => uiMessageStream(ANSWER, QUERY_SCOPE))
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    await user.click(await within(answer).findByRole('button', { name: /^Sources/ }))

    expect(within(answer).getByRole('list', { name: 'Query Scope' })).toBeInTheDocument()
    expect(within(answer).queryByRole('list', { name: 'Searched in' })).not.toBeInTheDocument()
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
    await user.click(await within(answer).findByRole('button', { name: /^Sources/ }))

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

  it('shows a Company Group as a curated group with the Companies it covers', async () => {
    const bigTech = ['AAPL', 'AMZN', 'GOOG', 'META', 'MSFT', 'NVDA', 'TSLA']
    fetchMock.mockImplementation(async () =>
      uiMessageStream(ANSWER, {
        companies: bigTech.map((ticker) => ({ ticker, name: ticker, coverage: 'tracked' })),
        sectorPhrases: [
          {
            phrase: 'big tech companies',
            column: 'group',
            values: ['Big Tech'],
            tickers: bigTech,
          },
        ],
        timeWindow: { kind: 'latest', count: null, label: 'latest' },
        sections: ['Risk Factors'],
        metric: null,
      })
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await user.type(
      screen.getByRole('textbox', { name: 'Question' }),
      'What are the main AI risks for big tech companies?{Enter}'
    )
    const answer = screen.getByRole('article', { name: 'Answer' })
    await user.click(await within(answer).findByRole('button', { name: /^Sources/ }))

    const chips = within(answer).getByRole('list', { name: 'Query Scope' })
    const chip = within(chips).getByText(`“big tech companies” → ${bigTech.join(', ')}`)
    expect(chip.closest('li')).toHaveAttribute(
      'title',
      'Company Group “Big Tech”, curated in the Sector table'
    )
  })

  it('shows each Coverage Gap as a Coverage note in its fixed wording, in plain words', async () => {
    const gaps = [
      WELLS_FARGO_GAP,
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
    const notes = await within(answer).findByRole('note', { name: 'Coverage notes' })
    // Headed "Coverage notes", keeping the domain term as hover text.
    const heading = within(notes).getByRole('heading', { name: 'Coverage notes' })
    expect(heading).toHaveAttribute('title', 'Coverage Gaps')
    const items = within(notes).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    // Each gap's label in plain words, with the label the answer states on hover.
    expect(within(items[0]).getByText('Not covered')).toHaveAttribute('title', 'Not in the Corpus')
    expect(items[0]).toHaveTextContent(
      'Wells Fargo is not in the filings provided, so this answer does not cover it.'
    )
    // The label is shown once, as the gap's heading, not repeated from its wording.
    expect(items[0].textContent).not.toMatch(/Not in the Corpus/)
    expect(within(items[1]).getByText('Trend unavailable')).toBeInTheDocument()
    // Domain terms in the wording read plainly, with the term on hover.
    expect(items[1]).toHaveTextContent(
      'JPMorgan Chase is a company with only a few filings. The collection holds 4 JPMorgan Chase filings.'
    )
    expect(within(items[1]).getByTitle('Snapshot Company')).toHaveTextContent(
      'company with only a few filings'
    )
    expect(within(items[1]).getByTitle('Corpus')).toHaveTextContent('collection')
    expect(within(items[0]).getByTitle('Filings')).toHaveTextContent('filings')
    // The notes follow the answer text: the answer leads with its finding.
    const text = within(answer).getByText('trade policy')
    expect(text.compareDocumentPosition(notes) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('shows no Coverage notes when the answer has no Coverage Gap', async () => {
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    const answer = screen.getByRole('article', { name: 'Answer' })
    await within(answer).findByRole('button', { name: 'Sources (2)' })

    expect(screen.queryByRole('note', { name: 'Coverage notes' })).not.toBeInTheDocument()
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

    const panel = await screen.findByRole('tabpanel', { name: 'Sources' })
    const source = within(panel).getByRole('region', { name: /^S1/ })
    expect(within(source).getByRole('heading', { level: 3 })).toHaveTextContent(
      'S1NVIDIA 10-Q, Q3 FY2026 (Aug–Oct 2025) · Financial Facts'
    )
    await user.click(within(source).getByRole('button', { name: 'Filing details' }))
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

  it("shows a passage's flattened tables as tables and its gaps as breaks", async () => {
    const mdna = {
      ...SOURCES[0],
      tag: 'S1',
      filingId: 'NVDA_10-Q_2024-07-28',
      company: 'NVIDIA Corporation',
      ticker: 'NVDA',
      formType: '10-Q',
      reportPeriod: '2024-07-28',
      fiscalPeriod: 'Q2 FY2025',
      calendarMonths: 'May–Jul 2024',
      section: 'MD&A',
      item: 'Item 2',
      label: 'NVDA 10-Q Q2 FY2025 (May–Jul 2024), MD&A (Item 2).',
      text: [
        'Second Quarter of Fiscal Year 2025 Summary',
        '| Three Months Ended |  |',
        'Revenue | $ | 30,040 |  |  |',
        'Gross margin | 75.1 | % |  |',
        '[…]',
        'Data Center revenue was a record.',
      ].join('\n'),
    }
    fetchMock.mockImplementation(async () =>
      uiMessageStream(['NVIDIA reported **revenue** of $30,040 million [S1].'], QUERY_SCOPE, [mdna])
    )
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('revenue')
    const answer = screen.getByRole('article', { name: 'Answer' })
    await user.click(within(answer).getByRole('link', { name: 'Source S1' }))

    const panel = await screen.findByRole('tabpanel', { name: 'Sources' })
    const source = within(panel).getByRole('region', { name: /^S1/ })
    expect(within(source).getByRole('heading', { level: 3 })).toHaveTextContent(
      'S1NVIDIA 10-Q, Q2 FY2025 (May–Jul 2024) · MD&A'
    )
    const table = within(source).getByRole('table', { name: 'Table from the passage' })
    const rows = within(table)
      .getAllByRole('row')
      .map((row) =>
        within(row)
          .getAllByRole('cell')
          .map((cell) => cell.textContent)
      )
    expect(rows).toEqual([
      ['Three Months Ended'],
      ['Revenue', '$', '30,040'],
      ['Gross margin', '75.1', '%'],
    ])
    expect(within(source).queryByText(/\|/)).not.toBeInTheDocument()
    expect(within(source).getByRole('separator', { name: 'Passage skipped' })).toBeInTheDocument()
    expect(within(source).getByText('Data Center revenue was a record.')).toBeInTheDocument()
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

describe('The side panel', () => {
  /** A second answer, about Microsoft, with its own Sources. */
  const MSFT_SOURCE = { ...UNCITED_SOURCE, tag: 'S1' }
  const secondAnswer = () =>
    uiMessageStream(
      ['Microsoft faces **trade restrictions** [S1].'],
      { ...QUERY_SCOPE, companies: [{ ticker: 'MSFT', name: 'Microsoft Corp' }] },
      [MSFT_SOURCE],
      [],
      'msg-2'
    )

  const rail = () => screen.getByRole('group', { name: 'Panel toolbar' })
  const railSources = () => within(rail()).getByRole('button', { name: 'Sources' })
  const sidePanel = () => screen.queryByRole('complementary', { name: 'Side panel' })

  /** Asks the first starter, then a follow-up, so the thread holds two answers. */
  async function twoAnswers(user: ReturnType<typeof userEvent.setup>) {
    fetchMock
      .mockImplementationOnce(async () => uiMessageStream())
      .mockImplementationOnce(async () => secondAnswer())
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('trade policy')
    await user.type(screen.getByRole('textbox', { name: 'Question' }), 'And Microsoft?{Enter}')
    await screen.findByText('trade restrictions')
    return screen.getAllByRole('article', { name: 'Answer' })
  }

  it('keeps the toolbar visible, its Sources icon opening and closing the panel', async () => {
    const user = userEvent.setup()
    render(<Workspace />)

    // Visible from the start, before any answer.
    expect(railSources()).toHaveAttribute('aria-pressed', 'false')
    expect(sidePanel()).not.toBeInTheDocument()

    await user.click(railSources())
    expect(sidePanel()).toBeInTheDocument()
    expect(railSources()).toHaveAttribute('aria-pressed', 'true')
    const tab = within(screen.getByRole('tablist', { name: 'Panel tabs' })).getByRole('tab', {
      name: 'Sources',
    })
    expect(tab).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel', { name: 'Sources' })).toHaveTextContent(/No Sources yet/)

    // Clicking the open tab's icon closes the panel.
    await user.click(railSources())
    expect(sidePanel()).not.toBeInTheDocument()
    expect(railSources()).toHaveAttribute('aria-pressed', 'false')
  })

  it("opens from the toolbar at the latest answer's first Source", async () => {
    const user = userEvent.setup()
    render(<Workspace />)
    const [first] = await twoAnswers(user)

    // A citation in the first answer, then closed.
    await user.click(within(first).getByRole('link', { name: 'Source S2' }))
    expect(screen.getByRole('region', { name: /^S2/ })).toHaveTextContent('Tesla')
    await user.click(screen.getByRole('button', { name: 'Close panel' }))
    expect(sidePanel()).not.toBeInTheDocument()

    // The toolbar reopens it at the latest answer's S1.
    await user.click(railSources())
    const panel = screen.getByRole('tabpanel', { name: 'Sources' })
    expect(within(panel).getByRole('region', { name: /^S1/ })).toHaveTextContent(
      'Microsoft 10-K, FY2025 (Jul 2024–Jun 2025) · Risk Factors'
    )
    expect(
      within(within(panel).getByRole('navigation', { name: "This answer's Sources" }))
        .getAllByRole('button')
        .map((tab) => tab.textContent)
    ).toEqual(['S1'])
  })

  it('opens the Sources tab at a citation, whatever the panel shows', async () => {
    const user = userEvent.setup()
    render(<Workspace />)
    const [first, second] = await twoAnswers(user)

    // Open from the toolbar, on the latest answer: a citation in the first answer moves it.
    await user.click(railSources())
    await user.click(within(first).getByRole('link', { name: 'Source S2' }))
    const panel = screen.getByRole('tabpanel', { name: 'Sources' })
    expect(within(panel).getByRole('region', { name: /^S2/ })).toHaveTextContent(
      'Tesla 10-K, FY2025 (Jan–Dec 2025) · Risk Factors'
    )
    expect(railSources()).toHaveAttribute('aria-pressed', 'true')

    // Clicking a citation again keeps the panel open, never toggles it closed.
    await user.click(within(first).getByRole('link', { name: 'Source S2' }))
    expect(sidePanel()).toBeInTheDocument()

    // Closed, a citation in the other answer opens it there.
    await user.click(screen.getByRole('button', { name: 'Close panel' }))
    await user.click(within(second).getByRole('link', { name: 'Source S1' }))
    expect(
      within(screen.getByRole('tabpanel', { name: 'Sources' })).getByRole('region', {
        name: /^S1/,
      })
    ).toHaveTextContent('Microsoft 10-K, FY2025 (Jul 2024–Jun 2025) · Risk Factors')
  })

  it('on a narrow screen, puts the toolbar above the question box and the panel full-screen', async () => {
    const user = userEvent.setup()
    render(<Workspace />)

    // jsdom applies no media queries, so the breakpoint classes are what decide it.
    expect(rail()).toHaveClass('hidden', 'lg:flex')
    const buttons = screen.getByRole('group', { name: 'Panel buttons' })
    expect(buttons).toHaveClass('lg:hidden')
    const input = screen.getByRole('textbox', { name: 'Question' })
    expect(buttons.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    await user.click(within(buttons).getByRole('button', { name: 'Sources' }))
    const panel = sidePanel()
    expect(panel).toHaveClass('fixed', 'inset-0', 'lg:static')
    expect(within(buttons).getByRole('button', { name: 'Sources' })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
    await user.click(screen.getByRole('button', { name: 'Close panel' }))
    expect(sidePanel()).not.toBeInTheDocument()
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
    // The question compared Apple's and Tesla's risks, so that comparison isn't suggested.
    const list = await screen.findByRole('list', { name: 'Suggested follow-ups' })
    expect(suggestionsOf(list)).toEqual([
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
      sections: [],
    }
    const held = heldUiMessageStream((part) => part.type === 'text-delta', ANSWER, second)
    fetchMock
      .mockImplementationOnce(async () => answerStream('msg-0'))
      .mockImplementationOnce(async () => held.response)
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))

    const first = await screen.findByRole('list', { name: 'Suggested follow-ups' })
    const suggestion = 'How does revenue compare between Apple and Tesla in their latest filings?'
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

  it("skips what an earlier question asked, by its answer's Query Scope", async () => {
    const apple = [{ ticker: 'AAPL', name: 'Apple Inc', coverage: 'tracked' }]
    const revenue = { ...QUERY_SCOPE, companies: apple, sections: [], metric: 'revenue' }
    fetchMock
      .mockImplementationOnce(async () =>
        answerStream('msg-0', ANSWER, { ...QUERY_SCOPE, companies: apple })
      )
      .mockImplementationOnce(async () => answerStream('msg-1', ANSWER, revenue))
    const user = userEvent.setup()
    render(<Workspace />)
    await user.type(screen.getByRole('textbox', { name: 'Question' }), "Apple's risks?{Enter}")
    await screen.findByRole('list', { name: 'Suggested follow-ups' })
    await user.type(screen.getByRole('textbox', { name: 'Question' }), 'And its revenue?{Enter}')

    await waitFor(() => expect(screen.getAllByRole('article', { name: 'Answer' })).toHaveLength(2))
    const list = await screen.findByRole('list', { name: 'Suggested follow-ups' })
    // Apple's risks were asked first, its revenue just now: only its outlook is left.
    expect(suggestionsOf(list)).toEqual(["What does Apple's latest filing say about its outlook?"])
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

describe('The Calendar tab', () => {
  /** The committed export's Company Calendars, as the workspace page passes them. */
  const CALENDARS = (evalExport as EvalExport).companies

  const rail = () => screen.getByRole('group', { name: 'Panel toolbar' })
  const railCalendar = () => within(rail()).getByRole('button', { name: 'Calendar' })
  const tickers = () =>
    within(screen.getByRole('navigation', { name: 'Companies asked about' }))
      .getAllByRole('button')
      .map((tab) => tab.textContent)
  const calendarTable = (ticker: string) =>
    screen.getByRole('table', { name: `${ticker} fiscal calendar` })
  /** The table's row for one fiscal period, by its first cell, never its band's heading. */
  const row = (table: HTMLElement, fiscalPeriod: string) =>
    within(table).getByRole('row', { name: new RegExp(`^${fiscalPeriod}\\b.+`) })

  /** Two answers: Apple and Tesla (Microsoft retrieved too, but not in the Query Scope),
   * then NVIDIA and McDonald's. */
  async function twoAnswers(user: ReturnType<typeof userEvent.setup>) {
    fetchMock
      .mockImplementationOnce(async () =>
        uiMessageStream(ANSWER, QUERY_SCOPE, [...SOURCES, UNCITED_SOURCE])
      )
      .mockImplementationOnce(async () =>
        uiMessageStream(
          ['NVIDIA grew **fast** [S1].'],
          {
            ...QUERY_SCOPE,
            companies: [
              { ticker: 'NVDA', name: 'NVIDIA Corp', coverage: 'tracked' },
              { ticker: 'MCD', name: "McDonald's Corp", coverage: 'snapshot' },
            ],
          },
          [FACTS_SOURCE],
          [],
          'msg-2'
        )
      )
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('trade policy')
    await user.type(screen.getByRole('textbox', { name: 'Question' }), 'And NVIDIA?{Enter}')
    await screen.findByText('fast')
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
    )
  }

  it('opens from the calendar icon, and says so when no company has been asked about', async () => {
    const user = userEvent.setup()
    render(<Workspace calendars={CALENDARS} />)

    expect(railCalendar()).toHaveAttribute('aria-pressed', 'false')
    await user.click(railCalendar())
    expect(railCalendar()).toHaveAttribute('aria-pressed', 'true')
    expect(
      within(screen.getByRole('tablist', { name: 'Panel tabs' })).getByRole('tab', {
        name: 'Calendar',
      })
    ).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel', { name: 'Calendar' })).toHaveTextContent(/No companies yet/)

    await user.click(railCalendar())
    expect(screen.queryByRole('complementary', { name: 'Side panel' })).not.toBeInTheDocument()
  })

  it("lists every Query Scope's Companies seen so far as alphabetical ticker tabs", async () => {
    const user = userEvent.setup()
    render(<Workspace calendars={CALENDARS} />)
    await twoAnswers(user)

    // The panel opened on the Calendar after the first answer and followed the second.
    expect(railCalendar()).toHaveAttribute('aria-pressed', 'true')
    // Microsoft was only retrieved as a Source, never in a Query Scope.
    expect(tickers()).toEqual(['AAPL', 'MCD', 'NVDA', 'TSLA'])
    await user.click(screen.getByRole('button', { name: 'AAPL' }))
    expect(
      within(screen.getByRole('navigation', { name: 'Companies asked about' })).getByRole(
        'button',
        { name: 'AAPL' }
      )
    ).toHaveAttribute('aria-pressed', 'true')
    expect(calendarTable('AAPL')).toBeInTheDocument()
  })

  it("shows a ticker's calendar newest first, banded by fiscal year, its revenue traceable", async () => {
    const user = userEvent.setup()
    render(<Workspace calendars={CALENDARS} />)
    await twoAnswers(user)
    await user.click(screen.getByRole('button', { name: 'NVDA' }))

    const panel = screen.getByRole('tabpanel', { name: 'Calendar' })
    expect(panel).toHaveTextContent('Fiscal year ends late January')
    const table = calendarTable('NVDA')

    // Banded by fiscal year, newest first; the calendar months sit beside each period.
    const bands = within(table).getAllByRole('rowgroup').slice(1)
    expect(bands.slice(0, 4).map((band) => band.getAttribute('aria-label'))).toEqual([
      'FY2026',
      'FY2025',
      'FY2024',
      'FY2023',
    ])
    // A fiscal year's band holds its year and its quarters, never the next year's first.
    const fy2025 = within(bands[1])
      .getAllByRole('row')
      .map((r) => r.querySelector('th')?.textContent)
    expect(fy2025).toEqual(['FY2025', 'FY2025', 'Q4 FY2025', 'Q3 FY2025', 'Q2 FY2025', 'Q1 FY2025'])

    const q3 = row(table, 'Q3 FY2026')
    expect(q3).toHaveTextContent('Aug–Oct 2025')
    expect(q3).toHaveTextContent('10-Q')
    expect(within(q3).getByText('$57,006M')).toHaveAttribute(
      'title',
      'NVDA_10-Q_2025-10-26 · Revenue'
    )
    const fy = row(table, 'FY2025')
    expect(fy).toHaveTextContent('Feb 2024–Jan 2025')
    expect(within(fy).getByText('$130,497M')).toHaveAttribute(
      'title',
      'NVDA_10-K_2025-01-26 · Revenue'
    )
    expect(fy).toHaveClass('font-semibold')
    // The fiscal year's row sits beside its fourth quarter, whose revenue is derived.
    const q4 = row(table, 'Q4 FY2025')
    expect(fy.compareDocumentPosition(q4) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(q4).toHaveTextContent('$39,331Mderived')
    expect(within(q4).getByText('$39,331M')).toHaveAttribute(
      'title',
      expect.stringContaining('FY2025 less Q1–Q3 FY2025')
    )
    // Every row, newest first.
    const periods = within(table)
      .getAllByRole('row')
      .slice(1)
      .map((r) => r.querySelector('th[scope="row"]')?.textContent)
      .filter((p) => p && /FY/.test(p))
    expect(periods.slice(0, 5)).toEqual([
      'Q3 FY2026',
      'Q2 FY2026',
      'Q1 FY2026',
      'FY2025',
      'Q4 FY2025',
    ])
  })

  it("greys the periods with no Filing, and shows a Snapshot Company's revenue where its filings give it", async () => {
    const user = userEvent.setup()
    render(<Workspace calendars={CALENDARS} />)
    await twoAnswers(user)
    await user.click(screen.getByRole('button', { name: 'MCD' }))

    const table = calendarTable('MCD')
    expect(within(table).getByRole('columnheader', { name: 'Revenue' })).toBeInTheDocument()
    expect(screen.getByRole('tabpanel', { name: 'Calendar' })).not.toHaveTextContent(
      /couldn’t be read/
    )
    const filed = row(table, 'FY2024')
    expect(filed).toHaveTextContent('10-K')
    expect(within(filed).getByText('$25,920M')).toHaveAttribute(
      'title',
      'MCD_10-K_2024-12-31 · Total revenues'
    )
    expect(filed).not.toHaveClass('text-muted')
    const gap = row(table, 'Q3 FY2024')
    expect(gap).toHaveTextContent('Jul–Sep 2024')
    expect(gap).toHaveTextContent('not in the filings')
    expect(gap).toHaveClass('text-muted')
  })

  it('says so when no revenue figure could be read from a company’s filings', async () => {
    fetchMock.mockImplementationOnce(async () =>
      uiMessageStream(['Target faces **tariffs** [S1].'], {
        ...QUERY_SCOPE,
        companies: [{ ticker: 'TGT', name: 'Target Corp', coverage: 'snapshot' }],
      })
    )
    const user = userEvent.setup()
    render(<Workspace calendars={CALENDARS} />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('tariffs')
    await screen.findByRole('tabpanel', { name: 'Calendar' })

    expect(screen.getByRole('tabpanel', { name: 'Calendar' })).toHaveTextContent(
      'No revenue figure could be read from this company’s filings.'
    )
    expect(
      within(calendarTable('TGT')).queryByRole('columnheader', { name: 'Revenue' })
    ).not.toBeInTheDocument()
  })
})

describe('The Calendar follows the conversation', () => {
  const CALENDARS = (evalExport as EvalExport).companies

  const rail = () => screen.getByRole('group', { name: 'Panel toolbar' })
  const railCalendar = () => within(rail()).getByRole('button', { name: 'Calendar' })
  const buttonsCalendar = () =>
    within(screen.getByRole('group', { name: 'Panel buttons' })).getByRole('button', {
      name: 'Calendar',
    })
  const sidePanel = () => screen.queryByRole('complementary', { name: 'Side panel' })
  const shownTicker = () =>
    within(screen.getByRole('navigation', { name: 'Companies asked about' }))
      .getAllByRole('button')
      .find((tab) => tab.getAttribute('aria-pressed') === 'true')?.textContent

  /** An answer about NVIDIA and McDonald's: two Companies not asked about before. */
  const nvidiaAnswer = (messageId: string) =>
    uiMessageStream(
      ['NVIDIA grew **fast** [S1].'],
      {
        ...QUERY_SCOPE,
        companies: [
          { ticker: 'NVDA', name: 'NVIDIA Corp', coverage: 'tracked' },
          { ticker: 'MCD', name: "McDonald's Corp", coverage: 'snapshot' },
        ],
      },
      [FACTS_SOURCE],
      [],
      messageId
    )
  /** An answer whose Query Scope names no Company, as for the tariffs starter. */
  const tariffsAnswer = (messageId: string) =>
    uiMessageStream(
      ['No Company is named, so **every filing** was searched.'],
      { ...QUERY_SCOPE, companies: [] },
      SOURCES,
      [],
      messageId
    )

  /** Types a question and waits for its answer, with `text` in it, to complete. */
  async function ask(user: ReturnType<typeof userEvent.setup>, question: string, text: string) {
    const before = screen.queryAllByText(text).length
    await user.type(screen.getByRole('textbox', { name: 'Question' }), `${question}{Enter}`)
    await waitFor(() => {
      expect(screen.getAllByText(text)).toHaveLength(before + 1)
      expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
    })
  }

  it("opens on the Calendar as soon as the first answer's Query Scope arrives, before its text", async () => {
    const { response, release } = heldUiMessageStream((part) => part.type === 'data-query-scope')
    fetchMock.mockImplementation(async () => response)
    const user = userEvent.setup()
    render(<Workspace calendars={CALENDARS} />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))

    // Only the Query Scope has arrived: the Calendar already shows its Companies.
    expect(await screen.findByRole('tabpanel', { name: 'Calendar' })).toBeInTheDocument()
    expect(screen.queryByText(/trade policy/)).not.toBeInTheDocument()
    expect(railCalendar()).toHaveAttribute('aria-pressed', 'true')
    // Apple and Tesla: the alphabetically first is shown.
    expect(shownTicker()).toBe('AAPL')

    release()
    await screen.findByText(/trade policy/)
    expect(shownTicker()).toBe('AAPL')
  })

  it("shows the streaming answer's Sources when the Sources tab is chosen, before any citation", async () => {
    const { response, release } = heldUiMessageStream((part) => part.type === 'text-delta')
    fetchMock.mockImplementation(async () => response)
    const user = userEvent.setup()
    render(<Workspace calendars={CALENDARS} />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByRole('tabpanel', { name: 'Calendar' })

    // The answer is still streaming; the Sources tab shows its Sources at the first.
    await user.click(
      within(screen.getByRole('tablist', { name: 'Panel tabs' })).getByRole('tab', {
        name: 'Sources',
      })
    )
    const panel = screen.getByRole('tabpanel', { name: 'Sources' })
    expect(panel).not.toHaveTextContent(/No Sources yet/)
    expect(
      within(within(panel).getByRole('navigation', { name: "This answer's Sources" }))
        .getAllByRole('button')
        .map((tab) => tab.textContent)
    ).toEqual(['S1', 'S2'])
    expect(within(panel).getByRole('region', { name: /^S1/ })).toHaveTextContent('Apple')

    // A Source opens from the panel while the answer is written.
    await user.click(within(panel).getByRole('button', { name: 'S2' }))
    expect(within(panel).getByRole('region', { name: /^S2/ })).toHaveTextContent('Tesla')
    release()
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
    )
  })

  it('stays closed once closed, through "New conversation" and a refresh; the rail reopens it', async () => {
    fetchMock
      .mockImplementationOnce(async () => uiMessageStream())
      .mockImplementationOnce(async () => nvidiaAnswer('msg-2'))
      .mockImplementationOnce(async () =>
        uiMessageStream(ANSWER, QUERY_SCOPE, SOURCES, [], 'msg-3')
      )
      .mockImplementationOnce(async () =>
        uiMessageStream(ANSWER, QUERY_SCOPE, SOURCES, [], 'msg-4')
      )
    const user = userEvent.setup()
    const { unmount } = render(<Workspace calendars={CALENDARS} />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByRole('tabpanel', { name: 'Calendar' })

    await user.click(screen.getByRole('button', { name: 'Close panel' }))
    await ask(user, 'And NVIDIA?', 'fast')
    expect(sidePanel()).not.toBeInTheDocument()

    // A new conversation's first answer naming a Company doesn't reopen it either.
    await user.click(screen.getByRole('button', { name: 'New conversation' }))
    await ask(user, 'Compare Apple and Tesla', 'trade policy')
    expect(sidePanel()).not.toBeInTheDocument()

    // Nor after a refresh in the same browser session.
    await user.click(screen.getByRole('button', { name: 'New conversation' }))
    unmount()
    render(<Workspace calendars={CALENDARS} />)
    await ask(user, 'Compare Apple and Tesla', 'trade policy')
    expect(sidePanel()).not.toBeInTheDocument()

    // The rail is the way back.
    await user.click(railCalendar())
    expect(screen.getByRole('tabpanel', { name: 'Calendar' })).toBeInTheDocument()
    expect(shownTicker()).toBe('AAPL')
  })

  it('closing it from its toolbar icon turns auto-open off too', async () => {
    fetchMock
      .mockImplementationOnce(async () => uiMessageStream())
      .mockImplementationOnce(async () =>
        uiMessageStream(ANSWER, QUERY_SCOPE, SOURCES, [], 'msg-2')
      )
    const user = userEvent.setup()
    render(<Workspace calendars={CALENDARS} />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByRole('tabpanel', { name: 'Calendar' })

    await user.click(railCalendar())
    await user.click(screen.getByRole('button', { name: 'New conversation' }))
    await ask(user, 'Compare Apple and Tesla', 'trade policy')
    expect(sidePanel()).not.toBeInTheDocument()
  })

  it("follows each new answer's alphabetically first Company while it shows; citations still open Sources", async () => {
    fetchMock
      .mockImplementationOnce(async () => uiMessageStream())
      .mockImplementationOnce(async () => nvidiaAnswer('msg-2'))
      .mockImplementationOnce(async () => tariffsAnswer('msg-3'))
      .mockImplementationOnce(async () =>
        uiMessageStream(ANSWER, QUERY_SCOPE, SOURCES, [], 'msg-4')
      )
    const user = userEvent.setup()
    render(<Workspace calendars={CALENDARS} />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByRole('tabpanel', { name: 'Calendar' })
    await user.click(screen.getByRole('button', { name: 'TSLA' }))
    expect(shownTicker()).toBe('TSLA')

    // NVIDIA and McDonald's: McDonald's comes first.
    await ask(user, 'And NVIDIA?', 'fast')
    expect(shownTicker()).toBe('MCD')

    // An answer naming no Company leaves the shown Company alone.
    await ask(user, 'Which companies are most exposed to tariffs?', 'every filing')
    expect(shownTicker()).toBe('MCD')

    // A citation opens Sources, and the next answer leaves it there.
    const answers = screen.getAllByRole('article', { name: 'Answer' })
    await user.click(within(answers[1]).getByRole('link', { name: 'Source S1' }))
    expect(screen.getByRole('tabpanel', { name: 'Sources' })).toBeInTheDocument()
    await ask(user, 'Compare Apple and Tesla again', 'trade policy')
    expect(screen.getByRole('tabpanel', { name: 'Sources' })).toBeInTheDocument()
  })

  it('puts a dot on the calendar icon when an answer adds Companies while closed, until the Calendar opens', async () => {
    fetchMock
      .mockImplementationOnce(async () => uiMessageStream())
      .mockImplementationOnce(async () =>
        uiMessageStream(ANSWER, QUERY_SCOPE, SOURCES, [], 'msg-2')
      )
      .mockImplementationOnce(async () => nvidiaAnswer('msg-3'))
    const user = userEvent.setup()
    render(<Workspace calendars={CALENDARS} />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByRole('tabpanel', { name: 'Calendar' })
    await user.click(screen.getByRole('button', { name: 'Close panel' }))
    expect(railCalendar()).not.toHaveAccessibleDescription(/new companies/)

    // The same Companies again add nothing.
    await ask(user, 'Compare Apple and Tesla again', 'trade policy')
    expect(railCalendar()).not.toHaveAccessibleDescription(/new companies/)

    await ask(user, 'And NVIDIA?', 'fast')
    expect(sidePanel()).not.toBeInTheDocument()
    expect(railCalendar()).toHaveAccessibleDescription(/new companies/)
    expect(buttonsCalendar()).toHaveAccessibleDescription(/new companies/)

    // Opening Sources leaves the dot; opening the Calendar clears it.
    await user.click(within(rail()).getByRole('button', { name: 'Sources' }))
    expect(railCalendar()).toHaveAccessibleDescription(/new companies/)
    await user.click(
      within(screen.getByRole('tablist', { name: 'Panel tabs' })).getByRole('tab', {
        name: 'Calendar',
      })
    )
    expect(railCalendar()).not.toHaveAccessibleDescription(/new companies/)
    expect(buttonsCalendar()).not.toHaveAccessibleDescription(/new companies/)
  })

  it('neither opens nor adds tickers for an answer whose Query Scope names no Company', async () => {
    fetchMock.mockImplementationOnce(async () => tariffsAnswer('msg-1'))
    const user = userEvent.setup()
    render(<Workspace calendars={CALENDARS} />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('every filing')

    expect(sidePanel()).not.toBeInTheDocument()
    expect(railCalendar()).not.toHaveAccessibleDescription(/new companies/)
    await user.click(railCalendar())
    expect(screen.getByRole('tabpanel', { name: 'Calendar' })).toHaveTextContent(/No companies yet/)
  })
})
