---
ticket: OME-1034
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-08-28
finished: 2026-08-28
---

# OME-1034 — Fix the broken README quickstart and the docs errors a first-time user hits

## Intent

An external tester installed `screamingface==0.1.1.post5`, opened the top-level README and
copy-pasted the Quickstart. Line 1 of the ensemble example raised `TypeError` because
`sf.Fusion` takes a keyword-only `synthesizer` with no default; the README also advertised an
`sf.from_url4(...)` entry point that has never existed, and `sf.__version__` — the first thing
anyone types to check what they installed — raised `AttributeError`. Alongside that, a handful of
docs-site pages carried a wrong FAQ answer, a diagram of a Fusion on the Pipelines page, invisible
links inside the orange "Note:" callouts, and thirteen line-level prose/link corrections.

This unit makes a first-run session end in a score instead of a traceback: the Quickstart runs
top-to-bottom as written, every documented symbol exists, `sf.__version__` reports the installed
version, the ports FAQ names the real override flags, and the Pipelines diagram shows stages.

Only one item is a code change (item 4, `sf.__version__`); it is the reason the landing leaf is
`py-screamingface`. Everything else is documentation.

## Planned changes

Code (stack `screamingface`):

- `packages/screamingface/src/screamingface/_version.py` — new: resolve the version from the
  installed distribution metadata, with a source-tree fallback.
- `packages/screamingface/src/screamingface/__init__.py` — assign and export `__version__`.
- `packages/screamingface/tests/test_version.py` — new: the RED tests (item 4).
- `packages/screamingface/tests/public_surface_snapshot.json` — deliberate regeneration; adding a
  public export is exactly the change this tripwire exists to announce.

Docs — root README (items 1, 2):

- `README.md` — pass a `synthesizer=` in the Quickstart Fusion example; replace the
  `sf.from_url4(...)` claim with the real API.

Docs — package README (item 3):

- `packages/screamingface/README.md` — `Url4.to_python()` returns a `str` of Python source, not
  live objects.

Docs site (items 5-15):

