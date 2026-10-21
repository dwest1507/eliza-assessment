'use client'

import { useState } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  citedSources,
  citedTag,
  linkCitations,
  splitAnswer,
  type CoverageGap,
  type QueryScope,
  type Source,
} from '@/lib/chat'
import CoverageGaps from '@/components/CoverageGaps'
import Disclosure from '@/components/Disclosure'
import QueryScopeChips from '@/components/QueryScopeChips'
import { shortLabel } from '@/components/SourcesPanel'

interface AnswerMessageProps {
  text: string
  sources: Source[]
  /** What the rules resolved from the question; it arrives before the text. */
  scope: QueryScope | null
  /** What the Filings cannot answer; it arrives before the text. */
  gaps: CoverageGap[]
  /** Whether the answer has finished: until then nothing shows beneath it. */
  complete: boolean
  /** The tag open in the side panel's Sources tab, if this answer's Sources are shown there. */
  openTag: string | null
  onCite: (tag: string) => void
}

/**
 * One answer: the Coverage Gap callout, then its Markdown, with every `[Sn]` a link that
 * opens the side panel's Sources tab at that Source. The Sources arrive before the text, so the
 * citations work while the answer is still streaming. Only the opening paragraph, the
 * direct answer, shows at first: "Show full analysis" reveals the rest, live while it
 * streams, and the expanded state is this answer's own, never saved, so a restored answer
 * starts collapsed. An answer with one paragraph, or one that does not open with prose,
 * shows whole with no control. Once it is complete, one collapsed "Sources" disclosure
 * follows: its Query Scope chips on top, then the Sources it cites, then the Sources it
 * was given but does not cite under a collapsed "Also retrieved (N)".
 */
export default function AnswerMessage({
  text,
  sources,
  scope,
  gaps,
  complete,
  openTag,
  onCite,
}: AnswerMessageProps) {
  const [expanded, setExpanded] = useState(false)
  const tags = new Set(sources.map((s) => s.tag))
  const cited = citedSources(text, sources)
  const uncited = sources.filter((s) => !cited.includes(s))
  const split = splitAnswer(text)
  const shown = split && !expanded ? split.opening : text

  const components: Components = {
    a: ({ href, children }) => {
      const tag = citedTag(href)
      if (tag === null) {
        return (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-strong underline underline-offset-2 transition-colors hover:text-accent"
          >
            {children}
          </a>
        )
      }
      if (!tags.has(tag)) {
        // A tag the answer was not given: show it, but there is nothing to open.
        return (
          <span title="Not among this answer's Sources" className="citation citation-missing">
            {tag}
          </span>
        )
      }
      return (
        <a
          href={href}
          aria-label={`Source ${tag}`}
          aria-current={openTag === tag ? 'true' : undefined}
          onClick={(event) => {
            event.preventDefault()
            onCite(tag)
          }}
          className="citation"
        >
          {tag}
        </a>
      )
    },
    table: ({ children }) => (
      <div className="my-3 overflow-x-auto">
        <table>{children}</table>
      </div>
    ),
  }

  return (
    <article aria-label="Answer" className="flex flex-col gap-3">
      {gaps.length > 0 && <CoverageGaps gaps={gaps} />}
      {text && (
        <div className="answer text-[16px] leading-relaxed text-ink">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {linkCitations(shown)}
          </ReactMarkdown>
        </div>
      )}
      {split && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <button
            type="button"
            aria-expanded={expanded}
            onClick={() => setExpanded(!expanded)}
            className="group flex items-center gap-1.5 rounded-md py-1 text-[13px] font-medium text-accent-strong transition-colors hover:text-accent"
          >
            <svg
              viewBox="0 0 24 24"
              className="h-3.5 w-3.5 transition-transform group-aria-expanded:rotate-90"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden="true"
            >
              <path d="m9 6 6 6-6 6" />
            </svg>
            {expanded ? 'Hide full analysis' : 'Show full analysis'}
          </button>
          {!complete && (
            <span className="flex items-center gap-1.5 text-[12px] text-muted">
              <span
                className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent"
                aria-hidden="true"
              />
              The rest is still being written…
            </span>
          )}
        </div>
      )}
      {complete && (scope || sources.length > 0) && (
        <footer className="flex flex-col gap-1 border-t border-line pt-2">
          <Disclosure summary={cited.length > 0 ? `Sources (${cited.length})` : 'Sources'}>
            <div className="flex flex-col gap-3">
              {scope && <QueryScopeChips scope={scope} />}
              {cited.length > 0 && (
                <SourceChips
                  label="Cited Sources"
                  sources={cited}
                  openTag={openTag}
                  onCite={onCite}
                />
              )}
              {uncited.length > 0 && (
                <Disclosure summary={`Also retrieved (${uncited.length})`}>
                  <SourceChips
                    label="Also retrieved"
                    sources={uncited}
                    openTag={openTag}
                    onCite={onCite}
                  />
                </Disclosure>
              )}
            </div>
          </Disclosure>
        </footer>
      )}
    </article>
  )
}

interface SourceChipsProps {
  label: string
  sources: Source[]
  openTag: string | null
  onCite: (tag: string) => void
}

/** Sources as chips, each opening the side panel's Sources tab at its Source. */
function SourceChips({ label, sources, openTag, onCite }: SourceChipsProps) {
  return (
    <ul aria-label={label} className="flex flex-wrap gap-1.5">
      {sources.map((source) => (
        <li key={source.tag}>
          <button
            type="button"
            onClick={() => onCite(source.tag)}
            aria-pressed={openTag === source.tag}
            className="rounded-md border border-line bg-surface px-2 py-1 text-left text-[12px] text-ink transition-colors hover:border-accent/50 hover:bg-raised aria-pressed:border-accent/50 aria-pressed:bg-accent/10"
          >
            <span className="font-mono font-medium text-accent-strong">{source.tag}</span>{' '}
            {shortLabel(source)}
          </button>
        </li>
      ))}
    </ul>
  )
}
