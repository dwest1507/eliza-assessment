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
