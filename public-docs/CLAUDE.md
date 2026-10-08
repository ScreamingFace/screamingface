# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Screamingface documentation site — a Vue 3 + TypeScript + Vite application. The
baseline chrome (navbar, themeable sidebar/doc layout, and a data-driven
navigation system) was ported from `syft-space-hub-docs`; the page content is
being built out per section.

## Development Commands

- **Dev server**: `npm run dev`
- **Build**: `npm run build` (type-check + Vite build)
- **Preview**: `npm run preview`
- **Type-check**: `npm run type-check` (`vue-tsc --noEmit`)
- **Lint**: `npm run lint` (oxlint + eslint, auto-fix)
- **Format**: `npm run format` (Prettier, `src/`)

There is no automated test setup in this project.

## Stack

- Vue 3 + Vue Router + Pinia
- Tailwind CSS v4 (via `@tailwindcss/vite`) with the theme tokens in `src/style.css`
- `lucide-vue-next` for icons, `prismjs` for code highlighting, `markdown-it` for
  notebook markdown
- Path alias `@/` → `src/`
- Type-checking uses a single `tsconfig.json` (extends `@vue/tsconfig`) covering
  `src/**` plus the config files (`vite.config.ts`, `eslint.config.ts`)

## Architecture

- `src/App.vue` — shell: `<TheNavbar />` + `<RouterView />`
- `src/components/layout/TheNavbar.vue` — sticky top nav (brand, product links [Home / SF Client / SDK], theme toggle, GitHub)
- `src/components/layout/DocLayout.vue` — sidebar (`NavTree`) + optional page header + content slot + prev/next buttons + an optional sidebar version footer (`version` prop). `title` is optional; the header is skipped when omitted.
- `src/components/layout/NavTree.vue` — renders one level of a navigation tree and recurses for children. A group renders as a label (uppercase at depth 0, muted below), a link as a `RouterLink`. Depth drives styling only, so nesting is unbounded.
- `src/components/ui/` — reusable content components: `CodeBlock`, `TabbedCodeBlock`, `ApiBlock`, `Collapsible`, `ImageCarousel`, `NotebookViewer`
- `src/components/nb/` — notebook-cell primitives for docs pages: `NbCell` (input + output chrome), `NbTextOut` (plain repr output), `NbStateCarousel`, plus the panel kit (`NbPanel`, `NbRowList`, `NbProgress`, `NbStatGrid`, `NbCheckList`, `NbScoreList`, `ProviderConnections`, `EvaluationReport`, `CandidateScores`) and `tokens.css`. A page wraps each cell in `<div class="not-prose">`.
- `src/composables/` — reusable logic: `useCopy` (clipboard + "Copied!" feedback), `useHighlight` (central Prism setup + `highlight()`), `useDocNavigation` (sidebar active-state + prev/next from a nav tree), `useCarousel` (index + auto-advance)
- `src/stores/` — Pinia stores for shared reactive state: `theme` (`isDark` state, `theme` getter, dark/light + localStorage persistence) and `codeLang` (shared code-tab language across `TabbedCodeBlock`s)
- `src/lib/` — framework-agnostic helpers: `utils.ts` (`cn` class merge), `notebook.ts` (nbformat types + pure helpers for `NotebookViewer`) and `analytics.ts` (`track` wrapper over the Plausible snippet in `index.html`; no-op when the script is absent)
- `src/pages/` — route components; `src/router/index.ts` — routes
- `src/navigation/` — one data file per documentation section (drives the sidebar + prev/next)
- `src/style.css` — Tailwind import + light/dark theme tokens + prose styling (includes `@tailwindcss/typography` with prose variables mapped to the theme tokens)

### Pages & routes

| Route                                     | Component                                         |
| ----------------------------------------- | ------------------------------------------------- |
| `/`                                       | `src/pages/HomePage.vue`                          |
| `/sf-client`                              | `src/pages/sf-client/Index.vue`                   |
| `/sf-client/installation`                 | `src/pages/sf-client/InstallationPage.vue`        |
| `/sf-client/first-fusion`                 | `src/pages/sf-client/FirstFusionPage.vue`         |
| `/sf-client/quickstartPage`               | `src/pages/sf-client/QuickstartPage.vue`          |
| `/sf-client/guides/connections`           | `src/pages/sf-client/guides/ConnectionsPage.vue`  |
| `/sf-client/guides/models`                | `src/pages/sf-client/guides/ModelsPage.vue`       |
| `/sf-client/guides/fusions`               | `src/pages/sf-client/guides/FusionsPage.vue`      |
| `/sf-client/guides/pipelines`             | `src/pages/sf-client/guides/PipelinesPage.vue`    |
| `/sf-client/guides/benchmarks`            | `src/pages/sf-client/guides/BenchmarksPage.vue`   |
| `/sf-client/guides/running-an-evaluation` | `src/pages/sf-client/guides/EvaluationPage.vue`   |
| `/sf-client/guides/leaderboards`          | `src/pages/sf-client/guides/LeaderboardsPage.vue` |
| `/sf-client/guides/reproduce-and-share`   | `src/pages/sf-client/guides/Url4Page.vue`         |
| `/sf-client/api/recipes`                  | `src/pages/sf-client/api/RecipesPage.vue`         |
| `/sf-client/api/benchmarks`               | `src/pages/sf-client/api/BenchmarksPage.vue`      |
| `/sf-client/api/reports`                  | `src/pages/sf-client/api/ReportsPage.vue`         |
| `/sf-client/api/clients`                  | `src/pages/sf-client/api/ClientsPage.vue`         |
| `/sf-client/api/fusions`                  | `src/pages/sf-client/api/FusionsPage.vue`         |
| `/sf-client/api/pipelines`                | `src/pages/sf-client/api/PipelinesPage.vue`       |
| `/sf-client/api/url4`                     | `src/pages/sf-client/api/Url4Page.vue`            |
| `/sf-client/api/connections`              | `src/pages/sf-client/api/ConnectionsPage.vue`     |
| `/sf-client/api/modules`                  | `src/pages/sf-client/api/ModulesPage.vue`         |
| `/sf-client/api/errors`                   | `src/pages/sf-client/api/ErrorsPage.vue`          |
| `/sf-client/api/events`                   | `src/pages/sf-client/api/EventsPage.vue`          |
| `/sf-client/api/leaderboards`             | `src/pages/sf-client/api/LeaderboardsPage.vue`    |
| `/learn`                                  | `src/pages/learn/ArchitecturePage.vue`            |
| `/learn/url4`                             | `src/pages/learn/Url4Page.vue`                    |
| `/learn/url4-sdk`                         | `src/pages/learn/Url4SdkPage.vue`                 |
| `/learn/engine`                           | `src/pages/learn/EnginePage.vue`                  |
| `/learn/caching`                          | `src/pages/learn/CachingPage.vue`                 |
| `/learn/ai-gateway`                       | `src/pages/learn/GatewayPage.vue`                 |
| `/learn/leaderboard`                      | `src/pages/learn/LeaderboardPage.vue`             |

