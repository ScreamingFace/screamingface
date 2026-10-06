// Thin wrapper over the Plausible snippet loaded in index.html. Every call is a no-op when the
// script is absent or blocked, so analytics can never break a page.

type EventProps = Record<string, string | number | boolean>

declare global {
  interface Window {
    plausible?: (event: string, options?: { props?: EventProps }) => void
  }
}

export function track(event: string, props?: EventProps): void {
  try {
    window.plausible?.(event, props ? { props } : undefined)
  } catch {
    /* analytics unavailable, ignore */
  }
}

// The tracker has no way to know a client-side route missed, so the not-found page reports it.
// Event name and `path` prop match the '404' goal on the Plausible site.
export function trackNotFound(): void {
  track('404', { path: window.location.pathname })
}

// One event for every copy button, so the dashboard shows which pages' snippets get used.
export function trackCodeCopy(): void {
  track('Code Copy', { path: window.location.pathname })
}
