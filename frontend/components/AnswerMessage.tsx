import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { citedTag, linkCitations, type QueryScope, type Source } from '@/lib/chat'
import QueryScopeChips from '@/components/QueryScopeChips'
import { shortLabel } from '@/components/SourcesPanel'

interface AnswerMessageProps {
  text: string
  sources: Source[]
  /** What the rules resolved from the question; it arrives before the text. */
  scope: QueryScope | null
  /** The tag open in the Sources panel, if this answer's Sources are shown there. */
  openTag: string | null
  onCite: (tag: string) => void
}

/**
 * One answer: the Query Scope chips, its Markdown, with every `[Sn]` a link that opens
 * the Sources panel at that Source, and the list of Sources it was given. The Query
 * Scope and Sources arrive before the text, so they show while the answer is still
 * streaming.
 */
export default function AnswerMessage({
  text,
  sources,
  scope,
  openTag,
  onCite,
}: AnswerMessageProps) {
  const tags = new Set(sources.map((s) => s.tag))

  const components: Components = {
    a: ({ href, children }) => {
      const tag = citedTag(href)
      if (tag === null) {
        return (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent underline"
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
      {scope && <QueryScopeChips scope={scope} />}
      {text && (
        <div className="answer text-[14.5px] leading-relaxed text-ink">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {linkCitations(text)}
          </ReactMarkdown>
        </div>
      )}
      {sources.length > 0 && (
        <footer className="border-t border-line pt-3">
          <h3 className="mb-2 text-[12px] font-medium tracking-wide text-muted uppercase">
            Sources
          </h3>
          <ul className="flex flex-wrap gap-1.5">
            {sources.map((source) => (
              <li key={source.tag}>
                <button
                  type="button"
                  onClick={() => onCite(source.tag)}
                  aria-pressed={openTag === source.tag}
                  className="rounded border border-line bg-white px-2 py-1 text-left text-[12px] text-ink hover:border-accent aria-pressed:border-accent aria-pressed:bg-accent/5"
                >
                  <span className="mr-1.5 font-mono font-medium text-accent">{source.tag}</span>
                  {shortLabel(source)}
                </button>
              </li>
            ))}
          </ul>
        </footer>
      )}
    </article>
  )
}
