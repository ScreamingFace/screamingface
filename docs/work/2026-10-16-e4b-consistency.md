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

- `docs/spec/2026-10-16-e4b-consistency/00-overview.md` (P1–P22, N1–N8, D1–D9)
- `docs/spec/2026-10-16-e4b-consistency/erd.md`, `contracts.md` (C1–C8), `test-plan.md`
  (fixed lists L37, L47, L5)
- `docs/spec/2026-10-16-e4b-consistency/prd/`: `consistency-record.md` (CR, 15 rows),
  `consistency-value.md` (CV, 14), `consistency-api.md` (CA, 14), `consistency-rebuild.md`
  (CB, 9), `consistency-display.md` (CD, 7), `docs.md` (DC, 5). 64 rows.
- `docs/plan/2026-10-16-e4b-consistency.md`

### Units

| # | Slug | PRD rows | Stacks | Pinned files |
|---|---|---|---|---|
| 1 | consistency-record | CR#1–15 | screamingface-engine, screamingface, repo | `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json`, `ET/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`, `ST/public_surface_snapshot.json` |
| 2 | consistency-value | CV#1–14 | screamingface-engine, screamingface, repo | none |
| 3 | consistency-api-source | CA#2, CA#3, CA#14 | screamingface, repo | `ST/public_surface_snapshot.json` |
| 4 | consistency-api-compile | CA#1, CA#4–13 | screamingface-engine, screamingface, repo | none |
| 5 | consistency-rebuild | CB#1–9 | screamingface, repo | none |
| 6 | consistency-display | CD#1–7 | screamingface, repo | none |
| 7 | docs | DC#1–5 | screamingface, repo | none |

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

### Spec review

A design review of the spec and the plan (2026-10-16) gave 2 MAJOR (one of them STRUCTURAL) and 14 MINOR
findings. All are applied in commit `docs(e4b): review fixes for the E4b part 7 spec`. No finding
contradicts an owner answer (Q3, Q4). No owner blocker.

