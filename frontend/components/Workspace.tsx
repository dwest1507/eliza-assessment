'use client'

import { useEffect, useMemo, useRef, useState, type FormEvent, type Ref } from 'react'
import Link from 'next/link'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import AnswerMessage from '@/components/AnswerMessage'
import CalendarPanel from '@/components/CalendarPanel'
import FollowUps from '@/components/FollowUps'
import SidePanel, { PanelToolbar, type PanelTab } from '@/components/SidePanel'
import SourcesPanel from '@/components/SourcesPanel'
import {
  answerComplete,
  citedSources,
  messageDataPart,
  messageSources,
  messageText,
  rejectionReason,
  type ResearchMessage,
} from '@/lib/chat'
import { loadConversation, saveConversation } from '@/lib/conversation'
import { ASK_PARAM, WHATS_COVERED_ID, type CoverageSummary } from '@/lib/coverage'
import type { CompanyCalendar } from '@/lib/evalExport'
import { followUps } from '@/lib/followUps'
import { STARTERS } from '@/lib/starters'

/** Which answer's Sources the panel's Sources tab shows, and which of them is open. */
interface OpenSource {
  messageId: string
  tag: string | null
}

/**
 * The research workspace: a conversation thread, starter prompts on an empty
 * conversation, and one right-hand side panel with a toolbar that is always visible. A
 * citation click opens the panel's Sources tab at that Source; the toolbar's Sources icon
 * opens it at the latest answer's first Source, or closes it. The conversation is
 * kept in session storage, so it survives a page refresh, and "New conversation" clears
 * it, so an old Query Scope can't leak into a new topic. With a Corpus coverage summary,
 * the empty conversation also says how many Companies are covered. The latest answer,
 * once complete, is followed by suggested follow-up questions. The toolbar's Calendar
 * icon opens the panel's Calendar tab: a ticker tab for every Company the conversation's
 * Query Scopes named, each showing its Company Calendar from `calendars`.
 */
