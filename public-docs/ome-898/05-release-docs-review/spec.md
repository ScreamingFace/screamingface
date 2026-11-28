---
title: "Release-time docs review: spec"
ticket: OME-898
status: draft
date: 2026-09-22
---

# Release-time docs review

The epic's own text: "when we do a big release, product will review all docs manually."

## 1. Current state

- Releases are automated per package via `release-please.yml`: one PR per component
  (aigateway, screamingface, url4, screamingface-engine, scoreboard, report-intake), each
  touching only that package's `CHANGELOG.md`, `pyproject.toml`, and the manifest.
- `.github/CODEOWNERS` routes `/public-docs/` to `@IrinaMBejan`. CODEOWNERS requests
  reviewers only on paths a PR touches, and a release PR never touches `public-docs/`.
  Confirmed on PR #592 (screamingface 0.2.0): requested reviewers were the root and
  package owners, not her.
- 15 GitHub Releases shipped in the last month, one per package per merge. None is marked
  as a "big release."
- `docs-sync-check.yml` is a presence check: a public `sf.*` export change requires a docs
  page change in the same PR. It does not check the page's content.
- No release-time checklist or runbook exists.

## 2. Scope

- Product decides which release counts as big. No script detects it.
- A human checkpoint, with no enforcement mechanism.
- `release-please.yml`, `release-please-config.json`, and `CODEOWNERS` stay as they are.
- The checklist runs once per big release, covering every routine release-please PR merged
  since the last one.

## 3. Design

One new file, `docs/release-docs-review-checklist.md`. One pointer line in
`.claude/README.md`.

Two passes.

1. **Code against docs.** List every `CHANGELOG.md` entry, across all packages, since the
   last big release. For each user-facing entry, find the matching `public-docs/` page and
   confirm it states the current behavior: a page for a new `sf.*` export, an updated guide
   for changed behavior, no page describing removed behavior.
2. **Docs against product-context.** Read `public-docs/` against
   `.claude/skills/product-context/SKILL.md`: terminology casing, the claims table, the
   persona set. Flag any drift from canon, and any docs statement presented as settled that
   product-context marks provisional or open.

Reviewer: `@IrinaMBejan`, per the existing `/public-docs/` entry in CODEOWNERS.

Trigger: product decides a given release is big, and at that point opens
`docs/release-docs-review-checklist.md` and works through it themselves. No release-please
PR, package version, or engineering signal starts the review.

## 4. Acceptance

- `docs/release-docs-review-checklist.md` exists with both passes.
- `.claude/README.md` names it and states when to run it.
- No change to `release-please.yml`, `release-please-config.json`, or `CODEOWNERS`.

## 5. Verification

- Read the checklist as product would: each step is followable without asking an
  engineer what it means.
- Both passes name their real inputs: the package `CHANGELOG.md` files, `public-docs/`,
  `product-context/SKILL.md`.