| # | Finding | Fix |
|---|---|---|
| 1 | MAJOR: `consistency` between `declared` and `gate` turns `ET/test_combine_gate_words.py:667` red (an unlisted pinned file) | The field goes between `cut` and `declared` (order `signal, cut, consistency, declared, gate, verifier, result`). `:667` and `ET/test_combine_evidence_words.py:354` stay green; the dump-order tests (`ET/test_combine_declared_exclusion.py:90`, `ST/test_declared_signals.py:293`) dump wires without consistency. Updated: erd §6, P13 (with WHY), C4, C8, CR-3, CR-D1, CR TDD #9 (renamed `..._orders_cut_consistency_declared_gate`), the SDK `to_dict` place, overview §8, plan §6. |
| 2 | STRUCTURAL: `sample_texts` copied the url4 row parse of `_panel_outputs` and split the context parse over two modules | One helper `_panel_rows(value, names, *, what, mismatch)` in `E/combine/spec.py`; `_panel_outputs` calls it with today's texts. `parse_context(..., samples_n: int \| None = None)` parses the rows; `CombineContext.samples: Mapping[str, tuple[str, ...]]` (j order). `E/combine/consistency.py` keeps `SampleCount` and `count_samples` only. The row-shape cases moved from CV-E1 to CR-E2 with exact messages. |
| 3 | `_from_spec(_spec())` raised for `Consistency`; the INVARIANT was false | `Consistency._entry(match)` writes the full entry; `combine_spec_text` calls it through one `isinstance` branch; the module INVARIANT and the `SignalSource` text change in unit 3; CA-1 and CB-D4 check `_from_spec(c._entry(M)) == c`. |
| 4 | `counts` could not reach `_column` | Pinned: `_signal_values(..., counts)`, `_column(..., counts)`, the `_SampleDeclared` branch, the `_Plan.declared` union. |
| 5 | a second keyword `samples=` beside `recorded=` through about 13 call sites | `recorded` becomes `_Recorded`, a mapping over the signal values that also carries `samples`; no call site changes and no new keyword (smaller rebase with part 6). |
| 6 | unit 3 too large | Split: unit 3 consistency-api-source (CA#2, CA#3, CA#14; the PIN), unit 4 consistency-api-compile (CA#1, CA#4–13). Later units renumbered 5–7; plan §2, §3, §4, §6 updated. |
| 7 | three dependency orders with no WHY | P7, P8, erd §7, API delta 4: the members stay first because S/_case_views.py:41-45 and :277 slice `depends_on[:len(members)]`; CA#8 checks it. |
| 8 | the sampler reuse looked like scope drift | P5 and the epic map row state why `sf.samples()` and `derive_attempt_seed` are not called (seed refusal, colliding defaults, Engine-only code) and that the idea is used. |
| 9 | CB-E1..E6 oracle not exact | Each row asserts the exact text; one correction at the first run is allowed and goes to the ledger and overview §10. test-plan §2 states the rule. |
| 10 | schema PIN row had no exact oracle | CR TDD #13 lists the exact `required` lists, `additionalProperties`, bounds, the discriminator entry, the `consistency` property shape and the required counts (8 and 18), checked on the base snapshots. |
| 11 | docstrings and comments became false | Deltas now edit the evidence INVARIANT (unit 1), the `CombineContext` docstring (unit 1), the `_fusion_context` docstring and the S/url4.py:83-85 comment (unit 4), the signal-source INVARIANT (unit 3). |
| 12 | the one-Consistency rule was in a new function | It goes into `_declaration`, beside the one-`sf.Entropy` rule. |
| 13 | CN-I5 checked only the member's own sample seeds | The check covers the sample seeds of every member of the Fusion (CA-E2 has a member 2 case); the gap across two Fusions is scope note N7. |
| 14 | P7 accounting stage: the precedent was not shown | Plan §6 P7 lists both options (`generation` proposed; `synthesis` as for `judge` and `writer`). |
| 15 | up to 1024 more step rows per Case not named | Scope note N8, deferred item D9, display PRD §5. |
| 16 | the `ast` import test copied the layering gate | CV TDD row 13 is dropped (no earlier part has such a test); C7 and the value PRD cite the gate. CV rows 14 → 13, 15 → 14; 64 rows in total. |

### Status

Spec written headless from the owner answers of 2026-10-16; spec review fixes applied. Build not
started. The units append
their sections (Intent, Planned changes, Pinned edits, Test plan, Acceptance, Deviations, Outcome)
below.

## Unit 1: consistency words, samples context key and evidence record (`consistency-record`)

### Intent

PRD `consistency-record` (rows CR#1–CR#15); ans:Q3 (the source sets the temperature), ans:Q4
("the count of failed samples is recorded"); P4 (one consistency source), P9 (the context key),
P13 (the evidence record between `cut` and `declared`), P14 (the SDK mirror). The Engine gets the
spec entry `{"source": "consistency", "n", "temperature", "match"}` (`ConsistencySource`,
`ConsistencyMatch`, every key required, at most one per spec, `declares_consistency`), the
context key `samples` (`parse_context(samples_n=)`, `CombineContext.samples`, the shared url4 row
helper `_panel_rows` that `_panel_outputs` now calls with its old texts), and the optional evidence
record `consistency` (`SampleCountRecord`, CS-I1..CS-I5). The SDK gets
`sf.report.CombineSampleCount`, `CombineEvidence(consistency=...)` with the same checks, and a
strict `consistency` decoder. No code computes a value yet (unit 2). No schema id changes; every
existing evidence, spec, context and url4 keeps its bytes.

### Planned changes

- `E/combine/spec.py`: `ConsistencyMatch`, `ConsistencySource`, the `DeclaredSource` union, the
  one-consistency rule in `_check_signals`, `declares_consistency`, `CombineContext.samples` and
  its docstring, `_CONTEXT_KEYS`, `parse_context(samples_n=)`, `_parse_samples`, `_panel_rows`
  (moved out of `_panel_outputs`), `__all__`.
- `E/combine/evidence.py`: `SampleCountRecord` (`_check`: CS-I4), `CombineEvidence.consistency`
  (between `cut` and `declared`), `_check_consistency` (CS-I1, CS-I2, CS-I3, CS-I5), the module
  INVARIANT, `__all__`.
- `S/combine_evidence.py`: `CombineSampleCount`, `CombineEvidence.consistency` and its keyword,
  `_consistency_map`, `_sample_number`, `to_dict`, `__all__`.
- `S/_evaluation/combine_evidence.py`: `_OPTIONAL_EVIDENCE_KEYS` (+ `consistency`),
  `_SAMPLE_COUNT_KEYS`, `_consistency`, `_sample_count`.
- `S/report.py`: export `CombineSampleCount`.
- New tests: `ET/test_combine_consistency_words.py` (50 items),
  `ST/test_consistency_words.py` (22 items).

### Pinned edits

- `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-spec.v1.json`:
  regenerated; adds `$defs.ConsistencySource`, `$defs.ConsistencyMatch` and the `consistency`
  member of the `signals` union only.
- `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`:
  regenerated; adds `properties.consistency` and `$defs.SampleCountRecord` only.
- `packages/screamingface/tests/public_surface_snapshot.json`: regenerated; `CombineSampleCount`
  (export and class entry), the `CombineEvidence.__init__` keyword `consistency`,
  `CombineEvidence.consistency`.

### Test plan

- 15 PRD rows in PRD §7 order. CHAR: CR#1 (two functions, ET and ST; fixed lists L37 and L47,
  48 specs), CR#2, CR#15, and the CR#6 companion `test_the_quorum_panel_keeps_its_messages`. RED:
  CR#3–CR#12, CR#14. PIN: CR#13, CR#14 (surface).
- Stubs in commit A: `ConsistencyMatch` / `ConsistencySource` not in the union,
  `declares_consistency` raises `NotImplementedError`, `CombineContext.samples` (default None),
  an unread `samples_n` keyword, an Engine `SampleCountRecord` with no bounds and no check, an SDK
  `CombineSampleCount` with no checks (`to_dict` raises `NotImplementedError`). Commit A: ET 45
  failed / 5 passed, ST 20 failed / 2 passed.
- Oracles: CR-2 (`("x", "z")`, j order), CR-3 (`2/4 = 0.5`, `2/2 = 1.0`, all failed → null), the
  fixed messages of the unit spec §3 and CR-E2.

### Acceptance

- A spec with one consistency entry parses on the Engine; a bad entry (bounds, missing keys, extra
  keys, two entries) is `combine_spec_invalid` with a fixed message that echoes no value; the bare
  entry stays refused.
- `parse_context(..., samples_n=n)` gives each member's sample texts in j order; a missing, extra
  or bad `samples` value is `combine_spec_invalid` with the exact CR-E2 text; the quorum panel keeps
  its texts.
- The evidence writes `consistency` between `cut` and `declared`, record keys in order; CS-I1..CS-I5
  refuse mismatches on both sides.
- The SDK decodes and writes back the record byte for byte; `sf.report.CombineSampleCount` exists.
- The 37 cases of L37 and the 48 specs of L47 keep their bytes and have no consistency.
- Gates: append-only lists only the three pinned files; every other gate green; `repo` green.

### Deviations

- (pre-filled) D-1: CR#15 is a CHAR row: the SDK spec decoder already accepts any object entry in
  `signals` (`_is_signals`), so the test passes at commit A (PRD §7 row 15 asked to record this).
- (pre-filled) D-2: CR#1 is two test functions (ET and ST). The L47 part checks the `source` words
  of each parsed spec and the absence of a url4 struct key `samples:` (regex), not
  `declares_consistency`, so that the CHAR row uses no new name and passes at commit A. The L47
  files hold 48 combine specs.
- (pre-filled) D-3: CR#6 has a CHAR companion, `test_the_quorum_panel_keeps_its_messages`
  (3 params): no existing test pins the quorum panel texts, and `_panel_rows` moves them.
- (pre-filled) D-4: CR#4 and CR#6 start each param with a positive control (the CR-1 entry parses;
  the CR-2 context parses). Without it, 11 of the 12 CR#4 params and 2 of the CR#6 params would
  pass at commit A with the same message for the wrong reason.
