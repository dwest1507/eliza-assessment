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

function uiMessageStream(answer: string[] = ANSWER): Response {
  const parts = [
    { type: 'start', messageId: 'msg-1' },
    {
      type: 'data-query-scope',
      data: { companies: [{ ticker: 'AAPL', name: 'Apple Inc.', coverage: 'tracked' }] },
    },
    { type: 'data-sources', data: { sources: SOURCES } },
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

  it('says so when the answer cannot be loaded, without leaking the error', async () => {
    fetchMock.mockImplementation(async () => new Response('backend exploded', { status: 502 }))
    const user = userEvent.setup()
    render(<Workspace />)

    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))

    expect(await screen.findByRole('alert')).toHaveTextContent('The answer could not be loaded')
    expect(screen.queryByText(/exploded/)).not.toBeInTheDocument()
  })
})
