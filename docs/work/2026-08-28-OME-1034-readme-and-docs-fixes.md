---
ticket: OME-1034
stack: screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-08-28
finished:
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

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">
