import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

// jsdom does not implement scrollIntoView (used to scroll a new question into place and
// for "Jump to latest").
// Route tests run in the node environment, which has no window.
if (typeof window !== 'undefined') {
  window.HTMLElement.prototype.scrollIntoView = vi.fn()
}