export default function Workspace({
  coverage,
  calendars = [],
}: {
  coverage?: CoverageSummary
  calendars?: CompanyCalendar[]
}) {
  const [transport] = useState(
    () => new DefaultChatTransport<ResearchMessage>({ api: '/api/chat' })
  )
  const { messages, sendMessage, regenerate, setMessages, status, stop, error } =
    useChat<ResearchMessage>({
      transport,
    })
  const [input, setInput] = useState('')
  // The tab the side panel shows, or null while it is closed.
  const [panel, setPanel] = useState<PanelTab | null>(null)
  const [open, setOpen] = useState<OpenSource | null>(null)
  // The ticker the Calendar tab shows, or null for its first.
  const [calendarTicker, setCalendarTicker] = useState<string | null>(null)
  const calendarsByTicker = useMemo(
    () => new Map(calendars.map((calendar) => [calendar.ticker, calendar])),
    [calendars]
  )
  const threadRef = useRef<HTMLDivElement>(null)
  const questionRef = useRef<HTMLInputElement>(null)
  const lastQuestionRef = useRef<HTMLDivElement>(null)
  // How to scroll the next question into place once it renders, or null for not at all.
  const pendingScroll = useRef<ScrollBehavior | null>(null)
  const [end, setEnd] = useState<HTMLDivElement | null>(null)
  const [endBelow, setEndBelow] = useState(false)

  const busy = status === 'submitted' || status === 'streaming'

  // Session storage is read after the first render, so the server-rendered page (which
  // has no storage) and the browser's first render agree.
  useEffect(() => {
    const saved = loadConversation()
    if (saved.length > 0) {
      // A restored conversation opens at its last question, at once.
      pendingScroll.current = 'auto'
      setMessages(saved)
    }
  }, [setMessages])

  // A question "What's covered" asks about is filled in, never sent, and leaves the
  // address so a refresh doesn't fill it in again. Read after the first render, like
  // session storage, since the server-rendered page has no address to read.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const question = params.get(ASK_PARAM)
    if (!question) return
    // eslint-disable-next-line react-hooks/set-state-in-effect -- synced once from the address
    setInput(question)
    params.delete(ASK_PARAM)
    const search = params.toString()
    window.history.replaceState(
      window.history.state,
      '',
      `${window.location.pathname}${search ? `?${search}` : ''}${window.location.hash}`
    )
    questionRef.current?.focus()
  }, [])

  // Saved once each answer is complete, never half-written. Only "New conversation"
  // clears it, so the empty first render never overwrites a saved conversation.
  useEffect(() => {
    if (!busy && messages.length > 0) saveConversation(messages)
  }, [messages, busy])

  // The thread scrolls once per question, to put it at the top of the thread, and never
  // while its answer streams, so the reader keeps their place.
  const lastQuestionId = messages.findLast((m) => m.role === 'user')?.id
  useEffect(() => {
    const behavior = pendingScroll.current
    if (!behavior || !lastQuestionId) return
    pendingScroll.current = null
    lastQuestionRef.current?.scrollIntoView({ behavior, block: 'start' })
  }, [lastQuestionId])

  // "Jump to latest" shows while the end of the thread is below the thread's visible area.
  useEffect(() => {
    if (!end || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(
      ([entry]) =>
        setEndBelow(
          !entry.isIntersecting &&
            (!entry.rootBounds || entry.boundingClientRect.top >= entry.rootBounds.bottom)
        ),
      { root: threadRef.current }
    )
    observer.observe(end)
    return () => observer.disconnect()
  }, [end])

  function ask(question: string) {
    const text = question.trim()
    if (!text || busy) return
    pendingScroll.current = scrollBehavior()
    sendMessage({ text })
  }

  function newConversation() {
    if (busy) stop()
    setMessages([])
    saveConversation([])
    setPanel(null)
    setOpen(null)
    setCalendarTicker(null)
    setInput('')
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!input.trim() || busy) return
    ask(input)
    setInput('')
  }

  /** Opens the Sources tab at one answer's Source, whatever the panel showed. */
  function cite(messageId: string, tag: string) {
    setOpen({ messageId, tag })
    setPanel('sources')
  }

  /** A toolbar icon: opens the panel on its tab, or closes it when that tab is showing. */
  function toggle(tab: PanelTab) {
    if (panel === tab) {
      setPanel(null)
      return
    }
    if (tab === 'sources') {
      const latest = messages.findLast((m) => m.role === 'assistant')
      setOpen(latest ? { messageId: latest.id, tag: null } : null)
    }
    setPanel(tab)
  }

  const openMessage = open ? messages.find((m) => m.id === open.messageId) : undefined
  const openSources = openMessage ? messageSources(openMessage) : []
  const openCited = new Set(
    openMessage ? citedSources(messageText(openMessage), openSources).map((s) => s.tag) : []
  )
  const shownTag = panel === 'sources' && open ? (open.tag ?? openSources[0]?.tag ?? null) : null
  // Every Company any answer's Query Scope named, alphabetical: the Calendar's tickers.
  const calendarTickers = [
    ...new Set(
      messages.flatMap((m) =>
        m.role === 'assistant'
          ? (messageDataPart(m, 'query-scope')?.companies ?? []).map((c) => c.ticker)
          : []
      )
    ),
  ].sort()
  const last = messages.at(-1)
  const writing = status === 'streaming' && last?.role === 'assistant' && !messageText(last)
  const turns = groupTurns(messages)
  // Follow-ups suggested under the latest answer once it is complete, built from its
  // Query Scope by fixed templates, so no model is asked.
  const lastScope = last?.role === 'assistant' ? messageDataPart(last, 'query-scope') : null
  const lastQuestion = messages.findLast((m) => m.role === 'user')
  const suggestions =
    status === 'ready' && lastScope
      ? followUps(lastScope, lastQuestion ? messageText(lastQuestion) : '')
      : []

  const renderMessage = (message: ResearchMessage) =>
    message.role === 'user' ? (
      <UserMessage
        key={message.id}
        ref={message.id === lastQuestionId ? lastQuestionRef : undefined}
        text={messageText(message)}
      />
    ) : (
      <AnswerMessage
        key={message.id}
        text={messageText(message)}
        sources={messageSources(message)}
        scope={messageDataPart(message, 'query-scope')}
        gaps={messageDataPart(message, 'coverage-gaps')?.gaps ?? []}
        complete={answerComplete(message, messages, status)}
        openTag={open?.messageId === message.id ? shownTag : null}
        onCite={(tag) => cite(message.id, tag)}
      />
    )

  // Progress, errors and the end-of-thread marker follow the latest turn.
  const tail = (
    <>
      {status === 'submitted' && <Progress text="Finding the relevant filings…" />}
      {writing && <Progress text="Writing the answer…" />}

      {status === 'error' && (
        <div
          role="alert"
          className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[14px] text-red-200"
        >
          {rejectionReason(error) ?? (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span>The answer couldn&apos;t be loaded. Please try again.</span>
              <button
                type="button"
                onClick={() => regenerate()}
                className="btn-secondary px-3 py-1.5 text-[13px] whitespace-nowrap"
              >
                Try again
              </button>
            </div>
          )}
        </div>
      )}
      {suggestions.length > 0 && <FollowUps questions={suggestions} onPick={ask} />}
      <div ref={setEnd} />
    </>
  )

  return (
    <div className="flex h-dvh flex-col text-ink">
      <header className="flex shrink-0 items-center gap-3 border-b border-line bg-canvas/80 px-4 py-2.5 backdrop-blur-xl sm:gap-4 sm:px-5">
        <h1 className="text-[15px] font-semibold tracking-tight whitespace-nowrap text-ink">
          SEC Filings Research<span className="text-accent">.</span>
        </h1>
        <p className="hidden font-mono text-[12px] tracking-widest text-muted lg:block">
          Answers from companies’ 10-K and 10-Q filings, with every claim linked to its passage
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
          <div className="relative flex min-h-0 flex-1 flex-col">
            {/* A size container, so the latest turn can be sized to the thread's height. */}
            <div ref={threadRef} className="[container-type:size] min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto flex max-w-3xl flex-col gap-6 px-5 py-8">
                {turns.length === 0 ? (
                  <>
                    <EmptyState disabled={busy} onPick={ask} coverage={coverage} />
                    {tail}
                  </>
                ) : (
                  turns.map((turn, i) =>
                    i < turns.length - 1 ? (
                      <div key={turn[0].id} className="flex flex-col gap-6">
                        {turn.map(renderMessage)}
                      </div>
                    ) : (
                      // At least the thread's height, less its bottom padding and the
                      // question's top margin, so a new question can scroll to the top
                      // with room below it for the answer.
                      <div
                        key={turn[0].id}
                        className="flex min-h-[calc(100cqh-3.5rem)] flex-col gap-6"
                      >
                        {turn.map(renderMessage)}
                        {tail}
                      </div>
                    )
                  )
                )}
              </div>
            </div>

            {end && endBelow && (
              <button
                type="button"
                onClick={() => end.scrollIntoView({ behavior: scrollBehavior(), block: 'end' })}
                className="btn-secondary absolute bottom-4 left-1/2 -translate-x-1/2 px-4 py-1.5 text-[13px] whitespace-nowrap shadow-[0_4px_24px_rgba(0,0,0,0.5)]"
              >
                Jump to latest <span aria-hidden="true">↓</span>
              </button>
            )}
          </div>

          <form
            onSubmit={handleSubmit}
            className="shrink-0 border-t border-line bg-canvas/80 px-5 py-3 backdrop-blur-xl"
          >
            <PanelToolbar open={panel} onToggle={toggle} variant="buttons" />
            <div className="mx-auto flex max-w-3xl gap-2">
              <input
                ref={questionRef}
                type="text"
                aria-label="Question"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask about a company’s risks, results or outlook…"
                className="h-10 min-w-0 flex-1 rounded-lg border border-line bg-white/[0.04] px-4 text-[14px] text-ink transition-all duration-150 outline-none placeholder:text-muted focus:border-accent/50 focus:bg-white/[0.06] focus:shadow-[0_0_0_3px_rgba(14,165,233,0.15)]"
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

        {panel && (
          <SidePanel tab={panel} onTab={setPanel} onClose={() => setPanel(null)}>
            {panel === 'calendar' ? (
              <CalendarPanel
                tickers={calendarTickers}
                calendars={calendarsByTicker}
                selected={calendarTicker}
                onSelect={setCalendarTicker}
              />
            ) : (
              <SourcesPanel
                sources={openSources}
                cited={openCited}
                selected={shownTag}
                onSelect={(tag) => open && setOpen({ ...open, tag })}
              />
            )}
          </SidePanel>
        )}
        <PanelToolbar open={panel} onToggle={toggle} variant="rail" />
      </div>
    </div>
  )
}

