import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  citedSources,
  citedTag,
  linkCitations,
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
  /** The tag open in the Sources panel, if this answer's Sources are shown there. */
  openTag: string | null
  onCite: (tag: string) => void
}

/**
 * One answer: the Coverage Gap callout, then its Markdown, with every `[Sn]` a link that
 * opens the Sources panel at that Source. The Sources arrive before the text, so the
 * citations work while the answer is still streaming. Once it is complete, two collapsed
 * disclosures follow: "Sources (N)", the Sources it cites, and "How this was answered",
 * its Query Scope chips and every Source it was given.
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
  const tags = new Set(sources.map((s) => s.tag))
  const cited = citedSources(text, sources)

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
        <div className="answer text-[14.5px] leading-relaxed text-ink">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {linkCitations(text)}
          </ReactMarkdown>
        </div>
      )}
      {complete && (
        <footer className="flex flex-col gap-1 border-t border-line pt-2">
          {cited.length > 0 && (
            <Disclosure summary={`Sources (${cited.length})`}>
              <SourceChips
                label="Cited Sources"
                sources={cited}
                openTag={openTag}
                onCite={onCite}
              />
            </Disclosure>
          )}
          <Disclosure summary="How this was answered">
            <div className="flex flex-col gap-3">
              {scope && <QueryScopeChips scope={scope} />}
              {sources.length > 0 && (
                <SourceChips
                  label="Retrieved Sources"
                  sources={sources}
                  openTag={openTag}
                  onCite={onCite}
                />
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

/** Sources as chips, each opening the Sources panel at its Source. */
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
