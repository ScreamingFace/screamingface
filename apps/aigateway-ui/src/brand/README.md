# Vendored design system — ScreamingFace Design System v2

**Source:** `https://brand.screamingface.ai/tokens.css`
**Version served at pull time:** `?v=20260731a`
**Pulled:** 2026-07-31 (OME-716)

Replaces the OpenMined Design System vendored by OME-707. That was an owner decision reversed by an
owner decision: internal operator tooling wears the ScreamingFace brand, not the parent one.

The repo also keeps a verbatim copy of the whole system at
`.claude/skills/screamingface-design/reference/`, with a runnable drift check in its
`PROVENANCE.md`. **That copy is the reference; this one is the build input.** They differ only by
the divergence below — diff them if you suspect drift.

## This console is the "app" register

SFDS v2 ships two registers. `[data-brand="marketing"]` overrides **only** the accent-family
aliases; **the app register is the default**, and this console takes it.

| role | app register | used here for |
|---|---|---|
| `--accent-*` | **blue** `#4b91f0` | every interaction — buttons, links, focus rings |
| `--brand-*` / `--gain-*` | gold | **nothing.** Gold is "rationed to the win" — the leading leaderboard row, the SOTA counter. An admin console has no win. |
| `--success-*` | green | account active, credential attached |
| `--danger-*` | red | deactivate, detach a connection |
| `--bg` `--surface` `--surface-2` `--border` `--border-2` `--text` `--text-2` | neutrals | everything else |

`design-system.test.ts` asserts the zero-gold rule mechanically, because "a comment says not to"
has never stopped anyone.

**One trap carried over from v1:** the back-compat bridge keeps `--gain` resolving, but in v2 it
resolves to **gold**, where v1 had it green. A surface using `--gain` to mean "success" is now
saying "this is the win". Use `--success-*`.

## The one divergence: font families

Four `--f-*` tokens point at `next/font` CSS variables instead of the literal family names upstream
hardcodes:

| token | upstream | here |
|---|---|---|
| `--f-sans` | `"IBM Plex Sans"` | `var(--font-plex-sans)` |
| `--f-mono` | `"IBM Plex Mono"` | `var(--font-plex-mono)` |
| `--f-wordmark` | `"IBM Plex Sans"` | `var(--font-plex-sans)` |
| `--f-display` | `"Parastoo"` | `var(--font-plex-sans)` — **see below** |

`next/font` self-hosts the faces at build time, so the rendered page makes no request to a font
CDN. That is the same posture the brand site takes (it ships its own `fonts.css` and
`assets/fonts/` precisely to avoid one), and it matters more here: this console is internal tooling
behind Cloudflare Access, so a third-party request from an admin page is both a leak and a failure
mode.

**Parastoo is not loaded at all.** It is v2's display face, and the anti-rule is explicit — *never
serif in product UI chrome, table cells, or buttons*. This console has no display type, so loading
it would cost bytes for a face nothing is permitted to use. `--f-display` is aliased to Plex Sans so
a stray `var(--f-display)` degrades to the correct family rather than falling back to a system
serif.

Everything else in `tokens.css` is byte-identical to upstream.

## `base.css` is ours, not upstream's

Upstream's `style.css` (42 KB) is the brand site's own stylesheet: `.rail`, `.masthead`, `.stats`,
`.climb`, `.deltawrap`, `.logo-band`, the fusion gradient, the leaderboard table. Almost none of it
applies to an admin console, and the parts that do — the button ladder, table, badge, status square
— are re-expressed as this app's `.ui-*` primitives in `globals.css`.

So `base.css` is a small element-defaults layer written against the tokens, adding no values of its
own. Read `.claude/skills/screamingface-design/reference/style.css` when you need to know how a
recipe is *supposed* to behave.

## Re-syncing

1. Re-pull `tokens.css` from the URL above.
2. Re-apply the four font substitutions in the table.
3. Bump the version string in this file.
4. `npm run lint:css && npm test` — the token gate and the register test are what catch a bad sync.

Do not hand-edit `tokens.css` for anything else. If the console needs a value the system lacks, the
fix goes upstream into the system, never into this copy — that is v2's own round-trip rule.
