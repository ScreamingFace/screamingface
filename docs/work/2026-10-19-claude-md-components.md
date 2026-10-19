---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: repo
status: in_progress
started: 2026-10-19
finished:
---

# claude-md-components — list the current components in CLAUDE.md

## Intent

The root `CLAUDE.md` "Monorepo" section still describes the July refoundation: it lists only
`apps/aigateway` and `apps/scoreboard`, calls `packages/` "reserved; `url4-python-sdk` first",
and its legacy line names "url4 engine" without saying that today's engine is
`apps/screamingface-engine`. Since then the engine (the largest component, ~204k lines at
2026-10-16), aigateway-ui, report-intake, analytics, studio and the two packages
(`packages/url4`, `packages/screamingface`) landed. Every agent session loads this file first,
so the stale list misroutes work. Found while building the 2026-10-18 engineering-review deck
("doc drift" metric).

## Planned changes

- `CLAUDE.md` — rewrite the "Monorepo" component bullets to the current set (one line each),
  name the `working-in-this-repo` skill's routing table as the source of truth for stack /
  CI / release details, mark `apps/desktop` as build leftovers (not a component, per OME-1266),
  and clarify the legacy line (the *original* url4 engine; today's engine is
  `apps/screamingface-engine`).

## Test plan

- Docs-only change: no runtime behaviour, no CI lane gates `CLAUDE.md`.
- Check: every `apps/*` and `packages/*` directory on `origin/main` appears in the list, and no
  listed path is missing (`git ls-tree -d --name-only origin/main apps/ packages/`).

## Acceptance

- The component list matches `git ls-tree` of `origin/main`; descriptions agree with the
  `working-in-this-repo` routing table.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:** docs-only unit; no spec/plan artifact (single-file wording fix requested
  directly by the owner).