/**
 * The conversation as turns: each question with the answer that follows it. A turn keeps
 * its element as later turns arrive, so an answer's component state survives a new question.
 */
function groupTurns(messages: ResearchMessage[]): ResearchMessage[][] {
  const turns: ResearchMessage[][] = []
  for (const message of messages) {
    if (message.role === 'user' || turns.length === 0) turns.push([message])
    else turns[turns.length - 1].push(message)
  }
  return turns
}

/** Smooth scrolling, unless the user prefers reduced motion. */
function scrollBehavior(): ScrollBehavior {
  const reduce =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  return reduce ? 'auto' : 'smooth'
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
          <span className="font-mono text-[12px] tracking-widest text-accent">
            10-K and 10-Q research
          </span>
        </div>
        <h2 className="headline text-3xl font-semibold tracking-[-0.03em] md:text-4xl">
          Ask a question about a public company
        </h2>
        <p className="mt-3 max-w-xl text-[14.5px] leading-relaxed text-muted">
          Name a company or its ticker. Each answer links every claim to the filing passage it comes
          from, and says what the filings can’t answer.
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

function UserMessage({ text, ref }: { text: string; ref?: Ref<HTMLDivElement> }) {
  return (
    <div ref={ref} className="flex scroll-mt-6 justify-end">
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
