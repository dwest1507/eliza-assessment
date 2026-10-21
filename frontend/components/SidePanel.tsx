'use client'

import { useId, type ReactNode } from 'react'

/** The side panel's tabs, in the order the toolbar and the tab strip show them. */
export type PanelTab = 'sources'

const TABS: { tab: PanelTab; name: string; icon: ReactNode }[] = [
  { tab: 'sources', name: 'Sources', icon: <DocumentIcon /> },
]

interface SidePanelProps {
  tab: PanelTab
  onTab: (tab: PanelTab) => void
  onClose: () => void
  /** The open tab's content. */
  children: ReactNode
}

/**
 * The workspace's one right-hand panel: its tabs (Sources, for now), a close control and
 * the open tab's content. On a wide screen it sits beside the thread; on a narrow one it
 * is a full-screen sheet.
 */
export default function SidePanel({ tab, onTab, onClose, children }: SidePanelProps) {
  const id = useId()
  const tabId = (t: PanelTab) => `${id}-tab-${t}`
  const panelId = (t: PanelTab) => `${id}-panel-${t}`

  return (
    <aside
      aria-label="Side panel"
      className="fixed inset-0 z-20 flex flex-col bg-elevated lg:static lg:z-auto lg:w-[30rem] lg:shrink-0 lg:border-l lg:border-line lg:bg-canvas/70 lg:backdrop-blur-xl"
    >
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line px-3 py-2">
        <div role="tablist" aria-label="Panel tabs" className="flex gap-1">
          {TABS.map(({ tab: t, name }) => (
            <button
              key={t}
              type="button"
              role="tab"
              id={tabId(t)}
              aria-selected={t === tab}
              aria-controls={panelId(t)}
              onClick={() => onTab(t)}
              className="eyebrow rounded-md px-2.5 py-1 text-muted transition-colors hover:text-ink aria-selected:bg-raised aria-selected:text-ink"
            >
              {name}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close panel"
          className="rounded-md p-1 text-muted transition-colors hover:bg-raised hover:text-ink"
        >
          <svg
            viewBox="0 0 24 24"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
          >
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
      <div
        role="tabpanel"
        id={panelId(tab)}
        aria-labelledby={tabId(tab)}
        className="flex min-h-0 flex-1 flex-col"
      >
        {children}
      </div>
    </aside>
  )
}

interface PanelToolbarProps {
  /** The tab the panel shows, or null while it is closed. */
  open: PanelTab | null
  onToggle: (tab: PanelTab) => void
  /**
   * "rail": the column of icons on the right edge of a wide screen; "buttons": the row
   * above the question box on a narrow one.
   */
  variant: 'rail' | 'buttons'
}

/**
 * The panel's toolbar, always visible: one icon per tab, highlighted while its tab is
 * open. Clicking an icon opens the panel on its tab, and clicking the open tab's icon
 * closes it.
 */
export function PanelToolbar({ open, onToggle, variant }: PanelToolbarProps) {
  const rail = variant === 'rail'
  return (
    <div
      role="group"
      aria-label={rail ? 'Panel toolbar' : 'Panel buttons'}
      className={
        rail
          ? 'hidden w-12 shrink-0 flex-col items-center gap-1.5 border-l border-line bg-canvas/80 py-3 backdrop-blur-xl lg:flex'
          : 'mx-auto mb-2 flex max-w-3xl justify-end gap-1.5 lg:hidden'
      }
    >
      {TABS.map(({ tab, name, icon }) => (
        <button
          key={tab}
          type="button"
          aria-label={name}
          aria-pressed={open === tab}
          title={open === tab ? `Close ${name}` : `Open ${name}`}
          onClick={() => onToggle(tab)}
          className={`flex items-center gap-1.5 rounded-md text-muted transition-colors hover:bg-raised hover:text-ink aria-pressed:bg-accent/15 aria-pressed:text-accent-strong ${
            rail ? 'p-2' : 'border border-line px-2.5 py-1 text-[13px]'
          }`}
        >
          {icon}
          {!rail && <span aria-hidden="true">{name}</span>}
        </button>
      ))}
    </div>
  )
}

function DocumentIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-[18px] w-[18px]"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5M9 13h6M9 17h6" />
    </svg>
  )
}
