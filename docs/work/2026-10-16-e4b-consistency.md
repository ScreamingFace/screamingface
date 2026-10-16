---
ticket: unfiled   # epic OME-1290 is the parent; the leaf is filed at PR-open
stack: screamingface-engine, screamingface, repo
status: planned   # planned | in_progress | done | blocked
started: 2026-10-16
finished:
---

# e4b-consistency — E4b part 7, consistency@N

One ledger for the whole part. The plan is
[docs/plan/2026-10-16-e4b-consistency.md](../plan/2026-10-16-e4b-consistency.md). The spec is
[docs/spec/2026-10-16-e4b-consistency/](../spec/2026-10-16-e4b-consistency/00-overview.md).
Branch `e4b-consistency`, base `633fec3a1` (part 5, on parts 4, 3 and 2). Part 6 builds in
parallel from the same base (branch `e4b-signal-sums`, another worktree; this part never touches
it). Each unit gets its own section below, in the order of plan §2.

## Spec

### Intent

Add the `consistency@N` signal source of the E4b sources table. `sf.Consistency(n, *,
temperature=1.0)` is declared like `sf.Logprob`. The compile adds n extra calls for each member
(the member's route, prompt and other params; the stated temperature; distinct, fixed seeds), each
member's calls in one broadcast panel with `quorum=0`, so a failed extra call never fails the Case.
The combine step reads the panels from a new context key `samples` and records, for each member,
`matched / succeeded` over its successful extra calls, after the step's own extract and normalize
(or `last_line` and `text` for a step with no extract). All failed → the value is missing, and a
rule that reads it excludes the member. The evidence gets an optional record `consistency` with
`matched`, `succeeded`, `failed` per member. The part 4 surfaces show the value and the failed
count; the url4 rebuild gives back `sf.Consistency(...)` and drops the extra calls.

### Owner decisions (verbatim)

- Q3 temperature: "Source sets temperature (Recommended)" — `sf.Consistency(n=5,
  temperature=1.0)`: the extra calls use distinct seeds and the stated temperature (default 1.0),
  the member's other params unchanged. Explicit and reproducible.
- Q4 sample failure: "Fraction over successes (Recommended)" — value = matches / successful
  samples; the count of failed samples is recorded; if all fail, the value is missing (the rule then
  excludes the member, as in part 2). The Case does not fail.

No proposed item contradicts these answers. No owner blocker.

### Spec files (commit `docs(e4b): spec and plan for E4b part 7 (consistency)`)

- `docs/spec/2026-10-16-e4b-consistency/00-overview.md` (P1–P22, N1–N6, D1–D8)
- `docs/spec/2026-10-16-e4b-consistency/erd.md`, `contracts.md` (C1–C8), `test-plan.md`
  (fixed lists L37, L47, L5)
- `docs/spec/2026-10-16-e4b-consistency/prd/`: `consistency-record.md` (CR, 15 rows),
  `consistency-value.md` (CV, 15), `consistency-api.md` (CA, 14), `consistency-rebuild.md`
  (CB, 9), `consistency-display.md` (CD, 7), `docs.md` (DC, 5). 65 rows.
- `docs/plan/2026-10-16-e4b-consistency.md`

### Units

| # | Slug | PRD rows | Stacks | Pinned files |
|---|---|---|---|---|
| 1 | consistency-record | CR#1–15 | screamingface-engine, screamingface, repo | `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json`, `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`, `ST/public_surface_snapshot.json` |
| 2 | consistency-value | CV#1–15 | screamingface-engine, screamingface, repo | none |
| 3 | consistency-api | CA#1–14 | screamingface-engine, screamingface, repo | `ST/public_surface_snapshot.json` |
| 4 | consistency-rebuild | CB#1–9 | screamingface, repo | none |
| 5 | consistency-display | CD#1–7 | screamingface, repo | none |
| 6 | docs | DC#1–5 | screamingface, repo | none |

`ET/` = `apps/screamingface-engine/tests/unit/`, `ST/` = `packages/screamingface/tests/`.

### Facts checked on `633fec3a1` (intake)

- No `.codegraph/` in this worktree; the facts were checked with grep and read.
- `sf.samples()` exists: S/_samples.py:21-52 (n 1..256, `seeds` default `range(n)`,
  `temperature`, `params`; it refuses a `seed` in params). Confirmed.
- Duplicate members warn: `_warn_duplicate_members` S/_evaluation/candidate.py:839-870 (the brief
  said 855-870; the function starts at 839).
- The name `consistency` is reserved: `RESERVED_NAME_PREFIXES` S/_signals.py:23; the refusal text
  S/fusion.py:159-163 (the brief's :162 is inside it); pinned by
  `ST/unit/test_declared_name_conformance.py:79`.
- Engine `SOURCES` holds only `verbalized`: E/combine/operators/extract.py:395-397. Confirmed.
- Logprob and entropy are `_ReplyDeclared`: E/combine/endpoint.py:716-718 (in `_declared`,
  :710-728). Confirmed.
- Agreement math: `_tie_and_agreement` E/combine/operators/select.py:42-48. Confirmed.
- The normalizer `text@1`: E/combine/operators/normalize.py:58-66 (trim, collapse, casefold, strip
  one trailing period).
- The member reader indexes recorded calls by `(path, params)`; zero or several matches make the
  numbers unknown: E/world/combine.py:82-165. The binding param is stripped before the gateway:
  E/world/request_parameters.py:6-10, :26-28, :172-182. `derive_attempt_seed` :133-145
  (31 bits of sha256).
- The binding vocabulary `(model|synthesis|judge|writer)_N` is pinned in three places
  (S/_operation_bindings.py:5-9, E/benchmarks/operation_outputs.py:52,
  `ET/data/combine_contract/binding_names.json`). This part adds no prefix.
- The Engine attributes calls inside root `panel_N` sources:
  E/benchmarks/operation_outputs.py:165-209. url4 broadcast: a failed optional slot is left out
  (packages/url4/src/url4/dag/nodes/broadcast_result.py:19-55); `quorum` 0 always holds
  (`_shared.py:256-262`). url4 `struct` keeps the insertion order (checked with `uv run`).
- The replay recompiles a url4 with an optional slot byte for byte: S/url4.py:411-470;
  `spec_operator_pairs` reads only the four steps: S/_evaluation/combine_spec.py:189-197.
- Accounting stages: `_ACCOUNTED_STAGES` S/accounting.py:40-42 (an unknown kind gets no row).
  Fixed-seed warning: `_own_seed_calls` S/_evaluation/runner.py:642-649; replay `seeded`
  S/_evaluation/url4.py:239-245.
- `sf.Pick(by_signal=...)` and `sf.Rank(by_signal=...)` take no `extract`
  (S/fields.py:503-555, S/selection.py:79-118), so the match cannot always be "the step's own".
  The spec writes the match operators in the entry (P3).
- Existing tests refuse the bare entry `{"source": "consistency"}`:
  `ET/test_combine_declared_signals.py:135`, `:240`. They stay green because `n`, `temperature`
  and `match` are required.
- Docs constraints: `ST/test_gate_docs.py:100` pins the headings between `### Signal sources` and
  `### Fusion as a named recipe`; so the new section goes before `## Install`.
  `ST/test_show_signals_docs.py:24-35` (counted tokens), `:78` (Browse..Accounting headings).
- No test reads every key of the 37 contract cases or globs the url4 fixtures, so a new contract
  file and new url4 files do not turn an existing test red (checked with grep).
- Derived seeds: for k ≤ 256 and j ≤ 32 the 8192 seeds are distinct; the smallest is 134114
  (computed with `uv run`).

### Status

Spec written headless from the owner answers of 2026-10-16. Build not started. The units append
their sections (Intent, Planned changes, Pinned edits, Test plan, Acceptance, Deviations, Outcome)
below.
