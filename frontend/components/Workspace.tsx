'use client'

import { useEffect, useRef, useState, type FormEvent } from 'react'
import Link from 'next/link'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import AnswerMessage from '@/components/AnswerMessage'
import SourcesPanel from '@/components/SourcesPanel'
import {
  messageDataPart,
  messageSources,
  messageText,
  rejectionReason,
  type ResearchMessage,
} from '@/lib/chat'
import { loadConversation, saveConversation } from '@/lib/conversation'
import { STARTERS } from '@/lib/starters'

/** Which answer's Sources the panel shows, and which of them is open. */
interface OpenSource {
  messageId: string
  tag: string
}

/**
 * The research workspace: a conversation thread, starter prompts on an empty
 * conversation, and a Sources panel that opens on a citation click. The conversation is
 * kept in session storage, so it survives a page refresh, and "New conversation" clears
 * it, so an old Query Scope can't leak into a new topic.
 */
export default function Workspace() {
  const [transport] = useState(
    () => new DefaultChatTransport<ResearchMessage>({ api: '/api/chat' })
  )
  const { messages, sendMessage, setMessages, status, stop, error } = useChat<ResearchMessage>({
    transport,
  })
  const [input, setInput] = useState('')
  const [open, setOpen] = useState<OpenSource | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  const busy = status === 'submitted' || status === 'streaming'

  // Session storage is read after the first render, so the server-rendered page (which
  // has no storage) and the browser's first render agree.
  useEffect(() => {
    const saved = loadConversation()
    if (saved.length > 0) setMessages(saved)
  }, [setMessages])

  // Saved once each answer is complete, never half-written. Only "New conversation"
  // clears it, so the empty first render never overwrites a saved conversation.
  useEffect(() => {
    if (!busy && messages.length > 0) saveConversation(messages)
  }, [messages, busy])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, status])

  function ask(question: string) {
    const text = question.trim()
    if (!text || busy) return
    sendMessage({ text })
  }

  function newConversation() {
    if (busy) stop()
    setMessages([])
    saveConversation([])
    setOpen(null)
    setInput('')
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!input.trim() || busy) return
    ask(input)
    setInput('')
  }

  const openMessage = open ? messages.find((m) => m.id === open.messageId) : undefined
  const openSources = openMessage ? messageSources(openMessage) : []
  const last = messages.at(-1)
  const writing = status === 'streaming' && last?.role === 'assistant' && !messageText(last)

  return (
    <div className="flex h-dvh flex-col bg-canvas text-ink">
      <header className="flex shrink-0 items-baseline gap-3 border-b border-line bg-white px-5 py-3">
        <h1 className="text-[15px] font-semibold tracking-tight">SEC Filings Research</h1>
        <p className="hidden text-[13px] text-muted sm:block">
          Answers from 10-K and 10-Q Filings, every claim cited to its passage
        </p>
        <button
          type="button"
          onClick={newConversation}
          disabled={messages.length === 0}
          className="ml-auto rounded-md border border-line px-3 py-1 text-[13px] font-medium text-ink hover:bg-canvas disabled:opacity-40"
        >
          New conversation
        </button>
        <Link
          href="/how-it-works"
          className="text-[13px] font-medium text-accent hover:text-accent-strong"
        >
          How it works
        </Link>
      </header>

      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto flex max-w-3xl flex-col gap-6 px-5 py-8">
              {messages.length === 0 ? (
                <EmptyState disabled={busy} onPick={ask} />
              ) : (
                messages.map((message) =>
                  message.role === 'user' ? (
                    <UserMessage key={message.id} text={messageText(message)} />
                  ) : (
                    <AnswerMessage
                      key={message.id}
                      text={messageText(message)}
                      sources={messageSources(message)}
                      scope={messageDataPart(message, 'query-scope')}
                      gaps={messageDataPart(message, 'coverage-gaps')?.gaps ?? []}
                      openTag={open?.messageId === message.id ? open.tag : null}
                      onCite={(tag) => setOpen({ messageId: message.id, tag })}
                    />
                  )
                )
              )}

              {status === 'submitted' && <Progress text="Retrieving Sources…" />}
              {writing && <Progress text="Writing the answer…" />}

              {status === 'error' && (
                <div
                  role="alert"
                  className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-[14px] text-red-800"
                >
                  {rejectionReason(error) ?? (
                    <>
                      The answer could not be loaded. Check that the API is running (
                      <code className="font-mono text-[13px]">make dev</code>) and try again.
                    </>
                  )}
                </div>
              )}
              <div ref={endRef} />
            </div>
          </div>

          <form
            onSubmit={handleSubmit}
            className="shrink-0 border-t border-line bg-white px-5 py-3"
          >
            <div className="mx-auto flex max-w-3xl gap-2">
              <input
                type="text"
                aria-label="Question"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask about a Company's risks, results or outlook…"
                className="min-w-0 flex-1 rounded-md border border-line bg-white px-3 py-2 text-[14px] outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/20"
              />
              {busy ? (
                <button
                  type="button"
                  onClick={stop}
                  className="rounded-md border border-line px-4 py-2 text-[14px] font-medium text-ink hover:bg-canvas"
                >
                  Stop
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!input.trim()}
                  className="rounded-md bg-accent px-4 py-2 text-[14px] font-medium text-white hover:bg-accent-strong disabled:opacity-40"
                >
                  Ask
                </button>
              )}
            </div>
          </form>
        </main>

        {open && openSources.length > 0 && (
          <SourcesPanel
            sources={openSources}
            selected={open.tag}
            onSelect={(tag) => setOpen({ ...open, tag })}
            onClose={() => setOpen(null)}
          />
        )}
      </div>
    </div>
  )
}

function EmptyState({ disabled, onPick }: { disabled: boolean; onPick: (q: string) => void }) {
  return (
    <section className="flex flex-col gap-5 pt-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">Ask a question about a Company</h2>
        <p className="mt-1 text-[14px] text-muted">
          Name Companies by name or ticker. Each answer cites the Filing Sections it rests on and
          says what the Filings cannot answer.
        </p>
      </div>
      <ul aria-label="Starter prompts" className="grid gap-2 sm:grid-cols-2">
        {STARTERS.map((starter) => (
          <li key={starter.caseId}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onPick(starter.question)}
              title={starter.question}
              className="h-full w-full rounded-md border border-line bg-white px-4 py-3 text-left text-[14px] text-ink shadow-xs transition-colors hover:border-accent hover:bg-accent/5 disabled:opacity-50"
            >
              {starter.label}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function UserMessage({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] rounded-lg bg-accent/8 px-4 py-2.5 text-[14px] break-words whitespace-pre-wrap text-ink">
        {text}
      </p>
    </div>
  )
}

function Progress({ text }: { text: string }) {
  return (
    <p role="status" className="flex items-center gap-2 text-[13px] text-muted">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden="true" />
      {text}
    </p>
  )
}
