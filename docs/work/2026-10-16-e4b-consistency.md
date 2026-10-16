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

## Unit 2: consistency value (`consistency-value`)

### Intent

PRD `consistency-value` rows CV#1–14 (ans:Q4; P9–P13, P20–P22). The combine step computes, for each
member, `matched / succeeded` over its successful extra samples, after the declared match steps
(read cap, extract, normalize). A failed sample is not in the denominator; its count is recorded.
All samples failed, or no member match value → the value is missing, and a rule that reads it
excludes the member. The samples never vote. Every exit writes the evidence record `consistency`.
A new contract file `consistency_evidence_cases.json` (three scenarios) is read on both sides.

### Planned changes

- New `E/combine/consistency.py` (pure, standard library only): `SampleCount`, `count_samples`.
- `E/combine/endpoint.py`: `_SampleDeclared` (with `match_value`), `_Recorded` (a read-only mapping
  over the signal values with `samples`), `_Plan.declared` union, `_combine` (`samples_n=`, the
  counts once), `_sample_counts`, `_sample_item`, `_signal_values(..., counts)`, `_reader_numbers`
  annotation, `_column(..., counts)` with the `_SampleDeclared` branch, the six `recorded:`
  annotations, `_evidence` (`consistency=`), `_consistency_record`, `_declared`, `_sample_source`,
  the module INVARIANT sentence.
- Tests: new `ET/combine_consistency_support.py`, `ET/test_combine_consistency.py`,
  `ET/test_combine_consistency_contract.py`, `ST/test_consistency_evidence_contract.py`; new data
  file `ET/data/combine_contract/consistency_evidence_cases.json` (written by `write_fixture()`).

### Pinned edits

None. New files only, plus the source edits above.

### Test plan

