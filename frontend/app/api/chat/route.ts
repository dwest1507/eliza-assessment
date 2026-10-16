/**
 * The proxy to the chat API. The browser posts `useChat`'s request here, so the
 * backend's URL stays on the server: it comes from `BACKEND_URL` (see `.env.example`),
 * defaulting to the API `make api` runs locally.
 *
 * Only each message's role and text are forwarded: an earlier answer's Sources are
 * not evidence for the next question (the backend retrieves afresh), and resending
 * their passages would only make every follow-up heavier. The backend's AI SDK UI
 * message stream is passed through untouched, and so are its validation statuses.
 */

const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8000'

interface IncomingMessage {
  role?: unknown
  parts?: unknown
}

export async function POST(request: Request): Promise<Response> {
  let body: { messages?: unknown }
  try {
    body = await request.json()
  } catch {
    return Response.json({ detail: 'The request body is not JSON.' }, { status: 400 })
  }
  if (!Array.isArray(body?.messages)) {
    return Response.json({ detail: 'The request has no messages.' }, { status: 400 })
  }
  const messages = (body.messages as IncomingMessage[]).map((m) => ({
    role: m.role,
    content: textOf(m.parts),
  }))

  let backend: Response
  try {
    backend = await fetch(`${backendUrl()}/api/chat`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ messages }),
      signal: request.signal,
    })
  } catch {
    return Response.json({ detail: 'The research API is not reachable.' }, { status: 502 })
  }

  if (!backend.ok || !backend.body) {
    const status = backend.ok ? 502 : backend.status
    return new Response(await backend.text(), {
      status,
      headers: { 'content-type': backend.headers.get('content-type') ?? 'text/plain' },
    })
  }

  return new Response(backend.body, {
    headers: {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache',
      'x-accel-buffering': 'no',
      'x-vercel-ai-ui-message-stream': 'v1',
    },
  })
}

function backendUrl(): string {
  return (process.env.BACKEND_URL || DEFAULT_BACKEND_URL).replace(/\/+$/, '')
}

function textOf(parts: unknown): string {
  if (!Array.isArray(parts)) return ''
  return parts
    .filter((p) => p?.type === 'text' && typeof p.text === 'string')
    .map((p) => p.text as string)
    .join('')
}
