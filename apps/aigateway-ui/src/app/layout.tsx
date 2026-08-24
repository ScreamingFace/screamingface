import type { Metadata } from "next";
import Link from "next/link";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

import { ThemeSwitch } from "./theme";

import "./globals.css";

// SFDS v2 pairs IBM Plex Sans (UI, body, wordmark) with IBM Plex Mono (data, labels, IDs,
// receipts). next/font self-hosts both at build time, so the rendered page makes no request to a
// font CDN — the same posture the brand site takes, and it matters here specifically: this console
// is internal tooling behind Cloudflare Access, so a third-party request from an admin page is
// both a leak and a failure mode.
//
// PARASTOO IS DELIBERATELY ABSENT. It is v2's display face and is display/marketing-only; the
// anti-rule is explicit — "never serif in product UI chrome, table cells, or buttons". This
// console has no display type, so loading it would cost bytes for a face nothing may use. The
// vendored `--f-display` points at Plex Sans instead. See src/brand/README.md.
//
// Weights follow v2's spec: Sans 400/500/600, Mono 500/600. Mono 400 is included because table
// cells set data at regular weight.
const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-mono",
});

export const metadata: Metadata = {
  title: "aigateway admin",
  description: "Manage gateway accounts and their provider API keys.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // `suppressHydrationWarning` because the served script below sets `data-theme` on this element
    // before React hydrates, so the client DOM legitimately differs from the server markup. Scoped
    // to <html> only — it does not mask a mismatch anywhere else.
    <html
      lang="en"
      className={`${plexSans.variable} ${plexMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/*
          Applies the stored theme BEFORE first paint. A React effect runs after paint, so the page
          would render light and then flip — a visible flash on load and on every navigation.

          A served same-origin file rather than an inline script: the document then contains no
          injected HTML at all, and a future Content-Security-Policy needs no 'unsafe-inline'.
          Parser-blocking by design — no `async`/`defer` — because running late is the whole bug.
          Kept in step with `applyStoredTheme` by theme.test.tsx.
        */}
        {/* eslint-disable-next-line @next/next/no-sync-scripts --
            The rule guards against render-blocking scripts, and blocking is the entire point here:
            a deferred or async script runs after first paint, which is the flash this exists to
            prevent. The cost is one same-origin request for ~400 bytes, cached after first load. */}
        <script src="/theme-init.js" />
      </head>
      <body>
        <header className="app-bar">
          {/* Console navigation. Links, not client state: the browser handles routing and the
              active page is simply where the operator already is — a server-rendered app bar has
              no reliable way to know it without pathname plumbing that buys nothing here. */}
          <nav className="app-bar-nav" aria-label="Console sections">
            <Link href="/">Accounts</Link>
            <Link href="/cache">Response cache</Link>
          </nav>
          <span className="app-bar-mark">aigateway admin</span>
          <ThemeSwitch />
        </header>
        {children}
      </body>
    </html>
  );
}