- 14 rows (CV#1–14). CHAR: CV#1 (37 items) and the CV#6 param `samples-without-a-declaration`.
  RED: the others. Commit A adds the stub `E/combine/consistency.py` (`count_samples` raises
  `NotImplementedError`) and no other source change; the RED reason of the Engine runs is
  `SpecInvalid: a declared signal source is not registered` (the unit 1 endpoint).
- Expected RED: Engine 28 failed, 38 passed; SDK 5 failed (missing data file).

### Acceptance

- Fixture V: values 0.5, 1.0, None; record `{2,4,0}`, `{2,2,2}`, `{None,0,4}`; the vote result is
  unchanged (`"so 12"`, agreement 0.6666666666666666).
- Fixture W: values 0.6666666666666666, 0.0, 1.0; chosen member_3; output `"A"`.
- All samples failed → value None → `excluded`/`no_signal`; the Case answers.
- The samples never vote; an unreadable sample is succeeded and not matched; no voter still records.
- A spec without consistency writes no `consistency` key (the 37 cases of L37).
- The contract file holds exactly the three scenarios; the SDK decodes and round-trips each.
- Gates: `screamingface-engine`, `screamingface`, `repo` green.

### Deviations

- `_column` keeps the PRD's first branch (`_SampleDeclared`), and its last two branches become one
  conditional return, because ruff `max-returns = 3`.
- New test support module `ET/combine_consistency_support.py` (not in the PRD file list): fixtures
  V and W are shared by the row tests and the contract test.
- Row CV#2 has a second function for the pure `count_samples` (and commit A has its stub). CV#7
  adds a `match.normalize` case. CV#9 adds a number 12 over the read cap and a control under it.
  CV#11 adds a passing gate case. CV#12 adds a member text over the read cap.
- New private names not in the PRD: `_SampleDeclared.match_value`, `_sample_item`,
  `_sample_source`, `_consistency_record`; the `_Recorded` field is `numbers`; two `RuntimeError`
  guards (`_sample_counts`, `_column`); `count_samples` raises `ValueError` for more texts than n
  and does not call `read` when there is nothing to compare.
- No change beyond the list above. The §6.7 patch applied with `git apply` on the commit A tree.
  The contract file was written by `write_fixture()`, not by hand.

### Notes for the review

- C7: `E/combine/consistency.py` imports only `collections.abc` and `dataclasses`.
- P22: `git diff <unit-1 tip> -- apps/screamingface-engine/src/screamingface_engine/combine/endpoint.py`
  shows no changed call site of an exit and no new keyword.
- CS-I5 holds by construction: the column value and the record both come from `SampleCount`.

### Outcome (fill at the end — required before COMMIT)

- **Status:** DONE. Commit B is green on all three stacks. The append-only check named only the pinned files of unit 1 (see Gates).
- **Actual files:** `E/combine/consistency.py` (the commit A stub replaced by the full module); `E/combine/endpoint.py` (the §6.7 patch, 21 hunks); new `ET/data/combine_contract/consistency_evidence_cases.json` (three scenarios, written by `write_fixture()`). No test file changed after commit A.
- **Commits:** A `e4e8b4b83` (RED tests and stub). B `1c8ac5b0b` (the code, the contract data file and this Outcome). C, the last commit of this unit (the overview errata and this line).
- **Gates:** Engine stack: the append-only check lists only `screamingface.combine-spec.v1.json` and `screamingface.combine-evidence.v1.json`, both changed by unit 1 commit `b2ae6be62`. The run passed with `--skip-append-only`: ruff check, ruff format, pyright, layering check and pytest (coverage floor 80 percent) all pass. SDK stack: the append-only check lists only `tests/public_surface_snapshot.json`, changed by unit 1 commit `b2ae6be62`. The run passed with `--skip-append-only`: ruff check, ruff format, pyright, pytest (coverage floor 95 percent), notebooks, build and distribution all pass. Repo stack: all green with no flag. Focused runs: the three Engine consistency files give 116 passed; the 16 regression files give 365 passed; the SDK contract files give 66 passed; `check_layering.py` (under `uv run`) passes.
- **RED log:** commit A. Engine (`test_combine_consistency.py` + `test_combine_consistency_contract.py`): 28 failed, 38 passed (37 CV#1 items and CV#6 `samples-without-a-declaration`). Failures: `SpecInvalid: a declared signal source is not registered` (CV#2 endpoint, CV#3, CV#4, CV#5, CV#6 params 1-2, CV#7 four params with the wrong code or message, CV#8, CV#9, CV#10, CV#11, CV#12); `NotImplementedError` from the stub (CV#2 pure test); `missing contract fixture` (CV#13, three byte params, two fixture tests). SDK (`test_consistency_evidence_contract.py`): 0 passed, 5 failed, all `missing Engine contract fixture`. Ruff check, ruff format and pyright are clean on the new files.
- **Pinned edits made:** none

## Unit 3: consistency-api-source (`sf.Consistency`, the Fusion rules)

### Intent

PRD `consistency-api` rows CA#2, CA#3, CA#14 (ans:Q3; P2, P4, P5; erd CN-I1..CN-I6). The SDK gets
the public source `sf.Consistency(n, *, temperature=1.0)`: `n` an int from 1 to 32,
`temperature` finite and at least 0 (stored as a float), its repr and Python form, `_spec()` (the
entry without `match`) and `_entry(match)` (the full wire entry). New helper
`consistency_seed(k, j)` (erd §2). `sf.Fusion` refuses, before any call: two `sf.Consistency`
sources, a member that is not one `sf.Model`, more than 1024 extra calls, and a member seed equal
to a sample seed of any member. No compile path reads a `Consistency` yet (unit 4).

### Planned changes

- `S/signal_sources.py`: `Consistency` (`n`, `temperature`, `__repr__`, `_spec`, `_entry`, a
  `_from_spec` stub), `_MAX_CONSISTENCY_N`, `_sample_temperature`, `consistency_seed`; the module
  docstring line 1 and INVARIANT; the `SignalSource.source` comment; `__all__`.
- `S/__init__.py`: export `Consistency`.
- `S/fusion.py`: the one-`sf.Consistency` rule in `_declaration`; `_MAX_CONSISTENCY_CALLS`,
  `_check_consistency_source`, `_check_sample_seeds`; one call in `Fusion.__init__`.
- New test file `ST/test_consistency_api.py` (6 tests, 28 ids).

### Pinned edits

- `packages/screamingface/tests/public_surface_snapshot.json` (regenerated with
  `UPDATE_SURFACE_SNAPSHOT=1`): `Consistency` in `screamingface.__all__` and `exports` (its
  `__init__`, the fields `n` and `temperature`, the attribute `source`).

### Test plan

- 3 rows: RED CA#2 (`test_consistency_holds_n_and_the_temperature`,
  `test_consistency_refuses_bad_values`, `test_consistency_seed_gives_the_erd_seeds`); RED CA#3
  (`test_fusion_refuses_a_bad_consistency_declaration_before_any_call`, 8 ids, of which
  `model-synthesizer` is CHAR) with the CHAR control
  `test_fusion_accepts_a_consistency_declaration_at_the_limits`; PIN CA#14
  (`test_public_surface_has_sf_consistency` and the regenerated snapshot).
- Stubs (commit A): `Consistency` with the exact `__init__` signature that stores `n` and
  `temperature` with no check; `_spec`, `_entry`, `_from_spec` and `consistency_seed` raise
  `NotImplementedError`; `sf.Consistency` exported. Expected RED: `26 failed, 2 passed` in the new
  file; `test_public_surface_matches_the_committed_snapshot` fails.
- Oracles: the PRD texts (CA-E1, CA-E2), the erd §2 seeds, the hand-written snapshot entry.

### Acceptance

- The 28 ids pass. The CHAR ids pass before and after the change.
- The snapshot diff against `U2` is only the two hunks of the pinned edit.
- `git diff U2 --stat` on the test folders lists only the new file and the snapshot; on the
  source folders only `S/signal_sources.py`, `S/fusion.py`, `S/__init__.py`.
- Gates: `screamingface`, `repo` green, except the append-only check against `633fec3a1`, which
  lists only the pinned files of units 1 and 3; green with `--skip-append-only`.

### Deviations

- D-U3-1 (`_from_spec` stub): `SignalSource._from_spec` is abstract, so `Consistency` needs one to
  be constructible. This unit adds a stub that raises `NotImplementedError`; `_SOURCES` does not
  list `consistency`, so no path calls it. Unit 5 (consistency-rebuild) replaces it (PRD delta 3)
  and adds `_SOURCES["consistency"]`. Until then the module INVARIANT states the target of unit 5.
- D-U3-2 (the seed comparison, CN-I5): the PRD says "a member `seed` param equal to
  `consistency_seed(k, j)`". The built rule compares the url4 text (`str(seed)`), because the url4
  carries a param as text (`_scalar`, S/_evaluation/policy.py:26-29): an `int` seed and a `str`
  seed with the same digits are refused; a `float` seed (`2063835758.0`, other text) and a `bool`
  seed are not.
- D-U3-3 (helpers): `_MAX_CONSISTENCY_N`, `_sample_temperature`, `_MAX_CONSISTENCY_CALLS`,
  `_check_sample_seeds` are private helpers that the PRD does not name. They keep the ruff caps.
- D-U3-4 (more cases): CA#2 adds `n` -1, 3.0, "3", None and `temperature` inf, None, 10**400
  (an `int` beyond the float range; `OverflowError` is caught), and the check order. CA#3 adds a
  Pipeline member, a seed given as text (s(3,2), j ≠ 1), and a CHAR control test (the 1024 limit,
  seeds that are not refused).
- D-U3-5 (CA#14 test): the introspection test also reads the snapshot JSON, so it is RED until the
  pinned edit is made.
- D-U3-6 (line 1): the docstring summary says "(E4b)" instead of "(E4b part 3)", to name
  `sf.Consistency` in 100 characters.

### Outcome

- **Status:** DONE (commit B). The code is built and the gates pass, with one gate exception
  (see Gates).
- **Actual files:** `S/signal_sources.py`, `S/fusion.py` (commit B); `ST/public_surface_snapshot.json`
  (PINNED, regenerated in commit B); the ledger section (commit B). `S/__init__.py` and
  `ST/test_consistency_api.py` were set in commit A.
- **Commits:** A = 4d681228a (RED, stub, export, ledger section). B = the commit that adds this
  Outcome; its sha is the head of the branch at the end of the unit.
- **U2 (unit 2 tip):** a60999e66
- **RED log:** Recorded in commit A. This build did not run the RED state again; the GREEN run
  below ran on the commit B tree.
- **Gates:**
  - `screamingface` (`--base 633fec3a1`): the append-only check is RED. Its only offender is
    `tests/public_surface_snapshot.json` (the PINNED edit of this unit). With
    `--skip-append-only`, every other gate is green: ruff check, ruff format, pyright, pytest with
    the coverage floor (95 %), the notebook check, uv build and the distribution check.
  - `repo` (`--base 633fec3a1`): green, including the append-only check.
  - Focused tests: `tests/test_consistency_api.py` and `tests/test_public_surface.py` give 36
    passed (28 ids in the new file). The related files of §9 give 107 passed.
- **Flakes:** None seen in this unit.
- **Deviations (build):** None beyond the spec. The pinned snapshot holds the two hunks of §8 only
  (checked with `git diff` against commit A).

## Unit 4: the consistency sample calls (`consistency-api-compile`)

### Intent

PRD `consistency-api`, rows CA#1 and CA#4–CA#13 (ans:Q3, ans:Q4; P3, P5–P9, P17–P19; erd §2,
§3, §4, §7; contracts C1, C2, C3, C6). A Fusion that declares `sf.Consistency(n, temperature=t)`
compiles to n sample calls for each member. Each sample call is a model call with the binding
param first, the member's other params, `temperature=t` and `seed=consistency_seed(k, j)`. The
calls of one member sit in one broadcast panel with `quorum=0` and optional slots `sample_j`.
Each sample call has one operation (kind `sample`, label `"{member} sample"`) and one parameter
assignment. The combine context gets `samples` after `outputs` (or `panel`) and before `signals`.
The spec entry gets `match`. The combine `depends_on` is members, then signals, then samples. The
reducer topology node gets `samples` (encode only). Accounting maps `sample` to `generation`. The
fixed-seed warning skips the samples. A corrective loop that holds `sf.Consistency` is refused.
Two SDK-compiled url4 fixtures have a drift guard. The Pick fixture runs offline in the Engine
world, once with every sample answered and once with one sample that fails.

### Planned changes

- `S/_evaluation/combine_spec.py`: the `isinstance(source, Consistency)` branch and
  `_consistency_match`.
- `S/_evaluation/candidate.py`: `_SAMPLE_PARAMS`, `_CompiledSamples`, `_NO_SAMPLES`,
  `_consistency_source`, `_sample_panels`, `_sample_call`; `input_dependencies` passed through
  `_fusion` into `_reducer_synthesizer`; `_fusion_context(samples=)` and its docstring; combine
  `depends_on`; reducer node `samples`.
- `S/_evaluation/topology.py` (encode only): role `sample`, `_SampleTopology`,
  `_RecipeTopology.samples`, `_operation_shape`, `_encode_reducer`.
- `S/url4.py`: the context-order comment only.
- `S/_evaluation/corrective.py`: `_CONSISTENCY_IN_LOOP`, `_refuse_consistency` (first statement of
  `_compile_corrective`).
- `S/accounting.py`: `_ACCOUNTED_STAGES["sample"] = "generation"`.
- `S/_evaluation/runner.py`: `_own_seed_calls` skips kind `sample`.
- Tests (commit A): `ST/test_consistency_api.py` (imports added, block appended),
  new `ST/test_consistency_contract_fixtures.py`, new `ET/test_combine_consistency_run.py`.
- New fixtures (commit B, SDK writer only): `ET/data/combine_contract/consistency_pick_candidate.url4`,
  `ET/data/combine_contract/consistency_median_candidate.url4`.
- No Engine source change. No public name.

### Pinned edits

None. `ST/test_consistency_api.py` is new since `633fec3a1` (created by unit 3). The other test
files and the two fixtures are new files.

### Test plan

- 11 PRD rows: CA#1 (CHAR, 5 items), CA#4 (2 functions), CA#5, CA#6 (2 items), CA#7 (1 function
  with 2 runs), CA#8, CA#9, CA#10 (2 items), CA#11 (2 functions), CA#12 (2 functions), CA#13
  (1 function with 3 items).
