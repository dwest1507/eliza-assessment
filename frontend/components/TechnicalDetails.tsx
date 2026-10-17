'use client'

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'

interface Disclosures {
  isOpen: (id: string) => boolean
  toggle: (id: string) => void
  register: (id: string) => () => void
}

const DisclosuresContext = createContext<Disclosures | null>(null)

/** The id the URL fragment names, without its `#`. */
function fragment(): string {
  return decodeURIComponent(window.location.hash.slice(1))
}

/**
 * The "Technical details" layer of "How it works": its sections start collapsed, a
 * page-level control expands or collapses them all, and the section a URL fragment names
 * opens on load and whenever the fragment changes, so a link to a section lands on it open.
 */
export default function TechnicalDetails({
  heading,
  children,
}: {
  heading: ReactNode
  children: ReactNode
}) {
  const [ids, setIds] = useState<string[]>([])
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set())

  const register = useCallback((id: string) => {
    setIds((known) => (known.includes(id) ? known : [...known, id]))
    return () => setIds((known) => known.filter((k) => k !== id))
  }, [])

  const toggle = useCallback((id: string) => {
    setOpen((current) => {
      const next = new Set(current)
      if (!next.delete(id)) next.add(id)
      return next
    })
  }, [])

  useEffect(() => {
    // Open the named section, keeping any the reader already opened, then bring its
    // heading into view: with every section collapsed the page can be too short for the
    // browser to have reached it.
    const openFragment = () => {
      const id = fragment()
      if (!id) return
      setOpen((current) => (current.has(id) ? current : new Set(current).add(id)))
      requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView())
    }
    openFragment()
    window.addEventListener('hashchange', openFragment)
    return () => window.removeEventListener('hashchange', openFragment)
  }, [])

  const allOpen = ids.length > 0 && ids.every((id) => open.has(id))
  const disclosures: Disclosures = { isOpen: (id) => open.has(id), toggle, register }

  return (
    <DisclosuresContext value={disclosures}>
      {/* Wider than the reading column on large screens, so the tables fit. */}
      <div className="mx-auto flex w-full max-w-[100rem] flex-col gap-10">
        <div className="flex flex-wrap items-end justify-between gap-4">
          {heading}
          <button
            type="button"
            onClick={() => setOpen(allOpen ? new Set() : new Set(ids))}
            className="rounded-full border border-line px-4 py-1.5 text-[13px] text-muted transition-colors duration-200 hover:border-accent/50 hover:text-ink"
          >
            {allOpen ? 'Collapse all' : 'Expand all'}
          </button>
        </div>
        <div className="flex flex-col gap-16">{children}</div>
      </div>
    </DisclosuresContext>
  )
}

/**
 * One technical section: a region named by its heading, whose heading is the button that
 * opens and closes it. Its content stays rendered when closed, only hidden.
 */
export function TechnicalSection({
  id,
  title,
  intro,
  children,
}: {
  id: string
  title: string
  intro: ReactNode
  children: ReactNode
}) {
  const disclosures = useContext(DisclosuresContext)
  if (!disclosures) throw new Error('TechnicalSection must sit inside TechnicalDetails')
  const { isOpen, toggle, register } = disclosures
  useEffect(() => register(id), [id, register])
  const open = isOpen(id)
  const panel = `${id}-content`

  return (
    <section aria-labelledby={id} className="flex flex-col gap-4">
      <div>
        <div className="mb-3 flex items-center gap-3">
          <span className="h-px w-10 bg-accent/50" aria-hidden="true" />
          <span className="font-mono text-[11px] tracking-widest text-accent">{id}</span>
        </div>
        <h2
          id={id}
          className="headline scroll-mt-20 text-2xl font-semibold tracking-[-0.02em] md:text-3xl"
        >
          <button
            type="button"
            aria-expanded={open}
            aria-controls={panel}
            onClick={() => toggle(id)}
            className="group flex items-center gap-3 text-left"
          >
            <span
              aria-hidden="true"
              className={`text-[0.7em] text-accent transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
            >
              ▸
            </span>
            {title}
          </button>
        </h2>
        <p className="mt-2 max-w-3xl text-[14px] leading-relaxed text-muted">{intro}</p>
      </div>
      <div id={panel} hidden={!open} className="flex flex-col gap-4">
        {children}
      </div>
    </section>
  )
}