Note that `BenchmarksPage.vue` exists twice — under `guides/` (how to choose a
benchmark) and under `api/` (the `Benchmark` type). The route names
disambiguate them. The same applies to `Url4Page.vue` (`learn/` = the protocol,
`sf-client/guides/` = reproduce & share) and to the leaderboard pages:
`learn/LeaderboardPage.vue` is the concept, `sf-client/guides/LeaderboardsPage.vue`
is the `sf.leaderboards` API walkthrough.

### NotebookViewer

`src/components/ui/NotebookViewer.vue` renders a Jupyter `.ipynb` (parsed via
`src/lib/notebook.ts`): markdown cells → prose (`markdown-it`), code cells →
`In [n]` + copy + collapse (Prism), outputs handle html/text/image/error/stream.
It supports a `showTitle` toggle and rewrites inter-notebook links via
`NOTEBOOK_ROUTES`. It is kept for reuse but is **not currently wired to a page**.

## Navigation System

The sidebar and prev/next buttons are driven by shared data files in
`src/navigation/`, one file per documentation section.

A tree is built from two node kinds, distinguished by whether the node has a
destination (`isLink()` narrows on `'path' in entry`):

- a **group** (`{ title, children }`) labels its children and is never clickable
- a **link** (`{ title, path, children? }`) points at a page

Depth is not fixed — a group nested in a group is the same construct as a
top-level one, so `NavTree` renders any number of levels. `flatNav` collects
links only, so prev/next steps over group labels.

```ts
export const sfClientNavigation: NavEntry[] = [
  { title: 'Overview', path: '/sf-client' },
  { title: 'Get Started', children: [{ title: 'Quickstart', path: '…' }] },
  {
    title: 'User Guides',
    children: [
      { title: 'Connections', path: '…' },
      { title: 'Compose', children: [{ title: 'Models', path: '…' }] },
    ],
  },
]
```

| File                          | Export                                  | Used by                  | Entries                                                                                                                                                               |
| ----------------------------- | --------------------------------------- | ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/navigation/sf-client.ts` | `sfClientNavigation`, `sfClientVersion` | All `/sf-client/*` pages | Overview, then **Get Started**, **User Guides** (with a nested **Compose** group) and **API Reference** (with nested **Core classes** and **Modules & types** groups) |
| `src/navigation/sdk.ts`       | `sdkNavigation`                         | All `/sdk/*` pages       | **Getting Started**: Overview                                                                                                                                         |

**Versioning.** `sf-client.ts` also exports `sfClientVersion`
(`{ prefix, label, url }`), rendered once in the sidebar footer rather than on
each page. It is a commit while `screamingface` is unpublished; when the package
ships to PyPI only that object changes.

**How pages consume it:**

```ts
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'
```

Every page passes `:navigation="navigation"` and `:version="version"` to
`DocLayout`.

**How prev/next works:** `useDocNavigation` walks the tree recursively, collects
every link in sidebar order, and computes the previous and next page from the
current route. Adding a link to a nav file automatically gives it prev/next
buttons — no per-page configuration.

**Adding a new page:**

1. Create the Vue page under `src/pages/<section>/`, rendering it inside `DocLayout`.
2. Add a route in `src/router/index.ts`.
3. Add a link entry to the relevant `src/navigation/<section>.ts` file — at the
   top level, or in a group's `children`.
4. Import the shared navigation (and version, if the section has one) in the page.

**Adding a new section:**

1. Create `src/navigation/<section>.ts` exporting a `<section>Navigation: NavEntry[]`.
2. Add the section's routes in `src/router/index.ts`.
3. Add a top-level link to the section in `src/components/layout/TheNavbar.vue`
   (`products` array + `currentProduct` computed).
4. Each page in the new section imports from that navigation file.