- (pre-filled) D-5: CS-I5 also refuses a member row without the declared name in `signals` (a
  missing key is not read as None), and CS-I3 refuses an `n` that is not an `int` (a bool
  included). Both sides.
- (pre-filled) D-6: the SDK `CombineSampleCount` checks `member_id` with the member-id rule
  (`member_N`), as `CombineAnswerRow` does; the Engine keeps a plain `str` (CS-I2 ties it to the
  members). The SDK keyword `consistency` is the LAST keyword of `CombineEvidence.__init__`; the
  stored field and the wire key sit between `cut` and `declared`.
- (pre-filled) D-7: the samples parse is a private helper `_parse_samples` (the PRD wrote it
  inline in `parse_context`). CR#8 adds three cases to CR-E3: `matched -1`, the record under
  another name (CS-I1), and a member without the value key (CS-I5).

### Notes for the review

- Interim gap until unit 2: a spec with a consistency entry parses, but the endpoint refuses it at
  `_declared` (`a declared signal source is not registered`, `combine_spec_invalid`), and the
  endpoint never passes `samples_n`. No released code has this state.
- For unit 2: build `SampleCountRecord` with KEYWORDS (`SampleCountRecord(member_id=m,
  matched=c.matched, succeeded=c.succeeded, failed=c.failed)`); the consistency-value PRD writes it
  positionally as shorthand. `parse_context(..., samples_n=entry.n)` with `entry` from
  `declares_consistency(spec)`. `context.samples[m]` is a tuple of texts in j order.
