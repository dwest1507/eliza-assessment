import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Workspace from '@/components/Workspace'
import { STARTERS } from '@/lib/starters'

/**
 * How the thread scrolls: once when a question is sent, never while its answer streams,
 * and on demand through "Jump to latest". jsdom has no layout, so these tests stub the
 * browser APIs the workspace scrolls and watches with (`scrollIntoView`, set up in
 * `vitest.setup.ts`, `IntersectionObserver` and `matchMedia`) and assert the calls the
 * user would see as movement.
 */

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
]

const QUERY_SCOPE = {
  companies: [{ ticker: 'AAPL', name: 'Apple Inc', coverage: 'tracked' }],
  sectorPhrases: [],
  timeWindow: { kind: 'latest', count: null, label: 'latest' },
  sections: ['Risk Factors'],
  metric: null,
}

const HEAD = [
  { type: 'start', messageId: 'msg-1' },
  { type: 'data-query-scope', data: QUERY_SCOPE },
  { type: 'data-sources', data: { sources: SOURCES } },
  { type: 'data-coverage-gaps', data: { gaps: [] } },
  { type: 'start-step' },
  { type: 'text-start', id: 'text-1' },
]
const delta = (text: string) => ({ type: 'text-delta', id: 'text-1', delta: text })
const TAIL = [{ type: 'text-end', id: 'text-1' }, { type: 'finish-step' }, { type: 'finish' }]

