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
import { WHATS_COVERED_ID, type CoverageSummary } from '@/lib/coverage'
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
 * it, so an old Query Scope can't leak into a new topic. With a Corpus coverage summary,
 * the empty conversation also says how many Companies are covered.
 */
export default function Workspace({ coverage }: { coverage?: CoverageSummary }) {
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
    <div className="flex h-dvh flex-col text-ink">
      <header className="flex shrink-0 items-center gap-3 border-b border-line bg-canvas/80 px-4 py-2.5 backdrop-blur-xl sm:gap-4 sm:px-5">
        <h1 className="text-[15px] font-semibold tracking-tight whitespace-nowrap text-ink">
          SEC Filings Research<span className="text-accent">.</span>
        </h1>
        <p className="hidden font-mono text-[11px] tracking-widest text-muted lg:block">
          Answers from 10-K and 10-Q Filings, every claim cited to its passage
        </p>
        <button
          type="button"
          onClick={newConversation}
          disabled={messages.length === 0}
          aria-label="New conversation"
          className="btn-secondary ml-auto px-3 py-1.5 text-[13px] whitespace-nowrap"
        >
          New<span className="hidden sm:inline"> conversation</span>
        </button>
        <Link
          href="/how-it-works"
          className="text-[13px] whitespace-nowrap text-muted transition-colors duration-200 hover:text-ink"
        >
          How it works
        </Link>
      </header>

      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto flex max-w-3xl flex-col gap-6 px-5 py-8">
              {messages.length === 0 ? (
                <EmptyState disabled={busy} onPick={ask} coverage={coverage} />
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
                  className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[14px] text-red-200"
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
            className="shrink-0 border-t border-line bg-canvas/80 px-5 py-3 backdrop-blur-xl"
          >
            <div className="mx-auto flex max-w-3xl gap-2">
              <input
                type="text"
                aria-label="Question"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask about a Company's risks, results or outlook…"
                className="h-10 min-w-0 flex-1 rounded-lg border border-line bg-white/[0.04] px-4 text-[14px] text-ink transition-all duration-150 outline-none placeholder:text-muted/60 focus:border-accent/50 focus:bg-white/[0.06] focus:shadow-[0_0_0_3px_rgba(14,165,233,0.15)]"
              />
              {busy ? (
                <button
                  type="button"
                  onClick={stop}
                  className="btn-secondary h-10 px-5 text-[14px]"
                >
                  Stop
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!input.trim()}
                  className="btn-primary h-10 px-5 text-[14px]"
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

function EmptyState({
  disabled,
  onPick,
  coverage,
}: {
  disabled: boolean
  onPick: (q: string) => void
  coverage?: CoverageSummary
}) {
  return (
    <section className="flex flex-col gap-6 pt-10">
      <div>
        <div className="mb-4 flex items-center gap-3">
          <span className="h-px w-10 bg-accent/50" aria-hidden="true" />
          <span className="font-mono text-[11px] tracking-widest text-accent">
            10-K and 10-Q research
          </span>
        </div>
        <h2 className="headline text-3xl font-semibold tracking-[-0.03em] md:text-4xl">
          Ask a question about a Company
        </h2>
        <p className="mt-3 max-w-xl text-[14.5px] leading-relaxed text-muted">
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
              className="card h-full w-full px-4 py-3.5 text-left text-[14px] text-ink transition-all duration-200 hover:border-accent/40 hover:shadow-[0_0_0_1px_rgba(14,165,233,0.15),0_4px_24px_rgba(14,165,233,0.12)] disabled:opacity-50"
            >
              {starter.label}
            </button>
          </li>
        ))}
      </ul>
      {coverage && <CoverageLine coverage={coverage} />}
    </section>
  )
}

/** How many Companies are covered and how many have a trend's worth of history, in plain words. */
function CoverageLine({ coverage }: { coverage: CoverageSummary }) {
  const count = coverage.companies.length
  return (
    <p className="text-[13.5px] text-muted">
      {count} {count === 1 ? 'company' : 'companies'} covered · {coverage.tracked} with two or more
      years of quarterly filings ·{' '}
      <Link
        href={`/how-it-works#${WHATS_COVERED_ID}`}
        className="text-accent underline-offset-2 transition-colors duration-200 hover:underline"
      >
        See what’s covered
      </Link>
    </p>
  )
}

function UserMessage({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] rounded-xl bg-accent/15 px-4 py-2.5 text-[14px] break-words whitespace-pre-wrap text-ink shadow-[inset_0_0_0_1px_rgba(14,165,233,0.25)]">
        {text}
      </p>
    </div>
  )
}

function Progress({ text }: { text: string }) {
  return (
    <p
      role="status"
      className="flex items-center gap-2.5 font-mono text-[12px] tracking-wide text-muted"
    >
      <span className="relative flex h-2 w-2" aria-hidden="true">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-75" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
      </span>
      {text}
    </p>
  )
}
