import type { ResearchMessage } from '@/lib/chat'

/**
 * The conversation is kept in session storage, so a page refresh does not lose it and a
 * new browser session starts empty. The backend keeps nothing (it is stateless), so this
 * is the only copy. Storage can be missing or blocked (a private window, a full quota):
 * then the conversation simply lasts as long as the page.
 */
const STORAGE_KEY = 'sec-filings-research:conversation'

/** The conversation saved in this session, or an empty one. */
export function loadConversation(): ResearchMessage[] {
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? '[]')
    return Array.isArray(saved) ? saved : []
  } catch {
    return []
  }
}

/** Saves the conversation for this session; an empty one clears it. */
export function saveConversation(messages: ResearchMessage[]): void {
  try {
    if (messages.length === 0) sessionStorage.removeItem(STORAGE_KEY)
    else sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages))
  } catch {
    // Storage is unavailable; the conversation lives only as long as the page.
  }
}

/**
 * Whether the side panel may still open on the Calendar by itself. Closing the panel
 * turns that off for the rest of the browser session, so it is kept in session storage
 * apart from the conversation: "New conversation" and a refresh leave it off.
 */
const CALENDAR_AUTO_OPEN_OFF_KEY = 'sec-filings-research:calendar-auto-open-off'

/** True once the panel has been closed in this browser session. */
export function calendarAutoOpenOff(): boolean {
  try {
    return sessionStorage.getItem(CALENDAR_AUTO_OPEN_OFF_KEY) !== null
  } catch {
    return false
  }
}

/** Turns the Calendar's auto-open off for the rest of this browser session. */
export function turnCalendarAutoOpenOff(): void {
  try {
    sessionStorage.setItem(CALENDAR_AUTO_OPEN_OFF_KEY, '1')
  } catch {
    // Storage is unavailable; the workspace remembers it as long as the page lasts.
  }
}