/** A UI message stream the test feeds part by part, so it can look in mid-answer. */
function heldStream() {
  const encoder = new TextEncoder()
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c
    },
  })
  return {
    response: new Response(stream, {
      headers: { 'content-type': 'text/event-stream', 'x-vercel-ai-ui-message-stream': 'v1' },
    }),
    push(...parts: object[]) {
      for (const part of parts)
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(part)}\n\n`))
    },
    close() {
      controller.enqueue(encoder.encode('data: [DONE]\n\n'))
      controller.close()
    },
  }
}

/** The whole answer in one go. */
function wholeStream(): Response {
  const held = heldStream()
  held.push(...HEAD, delta('Apple depends on **outsourcing partners** [S1].'), ...TAIL)
  held.close()
  return held.response
}

/** A stand-in for the browser's IntersectionObserver that the test drives by hand. */
class FakeIntersectionObserver {
  static latest: FakeIntersectionObserver | null = null
  readonly targets: Element[] = []
  constructor(
    readonly callback: IntersectionObserverCallback,
    readonly options?: IntersectionObserverInit
  ) {
    FakeIntersectionObserver.latest = this
  }
  observe(target: Element) {
    this.targets.push(target)
  }
  unobserve() {}
  disconnect() {
    this.targets.length = 0
  }
  takeRecords() {
    return []
  }
}

/** Reports where the end of the thread is: in view, below the visible area, or above it. */
function reportEnd(where: 'visible' | 'below' | 'above') {
  const observer = FakeIntersectionObserver.latest
  if (!observer || observer.targets.length === 0) throw new Error('nothing is observed')
  const top = { visible: 400, below: 1600, above: -600 }[where]
  const entries = observer.targets.map((target) => ({
    target,
    isIntersecting: where === 'visible',
    boundingClientRect: { top, bottom: top + 1 },
    rootBounds: { top: 0, bottom: 800 },
  }))
  act(() => observer.callback(entries as unknown as IntersectionObserverEntry[], observer as never))
}

const scrollIntoView = vi.mocked(HTMLElement.prototype.scrollIntoView)
const fetchMock = vi.fn()

function stubReducedMotion(reduce: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: reduce && query === '(prefers-reduced-motion: reduce)',
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    }))
  )
}

beforeEach(() => {
  sessionStorage.clear()
  scrollIntoView.mockClear()
  fetchMock.mockReset()
  fetchMock.mockImplementation(async () => wholeStream())
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver)
  FakeIntersectionObserver.latest = null
  stubReducedMotion(false)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

/** Each scroll so far: the text of the element scrolled into view, and how. */
function scrolls() {
  return scrollIntoView.mock.calls.map((args, i) => ({
    text: (scrollIntoView.mock.contexts[i] as HTMLElement).textContent,
    options: args[0],
  }))
}

describe('Workspace scrolling', () => {
  it('scrolls once on send, to put the question at the top, and not while the answer streams', async () => {
    const held = heldStream()
    fetchMock.mockImplementation(async () => held.response)
    const user = userEvent.setup()
    render(<Workspace />)

    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText(STARTERS[0].question)
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1))
    expect(scrolls()).toEqual([
      { text: STARTERS[0].question, options: { behavior: 'smooth', block: 'start' } },
    ])

    held.push(...HEAD, delta('Apple depends on '))
    await screen.findByText(/Apple depends on/)
    held.push(delta('**outsourcing partners** [S1]. '), delta('More detail follows.'))
    await screen.findByText(/More detail follows/)
    held.push(...TAIL)
    held.close()
    await screen.findByRole('button', { name: 'Ask' })

    expect(scrollIntoView).toHaveBeenCalledTimes(1)
  })

  it('scrolls once to a typed question too', async () => {
    const user = userEvent.setup()
    render(<Workspace />)

    await user.type(screen.getByRole('textbox', { name: 'Question' }), 'Apple risks?{Enter}')
    await screen.findByText('outsourcing partners')

    expect(scrolls()).toEqual([
      { text: 'Apple risks?', options: { behavior: 'smooth', block: 'start' } },
    ])
  })

  it('scrolls without animation when the user prefers reduced motion', async () => {
    stubReducedMotion(true)
    const user = userEvent.setup()
    render(<Workspace />)

    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('outsourcing partners')

    expect(scrolls()).toEqual([
      { text: STARTERS[0].question, options: { behavior: 'auto', block: 'start' } },
    ])
  })

  it('opens a restored conversation at its last question', async () => {
    const text = (t: string) => [{ type: 'text', text: t }]
    sessionStorage.setItem(
      'sec-filings-research:conversation',
      JSON.stringify([
        { id: 'u1', role: 'user', parts: text('First question?') },
        { id: 'a1', role: 'assistant', parts: text('First answer.') },
        { id: 'u2', role: 'user', parts: text('Second question?') },
        { id: 'a2', role: 'assistant', parts: text('Second answer.') },
      ])
    )
    render(<Workspace />)

    await screen.findByText('Second answer.')
    expect(scrolls()).toEqual([
      { text: 'Second question?', options: { behavior: 'auto', block: 'start' } },
    ])
  })

  it('offers "Jump to latest" while the end of the thread is below the visible area', async () => {
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('outsourcing partners')
    scrollIntoView.mockClear()

    expect(screen.queryByRole('button', { name: 'Jump to latest' })).not.toBeInTheDocument()

    reportEnd('below')
    await user.click(screen.getByRole('button', { name: 'Jump to latest' }))
    expect(scrollIntoView).toHaveBeenCalledTimes(1)
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'end' })
    expect(scrollIntoView.mock.contexts[0]).toBe(FakeIntersectionObserver.latest?.targets[0])

    reportEnd('visible')
    expect(screen.queryByRole('button', { name: 'Jump to latest' })).not.toBeInTheDocument()

    // Out of view above (the reader is past the end, in the room left for the answer):
    // there is nothing below to jump to.
    reportEnd('above')
    expect(screen.queryByRole('button', { name: 'Jump to latest' })).not.toBeInTheDocument()
  })

  it('watches the end of the thread within the thread’s scroll area', async () => {
    const user = userEvent.setup()
    render(<Workspace />)
    await user.click(screen.getByRole('button', { name: STARTERS[0].label }))
    await screen.findByText('outsourcing partners')

    const observer = FakeIntersectionObserver.latest
    const root = observer?.options?.root as HTMLElement
    expect(root).toBeInstanceOf(HTMLElement)
    expect(root).toContainElement(screen.getByText('outsourcing partners'))
    expect(root).not.toContainElement(screen.getByRole('textbox', { name: 'Question' }))
  })
})
