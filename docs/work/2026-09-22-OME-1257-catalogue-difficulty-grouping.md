---
ticket: OME-1257
stack: screamingface-engine
status: in_progress
started: 2026-09-22
finished:
---

# OME-1257 — Group the benchmark catalogue by difficulty and interactivity

## Intent

Researchers scanning the catalogue can't tell an easy exact-match maths set from a
frontier expert exam, or a single-prompt board from interactive work — the flat list
makes board choice depend on prior knowledge. This unit adds a declared `difficulty`
tier to every benchmark (sibling of the existing `interaction` declaration), serves it
in every catalogue row, and makes `sf.benchmarks.list()` render the catalogue grouped
by the two axes so the listing reads as a map.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/definition.py` —
  `DifficultyTier` closed vocabulary + required `difficulty` field on
  `BenchmarkDeclaration` (no default, refused by name — same rule as `failure_policy`).
- Every registered board's `definition.py` (ours + imported) — assign a tier.
- Engine registry/conformance tests — every registered board declares a known tier;
  catalogue rows serve `difficulty`.
- `packages/screamingface` — served-row model gains `difficulty`; listing renders
  grouped by difficulty × interaction with provenance kept visible.
- Engine↔SDK conformance pin for the shared vocabulary (failure-codes precedent).

## Test plan

- RED: registry test asserting every registered benchmark declares a `difficulty`
  from the closed set (fails against boards not yet assigned).
- RED: catalogue-row test asserting `difficulty` is served beside `interaction`.
- RED: SDK listing test asserting grouped presentation (difficulty × interaction)
  with ours/imported provenance still visible.
- Vocabulary-refusal test: unknown tier value refused by name at declaration time.
- Engine↔SDK conformance test pinning the two vocabulary copies move together.

## Acceptance

- Every registered board declares a difficulty; missing/unknown fails registration.
- Catalogue rows serve `difficulty` alongside `interaction`.
- `sf.benchmarks.list()` presents the two-axis grouping, provenance visible.
- Tier assignments + vocabulary listed in the PR description for owner review.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus: `packages/screamingface/src/screamingface/_catalogue_vocabulary.py`
  (new neutral home for the SDK's ordered vocabulary copies — `catalog_contract`
  imports `_ui.catalog`, so putting them in the contract would have made a cycle);
  `screamingface_engine_inspect/importer.py` (generated BoardSpec rows now emit a
  `difficulty="TODO"` line that registration refuses by name, so an unassigned tier
  cannot ship); SDK `Benchmark` also gained `interaction` (the mapper silently
  dropped it before, and the listing needs both axes); public-surface snapshot
  regenerated + CHANGELOG entry.
- **Commits:** PR #1012 `feat(screamingface-engine): declare a difficulty tier on every benchmark` + stacked PR #1013 `feat(screamingface): render the catalogue as a faceted map with chips` (shas final on merge; owner approved `--skip-append-only` 2026-09-22).
  NOTE: Outcome items about the listing/chips/gold migration land in the STACKED PR #1013; the declaration/wire/conformance items land in #1012. Post-review rebase added tiers for `inspect-aime24`/`inspect-aime25` (OME-1238 landed mid-stack): both `medium` — competition-exam mathematics, headroom without expert stakes.
- **Gates:** engine — ruff ✓ format ✓ pyright 0 errors ✓ layering ✓ pytest 3272
  passed / 13 skipped ✓; SDK — ruff ✓ format ✓ pyright 0 errors ✓ pytest 1667
  passed / 26 skipped ✓ notebooks ✓ build ✓ distribution ✓ lock ✓. Coverage gates
  run last (both stacks) — append-only check requires the owner flag because a
  required declaration field necessarily edits prior exact-assertion tests.
- **Deviations:** (1) prior tests touched — enumerated for the owner: the required
  `difficulty` field forced additions inside existing declaration fixtures and
  exact `as_block()` assertions (9 engine test files), the public-surface snapshot
  regenerated per its documented procedure, and ONE origin-tabs widget test
  superseded (provenance re-pinned as per-row linked chips — every other OME-1114
  pin passes unmodified). (2) Work split into a 2-PR stack at design time
  (vocabulary+wire, then grouped rendering) per the ~500-LoC cap. (3) Owner
  redirect mid-unit, applied: vocabulary renamed to `easy`/`medium`/`hard`, and
  the widget's tier tabs replaced by clickable facet chips (Difficulty:
  All/Easy/Medium/Hard · Interaction: All/Single-shot/Multi-turn/Agentic — the
  agentic chip is presentation-only until the Engine declares the value; empty
  state says so). The prior OME-1114 "one tab per origin" changelog entry was
  amended in the same window since that layout never ships to users. (4) Second
  owner redirect, applied: a third chip row — Origin: All / ScreamingFace /
  inspect_evals, options derived from the origins actually present (open set by
  doctrine) — plus two SFDS-review fixes: active chips take the segmented-control
  primary pairing (accent fill + contrast text) and each chip row renders as one
  hairline frame. (5) Owner folded the gold-chip migration into this stack: `.sf-chip`/`.sf-pill`
  base restyled neutral (matching report_view.py's existing neutral chip), the
  redundant `--muted` modifier removed with its call sites — gold no longer
  appears anywhere in the catalogue (SFDS v2 gold-rationing).