- `CombineContext.samples` and the SDK `CombineEvidence.consistency` are `MappingProxyType`
  values (read-only), as `sources` and `signals` are.

### Outcome (fill at the end — required before COMMIT)

- **Status:** DONE. Commit B is green on all three stacks, except the append-only check, which lists only the three pinned files (see Gates).
- **Actual files:** the Engine files `combine/spec.py` and `combine/evidence.py`; the SDK files `combine_evidence.py`, `_evaluation/combine_evidence.py` and `report.py`; the three pinned files. The stubs of commit A were replaced by the code of Appendices A and B (applied as patches against `f5db24fe7`). No test file changed after commit A.
- **Commits:** A `a3d577f72` (RED tests and stubs). B `b2ae6be62` (code and pinned regeneration). C: this docs commit.
- **Gates:** Engine stack: ruff check, ruff format, pyright, layering check and pytest (coverage floor 80 percent) all pass. The append-only check lists only `screamingface.combine-spec.v1.json` and `screamingface.combine-evidence.v1.json`; the run passed again with `--skip-append-only`. SDK stack: ruff check, ruff format, pyright, pytest (coverage floor 95 percent), notebooks, build and distribution all pass. The append-only check lists only `tests/public_surface_snapshot.json`; the run passed again with `--skip-append-only`. Repo stack: all green with no flag.
- **Focused runs:** Engine `test_combine_consistency_words.py` 50 of 50 passed, then the spec group of 308 passed. SDK `test_consistency_words.py` and the spec group of 166 passed. `test_wire_schema_freeze.py` 10 passed. The schema diff check (Appendix F) printed `snapshot diff OK`. The surface diff matches Appendix G (14 insertions, 1 deletion).
- **RED log:** commit A. Engine file: 45 failed, 5 passed. SDK file: 20 failed, 2 passed. Every failure has the reason of spec section 5; no import, collection or name error. The CHAR rows pass. `ET/test_wire_schema_freeze.py` (10 passed) and `packages/screamingface/tests/test_public_surface.py` (8 passed) stay green. Ruff format and ruff check pass on both new files. Before the pinned regeneration, the only red test in the Engine file was CR#13 (`KeyError: 'consistency'`), as the spec expects.
- **Flakes:** none in this unit.
- **Deviations:** none beyond the pre-filled items D-1 to D-7. The pinned schema files were removed and regenerated with the procedure of spec section 8.2; the line counts match (58 and 62 insertions).
- **Approval blobs (base, after):**
  - `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-spec.v1.json`: base `b62a7858ca4c9877398bf4cfaa2208ae178bb47e`, after `837a7ee3531b4049e069457cb9c5711cf0a4378f`
  - `apps/screamingface-engine/tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json`: base `9f150b3bc73cb4d1e07f59800091c7d41d626616`, after `ebb34ae62020e6a6c12b62cf01312fd60acbd818`
  - `packages/screamingface/tests/public_surface_snapshot.json`: base `385cda6769a9672677a911b732a85372beffd513`, after `8400871fb64d20c385ccccacb0ae6e1aba4aa6d1`
