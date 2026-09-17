---
id: OME-738
linear_url: https://linear.app/openmined/issue/OME-738/add-a-ci-lane-for-public-docs
status: in_review
type: task
priority: P2
labels: [repo, autonomous, agentic]
created: 2026-08-04
closed:
---

# OME-738 — give public-docs a CI lane

Sub-issue of `OME-733` (Dependabot compliance + alert burndown).

`public-docs/` had **no CI**. No workflow `paths:` filter matched it, so a PR there showed only
unrelated checks and merged unverified — which is exactly how #460 (brace-expansion) and #432
(postcss) landed during `OME-734`. Both were correct security fixes, but nothing in the repo
could have said so.

Also a precondition for `OME-737`: the dependabot config gains a `/public-docs` npm entry, and
that entry should not exist before there is a lane to verify what it produces.

## The finding

The lane's first honest run showed the tree was **already failing lint**, and had been silently.
`npx eslint .` exited 1 on three pre-existing `vue/multi-word-component-names` errors. `npm run
lint` fails too — `--fix` cannot repair a component name — so the script has been exiting 1 for
as long as those files have existed. Nothing noticed, because nothing ran it.

**Fix (owner-approved): scope the rule, don't rename the components.** The rule guards against a
component shadowing a real HTML element, and neither directory can:

- `src/components/ui/` holds shadcn-style primitives (`Collapsible`, `CodeBlock`, `ApiBlock`) —
  single-word names are that library's convention.
- `src/pages/**/Index.vue` is a section-root **route** component, named for its route and never
  written as a tag.

Verified scoped, not blanket-disabled: a single-word `Probe.vue` dropped into
`src/components/layout/` was still flagged and exited 1.

## Design

- **One job, not the sibling test+build split** — `public-docs` has no test suite (`78331eb8`
  removed it), so no test-reporter or coverage step; both would fail on a `results.xml` that is
  never produced.
- **Lint binaries invoked directly**, never `npm run lint`: the scripts carry `--fix`, which in CI
  would mutate the tree and then pass on code differing from what was pushed. Recorded as an
  `INVARIANT:` in the workflow.
- **`npm run build` covers typecheck** (`run-p type-check "build-only {@}" --`).
- Carries the `cost` job, matching all five existing lanes.

## Verified

`npm ci` · `npx oxlint .` · `npx eslint .` · `npm run build` — all exit 0 locally.

Ledger: `docs/work/2026-08-04-OME-738-public-docs-ci-lane.md`
