'use client'

import { useId, useState, type ReactNode } from 'react'

interface DisclosureProps {
  /** The toggle's text, which is also its accessible name. */
  summary: string
  children: ReactNode
}

/**
 * A toggle that shows or hides its content, collapsed at first. The open state is the
 * component's own, so each disclosure opens on its own and none is remembered.
 */
export default function Disclosure({ summary, children }: DisclosureProps) {
  const [open, setOpen] = useState(false)
  const id = useId()

  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen(!open)}
        className="group flex items-center gap-1.5 rounded-md py-1 text-[12.5px] font-medium text-muted transition-colors hover:text-ink aria-expanded:text-ink"
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
        {summary}
      </button>
      {open && (
        <div id={id} className="pt-2 pb-1">
          {children}
        </div>
      )}
    </div>
  )
}