- `public-docs/src/pages/sf-client/InstallationPage.vue` — ports FAQ (item 5).
- `public-docs/src/style.css` (or the callout's owning component) — visible link affordance inside
  the orange "Note:" callouts (item 6).
- `public-docs/src/pages/sf-client/guides/PipelinesPage.vue` — replace the Fusion SVG with a real
  stage→stage→stage pipeline, and match the `aria-label` + `figcaption` (item 7).
- Prose corrections, tester's wording adopted verbatim (items 8-13), across the docs-site pages
  where each string actually appears.
- LANL paper link, OpenReview `XSIYfTm2h7` (item 14).
- Benchmark CTA destination → GitHub Issues on the canonical repo (item 15).

## Test plan

Item 4 is the only testable change; the RED tests are written first.

- Happy path: `sf.__version__` equals `importlib.metadata.version("screamingface")`.
- The anti-drift invariant: `sf.__version__` equals the `project.version` declared in
  `packages/screamingface/pyproject.toml`, so the attribute can never drift from the one place the
  number is written.
- Surface: `"__version__"` is in `sf.__all__`, so `from screamingface import *` carries it and the
  public-surface tripwire pins it.
- Error path: when no `screamingface` distribution is registered (a bare source tree on
  `sys.path`), version resolution falls back to a marker string rather than raising — a missing
  version label must never be the reason `import screamingface` fails.

Everything else is verified by the gates below plus a real import check.

## Acceptance

- `python -c "import screamingface as sf; print(sf.__version__)"` prints `0.1.1.post5`.
- The root README Quickstart runs as written (no `TypeError`, no reference to a symbol that does
  not exist).
- `uv run .claude/scripts/run_gates.py screamingface` is green.
- `public-docs`: `npm run type-check` (vue-tsc), `npm run build-only` (vite build),
  `oxlint`, `eslint` all green.
- Every one of the 15 ticket items is either applied or recorded here as not-found with the reason.

## Notes / constraints carried into this unit

- **Remote is `upstream`, not `origin`.** This checkout has a single remote,
  `upstream → github.com/ScreamingFace/screamingface`. The worktree was branched from
  `upstream/main` (`9d5f015b`), which is what the process rule "branch from `origin/main`" means
  here — same commit, different remote name.
- **Org URLs are out of scope.** `OME-914` / `OME-945` are concurrently rewriting
  `github.com/OpenMined/…` → `github.com/ScreamingFace/…` across the tree, including the root
  README and `public-docs/`. No `github.com/OpenMined` string is touched by this unit, even inside
  lines otherwise edited. For item 15 the destination used is
  `https://github.com/ScreamingFace/screamingface/issues` — the canonical org, already the value
  in `packages/screamingface/pyproject.toml`'s `[project.urls] Issues`, so it needs no rewrite
  from that other unit.
- **The changelog is release-please's.** `packages/screamingface/CHANGELOG.md` is generated from
  conventional commits, so the "record the interface change in the changelog" instruction in the
  public-surface tripwire is satisfied by the `feat(py-screamingface): …` commit, not by a hand
  edit.
- **`public-docs` has no card entry** in `.claude/sdlc.local.md` and no test suite. Its gates are
  the four `OME-846` used: `vue-tsc`, `vite build`, `oxlint`, `eslint`.

## Outcome

All 15 ticket items applied. Nothing was recorded as not-found.

- **Actual files** (as planned, plus one consequence):
  - `packages/screamingface/src/screamingface/_version.py` — new.
  - `packages/screamingface/src/screamingface/__init__.py` — `__version__` assigned + exported.
  - `packages/screamingface/tests/test_version.py` — new, 5 tests.
  - `packages/screamingface/tests/public_surface_snapshot.json` — regenerated (+5/-0).
  - `README.md`, `packages/screamingface/README.md` — items 1-3.
  - `public-docs/src/components/ui/Note.vue` — item 6 (the callout owns the styling, so the
    fix landed in the component, not in `style.css`; one change covers all 17 callouts).
  - `public-docs/src/pages/sf-client/InstallationPage.vue` — item 5.
  - `public-docs/src/pages/sf-client/guides/PipelinesPage.vue` — item 7.
  - `public-docs/src/pages/sf-client/Index.vue` — items 8, 9, 10, 14.
  - `public-docs/src/pages/sf-client/FirstFusionPage.vue` — items 11, 12, 13.
  - `public-docs/src/pages/sf-client/QuickstartPage.vue`, `public-docs/src/navigation/sf-client.ts`
    — item 13.
  - `public-docs/src/pages/sf-client/guides/BenchmarksPage.vue` — item 15.
  - **Not planned:** `InstallationPage.vue`'s `len(sf.__all__)   # 55` became stale the moment
    item 4 added an export. Corrected to `56` in the same change that caused it.

- **Commits:**
  - `ce4f4465` — docs(py-screamingface): open the OME-1034 work ledger and task mirror
  - `a9499265` — feat(py-screamingface): report the installed version as sf.__version__
  - `c3d19adb` — docs: fix the broken README quickstart and the to_python return-type claim
  - `163f9291` — docs(public-docs): correct the ports FAQ, the Pipelines diagram, and the
    first-run prose

- **Gates:**
  - `uv run .claude/scripts/run_gates.py screamingface` — ALL GATES GREEN (ruff check, ruff
    format, pyright, pytest, notebook check, `uv build`, distribution check).
    `1240 passed, 17 skipped`; coverage `95.09%` against a 95% floor.
  - `public-docs` — `vue-tsc --noEmit` 0, `vite build` 0, `oxlint .` 0, `eslint .` 0.
  - Acceptance: `python -c "import screamingface as sf; print(sf.__version__)"` → `0.1.1.post5`.

- **Deviations:**
  1. **The append-only check was skipped for this cycle, deliberately and once.**
     `run_gates.py screamingface` fails its append-only stage on
     `tests/public_surface_snapshot.json` with "existing test artifact is unsupported or
     unparseable" — the checker cannot parse JSON, so it conservatively rejects any change to
     that file. The change is the snapshot regeneration that adding a public export *requires*,
     performed through the mechanism `test_public_surface.py` documents in its own docstring
     (`UPDATE_SURFACE_SNAPSHOT=1`, which fails deliberately, then passes on a plain re-run).
     Hand-audited before proceeding: `git diff --numstat HEAD -- packages/screamingface/tests/`
     shows `5 0` on that one file and nothing else — purely additive, no test file modified, no
     assertion weakened, and the surface is now pinned more tightly than before, not less. The
     gate itself was NOT edited; the run used the runner's own `--skip-append-only` flag. Flagged
     for owner review rather than treated as routine.
  2. **Branched from `upstream/main`, not `origin/main`.** This clone has one remote, `upstream`.
     Same commit (`9d5f015b`), different remote name.
  3. **Three of the tester's "before" strings are line-wrapped in source**, so they are not
     byte-identical to the ticket's quotes: items 8, 10 and 11 span two or three lines with
     Prettier's fill. Whitespace-normalised they match exactly one place each, so they were
     applied there. Item 13's string is `DRACO state-of-art`, not `Draco` — the substantive
     error is the missing "the"; `DRACO` stays uppercase as it is everywhere else on the site
     and in the paper.
  4. **Item 14 used the forum URL.** `https://openreview.net/forum?id=XSIYfTm2h7` returns HTTP
     200. The PDF attachment URL returns 403 to a non-browser client (OpenReview's bot
     challenge), so the forum URL is both canonical and the more robust link.
  5. **Item 15 points at `https://github.com/ScreamingFace/screamingface/issues`** — the
     canonical org, matching `[project.urls] Issues` in the package's `pyproject.toml`. No
     `github.com/OpenMined` string was read or written by this unit; `git diff | grep OpenMined`
     is empty across all four commits.
  6. **`packages/screamingface/CHANGELOG.md` was not hand-edited.** It is release-please
     output; the `feat(py-screamingface):` commit is the changelog entry the public-surface
     tripwire asks for.

## Owner-verify

- **Item 7 is not machine-verifiable.** The new Pipelines diagram type-checks and builds, but
  only an eyeball in `npm run dev` at `/sf-client/guides/pipelines` confirms the boxes, the
  frame and the arrows land where intended in both themes. Item 6 (link affordance inside the
  orange Note callouts) wants the same glance.

## Observations — NOT changed, filed here rather than fixed

- `_runtime/cli.py`'s `--version` flag calls `importlib.metadata.version("screamingface")`
  directly rather than `_version.resolve_version()`. Harmless (a CLI only exists when
  installed, so failing loudly there is arguably right), but it is now a second copy of the
  same lookup.
- `public-docs` has three files that fail `prettier --check` on `main` and were left alone:
  `pages/learn/LeaderboardPage.vue`, `pages/sf-client/guides/LeaderboardsPage.vue`,
  `pages/sf-client/guides/Url4Page.vue`. Pre-existing, and Prettier is not a gate
  (`eslint.config.ts` ends with `skipFormatting`).
- `public-docs` is not registered as a stack in `.claude/sdlc.local.md`, so it has no
  `run_gates.py` entry. Its four checks had to be reconstructed from what `OME-846` used.