- No stub in commit A. Every imported name exists after unit 3. The compile of F1 works but has no
  sample calls, so each RED fails on an assertion, a KeyError of a missing source, a missing
  fixture, a "DID NOT RAISE", or (CA#13) `PlanningError` for mid-run checking.
- Invariants: SC-I1 (binding first, CA#11), SC-I3 (samples are not in `outputs`, CA#5), CX-I1
  (every member in `samples`, CA#5), P7 order (CA#8), P8 topology (CA#9), P18 (CA#12), P19 (CA#13).

### Acceptance

- F1 compiles to `model_4..model_12` in `panel_1..3` (quorum 0, optional slots), with the seeds of
  erd §2 and `temperature=1.0`. The combine context and spec match CA-3. The operations and
  assignments match CA-4. The reducer node matches CA-5.
- The Engine world runs the F1 fixture: 12 requests, output `"A"`, member values 0.6666666666666666,
  0.0 and 1.0. With the seed 137802004 sample failing: output `"A"`, the Case completes, and the
  member_3 record is `{matched 2, succeeded 2, failed 1}`.
- `screamingface-engine`, `screamingface` and `repo` gates are green. The append-only check names
  only the plan §6 files of units 1 and 3.

### Deviations

- D-1 (planner): `_sample_panels` runs for every reducer Fusion and returns an empty
  `_CompiledSamples` when no `sf.Consistency` is declared. The PRD says "when the Fusion declares
  a Consistency". The bytes are the same, and there is one call site with no branch.
- D-2 (planner): the corrective refusal is the first statement of `_compile_corrective`, before
  the check-surface check. The Recipe error shows on every benchmark.
- D-3 (planner): CA#7 checks the evidence fields of fixture W (chosen, signal, member values,
  `consistency`, `declared`, result) and not the whole evidence object.
- D-4 (planner): CA-D4 uses a hand-built `CandidateResult` (kind `model`, no members). The sample
  row and the member row both have `member_id None` there.
- D-U4-1 (build, commit A): the RED tests use the `_ca_*` helper names of spec §6.1. The
  `test_consistency_api.py` import block was merged into one block in isort order. No existing
  test line changed.
- D-U4-2 (build, commit A): the commit A title follows the orchestrator brief,
  `test(e4b): RED for E4b part 7 unit 4 consistency-api-compile`, and not the spec §12 title.
- D-U4-3 (build, commit B): `fingerprint()` in `ST/test_consistency_api.py` (CA-D2) has the
  return type `tuple[str, tuple[tuple[str, str], ...]]`. The url4 `Params` value holds `str | None`,
  so pyright reports a return type error. The fix changes only that annotation to
  `tuple[str, tuple[tuple[str, str | None], ...]]`. No assertion changed. This is the one edit to a
  test that commit A added. It is in commit B, so the owner must review it.
- D-U4-4 (build, commit B): the fixed-seed skip in `_own_seed_calls` uses the spec body (an
  `operations` map). Its output is the same as the old `labels` map for every call that is not a
  sample.

### Outcome

- **Status:** DONE. Commit B holds the code and the two fixtures. Commit C holds this section.
  All three gate stacks are green. Two gate runs skipped the append-only check, as the plan
  allows (see Gates).
- **Actual files (commit B):** `packages/screamingface/src/screamingface/_evaluation/candidate.py`,
  `_evaluation/combine_spec.py`, `_evaluation/topology.py` (encode side only),
  `_evaluation/corrective.py`, `_evaluation/runner.py`,
  `packages/screamingface/src/screamingface/url4.py` (comment only), `accounting.py`,
  `packages/screamingface/tests/test_consistency_api.py` (one annotation, D-U4-3), and the two new
  fixtures `apps/screamingface-engine/tests/unit/data/combine_contract/consistency_pick_candidate.url4`
  and `consistency_median_candidate.url4`, written with the SDK writer.
- **Commits:** A = 114ecdfa8 (RED). B = 8a765c59d (code, fixtures, D-U4-3). C = the commit that adds
  this Outcome; its sha is the head of the branch at the end of the unit.
- **RED log (focused tests at commit A):**
  - `packages/screamingface`: `tests/test_consistency_api.py` and
    `tests/test_consistency_contract_fixtures.py`: 33 passed, 17 failed. The 5 CA#1 items and the
    unit 3 tests pass. The 17 failures are the RED rows, each for its expected reason: root names
    and panels (CA#4, CA#13 quorum), missing `match` and `samples` in the context (CA#5), operation
    list (CA#8), rider `samples` (CA#9), "DID NOT RAISE PlanningError" (CA#10 x2), KeyError of
    `model_4` and `model_3` (CA#4 member params, CA#11 x2), 0 sample operations (CA#12), missing
    accounting row (CA#12), `PlanningError` for mid-run checking instead of the ValueError
    (CA#13 x3), missing fixture (CA#6 x2).
  - `apps/screamingface-engine`: `tests/unit/test_combine_consistency_run.py`: 1 failed on
    "combine_contract/consistency_pick_candidate.url4 is missing - write it with the SDK" (CA#7).
  - Ruff check and ruff format: see the commit A check.
  - This build did not run the RED state again.
- **GREEN checks run on the commit B tree:**
  - `packages/screamingface`: `tests/test_consistency_api.py` and
    `tests/test_consistency_contract_fixtures.py`: 50 passed. The focused list of spec §10 (14
    files): 146 passed.
  - `apps/screamingface-engine`: the six Engine files of spec §10: 20 passed. This includes
    `test_combine_consistency_run.py` (CA#7) with the failed sample (seed 137802004, HTTP 400).
- **Gates:**
  - `screamingface-engine` (`--base 633fec3a1`): the append-only check is RED. Its only offenders are
    `tests/unit/data/combine_contract/schemas/screamingface.combine-evidence.v1.json` and
    `tests/unit/data/combine_contract/schemas/screamingface.combine-spec.v1.json`. Both are the
    PINNED edits of unit 1 (plan §6, b2ae6be62). Unit 4 adds no change to them (checked against
    114ecdfa8). With `--skip-append-only`, every other gate is green: ruff check, ruff format,
    pyright, the layering check and pytest with the coverage floor.
  - `screamingface` (`--base 633fec3a1`): the append-only check is RED. Its only offender is
    `tests/public_surface_snapshot.json`, the PINNED edit of unit 3 (plan §6, da12433b7). Unit 4
    adds no change to it (checked against 114ecdfa8). With `--skip-append-only`, every other gate is
    green: ruff check, ruff format, pyright (after D-U4-3), pytest with the 95 percent coverage
    floor, the notebook check, uv build and the distribution check.
  - `repo` (`--base 633fec3a1`): green, including the append-only check.
- **Flakes:** none seen in this unit. No test was rerun.
- **Follow-ups (not in this unit, for the orchestrator):**
  - Refactor: `_sample_call` (`_evaluation/candidate.py`), `_CandidateCompiler._model` and
    `_model_signal_source` (`_evaluation/reducer_signals.py`) repeat the same steps to build one
    model call. One helper `_bound_model_call(route, context, prompt, params, binding)` can serve
    the sample and signal paths.
  - E4c backlog: `budget.py` (SDK and Engine) has no stage for operation kind `sample`. When E4c
    charges calls per operation kind, map `sample` to budget stage `model`.
  - Review text: the `_refuse_consistency` docstring WHY (D-2) says the refusal shows on every
    benchmark. Through the runner, the check-surface preflight runs first. The text is verbatim
    from the spec, so the owner must choose the wording.
  - Unit 5 scope: the url4 decoder does not know the `samples` key yet. Decode for the plain F1/F2
    fixtures, the judge-fallback shape (CB-3) and a Consistency Fusion inside a quorum Fusion
    member must come in unit 5.
- **Deviations:** D-1 to D-4 (planner), D-U4-1 and D-U4-2 (commit A), D-U4-3 and D-U4-4 (commit B).
  No deviation changes the PRD, so no line was added to overview §10.
- **Pinned edits:** none made in this unit. The owner must review D-U4-3, the one edit to a test that
  commit A added.

## Unit 5: url4 rebuild and replay (`consistency-rebuild`)

### Intent

PRD `consistency-rebuild`, rows CB#1 to CB#9 (P8, P16, P18, CN-I6, erd §7, C5). A consistency
url4 rebuilds and replays. `Url4.to_python()` writes `signals={'cons': sf.Consistency(n=3,
temperature=1.0)}` and the members as the author wrote them, and leaves out every sample call. A
replay shows the compile's operations (kind `sample`, label `{member} sample`) in the compile
order, pins the match operators against the Engine before any spend, and lists no sample call as
a fixed-seed call. A hand-edited url4 fails with one of the four existing C5 texts.

### Planned changes

- `S/_evaluation/topology.py`: `_decode_synthesizer` accepts `samples`; new `_decode_samples`
  and `_decode_sample_source` (every break is the reducer error); `_visit_reducer` takes the
  Fusion's `operations`, visits the sample calls (member rule) before the signal calls, and gives
  the reducer the context order `(fusion context, samples, signals)` and the operation order
  `(members, signals, samples)`.
- `S/url4.py`: `_require_call_kind` needs the binding param first on a `sample` call.
- `S/signal_sources.py`: `Consistency._from_spec` (keys exactly `source`, `n`, `temperature`,
  `match`; `match` keys exactly `extract`, `normalize`); `_SOURCES` adds `consistency`.
- `S/_evaluation/combine_spec.py`: `spec_operator_pairs` adds the match pairs (name order, each
  pair once); new `_match_pairs`, `_MATCH_STAGES`.
- `S/_evaluation/url4.py`: the replay `seeded` tuple leaves out the `sample` operations.
- New test file `ST/test_consistency_rebuild.py`. No Engine change. No public name.

### Pinned edits

None. The test file is new.

### Test plan

- 9 PRD rows: CB#1 CHAR (5 items, list L5); CB#2 (2 items), CB#3, CB#4 (2 functions), CB#5
  (6 hand edits and 13 malformed `samples` shapes), CB#6, CB#7, CB#8, CB#9 RED.
- RED stub: none new. The RED reason is the decoder's refusal of `samples` (CB#2-6, CB#9), the
  two step pairs of `spec_operator_pairs` (CB#7) and unit 3's `_from_spec` stub (CB#8). The CB#5
  functions start with a control rebuild of the untouched F1 url4, so no case passes in RED for
  the wrong reason.
- Invariants: CN-I6 (`_from_spec(_entry(match)) == source`), erd §7 (the two dependency orders),
  C5 (four texts), P18 (no sample in `seeded`).

### Acceptance

- F1 and F2 rebuild to the exact Python text of the unit spec §4 and recompile to the fixture
  bytes. F3 and a two-stage Pipeline round-trip. The replay operations equal the compile
  operations.
- Each hand edit E1..E6 fails with its exact C5 text in `to_python` and in the replay; every
  malformed `samples` shape is "invalid Reducer topology metadata"; a `samples` key without a
  declaration is "does not match its Recipe metadata".
- `spec_operator_pairs` lists `last_line@1` and `text@1` for F1; a replay against a catalog
  without `text@1` fails before the transport runs.
- `screamingface` and `repo` gates are green (the append-only check names only the plan §6 files
  of units 1 and 3).

### Deviations

- D-1 (planner): PRD §3 F3 writes `sf.Vote(judge=sf.Judge(...))`. `sf.Vote` refuses that ("Vote
  judge is read only by weights=sf.signal('score:judge')"). F3 adds
  `weights=sf.signal("score:judge")`, the existing judge-weighted vote shape
  (`judge_vote_candidate.url4`). The bindings and both dependency orders of CB-3 do not change.
- D-2 (planner): CB#4 adds a second function, a two-stage Pipeline (CA-D6 shape). It checks the
  new `operations` argument of `_visit_reducer`; at the top level that argument is `()` and a bug
  would not show.
- D-3 (planner): CB#5 adds a second function with 13 malformed `samples` shapes (PRD delta 1:
  "Any break: ValueError(_REDUCER_INVALID)"), and both CB#5 functions start with a control rebuild.
- D-4 (planner): `spec_operator_pairs` lists each pair once (`dict.fromkeys`). A median's match
  repeats its own steps (F2); every existing spec has four different pairs, so no existing result
  changes. CB#7 checks F2.
- D-5 (planner): CB#2 also checks F2, and CB#3 adds hand-written kinds, labels and dependencies
  next to the compile comparison.
- D-U5-1 (build, commit A): `ruff format` rewrapped the lines of `ST/test_consistency_rebuild.py`
  (wrapping only, no token changed) so that `ruff check` passes. The spec §6.1 text is otherwise
  kept.
- D-U5-2 (build, commit A): the ledger section is in commit A (spec §12 puts it in commit C).
  Commit C fills the Outcome.
- D-U5-3 (build, commit B): pyright reports an error in the RED file. `_compiled` is annotated
  `-> Candidate`, but `compile_candidate` returns `_CompiledCandidate`. The fix changes the
  return annotation to `_CompiledCandidate` and adds that name to the existing import from
  `screamingface._evaluation.candidate`. No assertion changed. This is the one edit to a test
  that commit A added. The owner must review it.
- D-U5-4 (review fix, commits ef9393309 and ea1ff0ee0): PRD `consistency-rebuild` §2 says
  "Each sample slot is optional, so every consistency url4 takes this check" and marks the
  premise [implied]. The premise was wrong for a hand-edited url4. The recompile ran only when
  the url4 had `;optional`, `quorum=` or quorum/optional metadata. A url4 with its `;optional`
  and `;quorum=0` markers removed skipped it, and it rebuilt as a plain Fusion (F1) or as a
  plain Median with 6 paid sample calls that feed nothing (F2). The fix adds `or value.samples`
  to `_has_fusion_policy` (`S/url4.py`). A node with samples is now policy. Two tests were added
  (`test_a_consistency_url4_without_its_policy_markers_does_not_rebuild`,
  `test_a_samples_key_without_a_declaration_and_policy_markers_does_not_rebuild`). Both expect
  the metadata C5 text in `to_python` and in the replay. The PRD is not edited in this unit.
- D-U5-5 (review fix, RED 5a9b60242 and the fix commit after it): the recompile trigger in
  `_validate_topology` (`S/url4.py`) now also covers any combine spec that declares `signals`.
  Before, the trigger read only `_has_fusion_policy` and `_has_executable_fusion_policy`. Hand
  edit: add a consistency entry to the spec `signals` of a plain Median url4 (no sample calls).
  Both predicates were False, so no recompile ran. `to_python` printed
  `signals={'cons': sf.Consistency(...)}` (a recipe that compiles to a different url4, with
  sample calls), and the replay ran with no samples. Unit 5 opened this path: before it,
  `signal_sources._SOURCES` had no `consistency`. WHY: a declared source adds calls, so it must
  prove its bytes. One test was added
  (`test_a_consistency_source_added_to_a_plain_url4_does_not_rebuild`). It expects the metadata
  C5 text in `to_python` and in the replay.
- (build) Any C5 text corrected at the first GREEN run: none. All 33 items passed at the first
  GREEN run, and no expected text changed.

### Outcome

- **Status:** DONE. Commit B holds the code and the D-U5-3 fix. Commit C holds this Outcome.
  All gates are green. The append-only check of `screamingface` is skipped (see Gates).
- **Actual files (commit B):** `packages/screamingface/src/screamingface/_evaluation/topology.py`,
  `_evaluation/combine_spec.py`, `_evaluation/url4.py`, `packages/screamingface/src/screamingface/signal_sources.py`,
  `packages/screamingface/src/screamingface/url4.py`, and `packages/screamingface/tests/test_consistency_rebuild.py`
  (the D-U5-3 fix only).
- **Commits:** A = 9ef3c1a58 (RED). B = eb8772a14 (code and D-U5-3). C = the commit that adds
  this Outcome; its sha is the head of the branch at the end of the unit.
- **RED log (focused file at commit A):** `packages/screamingface/tests/test_consistency_rebuild.py`:
  5 passed, 28 failed. The 5 CB#1 items pass. Each failure has its expected reason:
  - CB#2 (F1, F2), CB#3, CB#4 (2), CB#6, and the 19 CB#5 items (6 hand edits, 13 malformed
    shapes): `ValueError: URL4 Candidate has invalid Reducer topology metadata` (the decoder
    refuses `samples`). The CB#5 items fail at the control rebuild of the untouched F1 url4.
  - CB#7: the F1 pairs assertion (only the two step pairs are listed).
  - CB#8: `NotImplementedError` from unit 3's `Consistency._from_spec` stub.
  - CB#9: `str(exc)` is `_REDUCER`, and the test expects `_METADATA`.
  No import or collection error.
- **GREEN log:**
  - `packages/screamingface`: `tests/test_consistency_rebuild.py`: 33 passed (all CB#1 to CB#9
    items).
  - The focused list of spec §10 (17 files, with `test_consistency_rebuild.py`): 308 passed. The
    run came before two line wraps (formatting only). The full `screamingface` pytest run below
    came after them.
- **Gates:**
  - `screamingface` (`--base 633fec3a1`): the first run stopped at the append-only check. Its only
    offender is `tests/public_surface_snapshot.json`, the PINNED edit of unit 3 (plan §6,
    da12433b7). Unit 5 adds no change to it (checked against f2a848c27). The second run failed on
    pyright (D-U5-3). The third run, with `--skip-append-only`, was green: ruff check, ruff format
    check, pyright, pytest with the 95 percent coverage floor, the notebook check, uv build and the
    distribution check.
  - `repo` (`--base 633fec3a1`): green, including the append-only check.
- **Flakes:** none seen in this unit. No test was rerun.
- **Pinned edits:** none. The D-U5-3 fix is an edit to a test that commit A added, not a PINNED
  edit.

### Review fixes (round 1, unit 5)

- **Findings applied:** the MAJOR finding (the policy-marker gap) and its tests. Commits:
  `ef9393309` (RED: two tests, both fail with "DID NOT RAISE" at first), `ea1ff0ee0` (fix:
  `_has_fusion_policy` reads `samples`), then the commit of this block (ledger). Deviation
  D-U5-4 records the wrong premise of PRD §2.
- **Gates after the fix:** `screamingface` run 1 stopped at the append-only check. Its only
  offender is `packages/screamingface/tests/public_surface_snapshot.json` (the unit 3 PINNED
  edit, plan §6). Run 2 used `--skip-append-only` and was green (ruff check, ruff format check,
  pyright, pytest with the 95 percent floor, notebook check, uv build, distribution check).
  `repo` was green with the append-only check on.
- **Focused run:** `test_consistency_rebuild.py`: 35 passed (33 from unit 5 plus 2 new).
- **Findings not applied (open for the orchestrator):**
  - MINOR, a sample binding equal to a member binding (for example `model_4` set to
    `model_1`) fails in the walker with "Evaluation URL4 has conflicting Recipe topology
    metadata", not with a C5 text. The url4 still fails closed. The fix needs a decision: accept
    and record it in the PRD, or refuse it in `_decode_fusion` with `_REDUCER_INVALID`. Not done.
  - MINOR, `_decode_sample_source` repeats the model-leaf checks of `_decode_signal_source`. The
    spec §3.1 pins the body. A shared `_decode_model_leaf` helper is optional. Not done.
  - MINOR, `spec_operator_pairs` and `url4._combine_operator_pairs` both de-duplicate pairs
    (D-4). Kept as the spec §3.4 pins it. Not done.
  - MINOR, two dicts built from `recovered.operations` (`url4.py`), and the wrapped subset check
    in `_decode_synthesizer`. Both are style only. The spec §3.1 and §3.5 pin the exact text.
    Not done.
  - MINOR, D-U5-3 (the RED file edit). No action in this unit. The owner must approve it.
- **Flakes:** none seen in this round. No test was rerun.
- **Pinned edits:** none in this round.

## Unit 6: show consistency in the report (`consistency-display`)

### Intent

PRD `consistency-display`, rows CD#1–7 (ans:Q4 "the count of failed samples is recorded"; P15;
part 4 surfaces and number format). The Case pane Combine section of a step that declares
`sf.Consistency` gets one step chip after the mean chip:
`samples · {name} · {n} per member · failed {F} of {T}`. In the column of the consistency name,
each member cell shows the value, then ` {f} failed` (class `sf-cmb__nn`) when the member has
failed samples; a missing value is a dash whose reason is the member reason (fail or excluded),
else `every sample failed`, else `no answer to compare`. The run summary of the step gets one line
after the gate line: `samples · {name} · failed {F} of {T}` over the Cases with evidence. The
export already holds `operations[].combine.consistency`; no export, trace or schema change. A step
without consistency keeps its bytes. The sample operations stay as rows with no member (N8, D9
deferred).

Unit base: `f2fddb97170fe19d4170feadf775d9a869a9495c` (the unit 5 tip).

### Planned changes

- `S/_ui/combine_view.py`: constants `_EVERY_SAMPLE_FAILED`, `_NO_ANSWER_TO_COMPARE`;
  `_SampleFacts`, `_sample_facts`, `_samples_chip` (after `_reads_chip`); one `_chips` item after
  the mean chip; `_member_row` calls `_signal_cell`; `_signal_cell`, `_sample_record`,
  `_consistency_reason` (after `_member_row`); `_StepSummary` fields `sample_name`,
  `samples_failed`, `samples_total` (after `values`), `add` calls `_add_samples`; `_samples_line`
  (after `_gate_line`); `_summary_html` writes `heading + gate line + samples line + table`. Each
  edit keeps one unchanged line between it and a part 6 edit of the same file (contracts C8).
- New test file `ST/test_consistency_display.py` (CD#1–7). It reads
  `COMBINE_CONTRACT / "consistency_evidence_cases.json"` under `requires_engine_app` and builds
  each Case by hand; it never uses `_answer_fixtures.fixture_case`.

### Pinned edits

None.

### Test plan

- 7 PRD rows (8 test functions) in the PRD §7 order. CHAR: CD#1 (the fixed list L37: no sample
  fact), CD#6 (the export), CD#7 (the trace field sets). RED: CD#2–CD#5.
- No stub: the tests import no new name. Each RED row fails on an assertion.
- Every chip, cell and line oracle is hand-written from consistency-display §3 and the fixture V
  and W tables of consistency-value §3.

### Acceptance

- V shows `samples · cons · 4 per member · failed 6 of 12` as the last chip; W shows
  `... 3 per member · failed 0 of 9` and no note; no_votes shows the V chip.
- The cells of V, no_votes and the CD-D4 copy have the exact values, notes and reasons of
  CD-2, CD-D3, CD-D4.
- The run summary of two V Cases has `samples · cons · failed 12 of 24` directly after the
  heading and the cons means 0.5, 1 and a dash; a Case without evidence is not counted.
- The export holds the record between `signal` and `declared`; the trace keeps the v1 fields.
- `screamingface --base <U5>` and `repo --base <U5>` all green; `--base 633fec3a1` red only on
  the unit 1 and 3 pinned files.

### Deviations

- D-1 (kind, CD#6): CHAR, not RED. Units 1–2 already export the record (PRD row 6: "if green at
  RED, the ledger records it as a CHAR row").
- D-2 (code, CD-1): the chip reads `n` and `T` from the record sums (`succeeded + failed` of the
  first record; the sum over the records), not from `declared[name]["n"]`. CS-I3 makes them equal
  (the SDK `CombineEvidence` checks it), and a record holds typed ints while a declared entry
  value is an `object`.
- D-3 (test design, CD#2): the row also checks the no_votes chip (`failed 6 of 12`): a step with
  no voter still shows its samples. One more assert, not a new row.
- D-4 (test design, CD-D4): the "hand-built CombineEvidence" is the `consistency_vote` wire with
  member_1 `signals.cons` and `consistency.cons[0].matched` set to None, decoded by the SDK
  decoder (so CS-I5 is checked).
- D-5 (test design, CD#1): no sha256 digests; the bytes of the existing sections are pinned by the
  L32 digests of `ST/test_gate_display.py` (green with no edit), and part 6 changes some of these
  bytes later, so a second digest list would only add rebase work.
- D-6 (process, RED): the test file was written before this ledger section. The section was
  appended before commit A. No test text or oracle changed by this order.

### Outcome (fill at the end — required before COMMIT)

- **Status:** in_progress (RED: commit A pending)
- **Actual files:**
- **Commits:**
- **Gates:**
- **RED log:**
- **Deviations:**
