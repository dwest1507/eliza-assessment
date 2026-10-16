import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

// jsdom does not implement scrollIntoView (used to keep the latest answer in view).
// Route tests run in the node environment, which has no window.
if (typeof window !== 'undefined') {
  window.HTMLElement.prototype.scrollIntoView = vi.fn()
}
