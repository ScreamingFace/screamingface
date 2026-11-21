# Release docs review checklist

Run this yourself, at a release you decide is big. Nothing in this repo triggers it: not a
release-please PR, not a package version.

Reviewer: `@IrinaMBejan`.

## 1. Code against docs

List every `CHANGELOG.md` entry, across all packages, since the last big release. Include
each file's "Unreleased" section: a package with no cut release yet still has shipped,
undocumented behavior sitting there.

- `apps/aigateway/CHANGELOG.md`
- `apps/aigateway-ui/CHANGELOG.md`
- `apps/report-intake/CHANGELOG.md`
- `apps/scoreboard/CHANGELOG.md`
- `apps/screamingface-engine/CHANGELOG.md`
- `packages/screamingface/CHANGELOG.md`
- `packages/url4/CHANGELOG.md`

For each user-facing entry, find the matching page under `public-docs/` and confirm it
states the current behavior:

- a new `sf.*` export has a page
- changed behavior has an updated guide
- removed behavior has no page still describing it

## 2. Docs against product-context

Read `public-docs/` against `.claude/skills/product-context/SKILL.md`:

- terminology casing matches
- nothing in public copy violates the claims table
- the persona set matches who `public-docs/` assumes its reader is

Flag anything that drifted from that file, and anything `public-docs/` states as settled
that `product-context` marks provisional or open.
