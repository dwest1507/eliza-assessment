// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { POST } from '@/app/api/chat/route'

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  vi.stubEnv('BACKEND_URL', 'http://backend.test:9000/')
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

function chatRequest(body: unknown): Request {
  return new Request('http://localhost:3000/api/chat', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
}

const conversation = {
  id: 'chat-1',
  trigger: 'submit-message',
  messages: [
    { id: 'm1', role: 'user', parts: [{ type: 'text', text: 'Compare Apple and Tesla' }] },
    {
      id: 'm2',
      role: 'assistant',
      parts: [
        { type: 'data-sources', data: { sources: [{ tag: 'S1', text: 'a long passage' }] } },
        { type: 'step-start' },
        { type: 'text', text: 'Apple faces ' },
        { type: 'text', text: 'tariffs [S1].' },
      ],
    },
    { id: 'm3', role: 'user', parts: [{ type: 'text', text: 'And Microsoft?' }] },
  ],
}

describe('POST /api/chat (proxy)', () => {
  it('forwards the conversation text to the configured backend', async () => {
    fetchMock.mockResolvedValue(new Response('data: [DONE]\n\n'))

    await POST(chatRequest(conversation))

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('http://backend.test:9000/api/chat')
    expect(init.method).toBe('POST')
    // Only the text goes back: earlier Sources would only make the request heavier.
    expect(JSON.parse(init.body)).toEqual({
      messages: [
        { role: 'user', content: 'Compare Apple and Tesla' },
        { role: 'assistant', content: 'Apple faces tariffs [S1].' },
        { role: 'user', content: 'And Microsoft?' },
      ],
    })
  })

  it('streams the backend response through as a UI message stream', async () => {
    const body = 'data: {"type":"start"}\n\ndata: [DONE]\n\n'
    fetchMock.mockResolvedValue(
      new Response(body, {
        headers: { 'content-type': 'text/event-stream', 'x-vercel-ai-ui-message-stream': 'v1' },
      })
    )

    const response = await POST(chatRequest(conversation))

    expect(response.status).toBe(200)
    expect(response.headers.get('x-vercel-ai-ui-message-stream')).toBe('v1')
    expect(response.headers.get('content-type')).toContain('text/event-stream')
    expect(await response.text()).toBe(body)
  })

  it('passes a validation error from the backend through', async () => {
    fetchMock.mockResolvedValue(
      Response.json({ detail: 'The question is empty.' }, { status: 400 })
    )

    const response = await POST(chatRequest(conversation))

    expect(response.status).toBe(400)
  })

  it('answers 502 when the backend is not reachable', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'))

    const response = await POST(chatRequest(conversation))

    expect(response.status).toBe(502)
  })

  it('rejects a body without messages with 400 and does not call the backend', async () => {
    const response = await POST(chatRequest({ id: 'chat-1' }))

    expect(response.status).toBe(400)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('defaults to the local API when no backend URL is configured', async () => {
    vi.stubEnv('BACKEND_URL', '')
    fetchMock.mockResolvedValue(new Response('data: [DONE]\n\n'))

    await POST(chatRequest(conversation))

    expect(fetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8000/api/chat')
  })
})
