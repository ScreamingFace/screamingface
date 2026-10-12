# E4a unit 13: reducer synthesizers with Fusion quorum and optional members

Status: approved direction (owner, 2026-10-12: "make them compatible transparently"), built as unit 13.
Refs: OME-1289 (E4a) × OME-1557 (Fusion quorum, main PR #1340).

## 1. Problem

Main added Fusion `quorum` and per-member `optional=True` (#1340). The E4a stack lets a Fusion end in a
reducer (`sf.Vote`, `sf.Reduce`, `sf.Judge`, `sf.Pick`, `sf.Merge`, `sf.Rank`, `sf.Concat`, `sf.Filter`),
which compiles to one deterministic combine call (`/ensemble/combine/v1`).

The two features do not meet:

- With quorum or an optional member, main compiles the members into a `panel_N` group and hands the
  synthesizer `{input, outputs: "$panel_N"}`. The panel is TEXT: `member_1: <answer>` lines.
- The combine route needs `outputs` as a JSON object with an entry for every spec member. A missing
  entry or a string is a permanent `combine_spec_invalid`.

The rebase onto main (2026-10-12) added a stop-gap: `sf.Fusion` refuses a reducer synthesizer with
quorum or optional members. This plan removes that refusal.

## 2. Verified facts

Each fact was run, not only read (url4 in this repo, `StaticIOLayer`, 2026-10-12).

| # | Fact | Consequence |
|---|---|---|
| F1 | The text panel `(…)!''` gives `member_1: A\nmember_2: B…`. A member answer that holds `member_3: x` looks the same as a real member 3 line. | The combine route cannot parse the text panel safely. |
| F2 | The broadcast panel `(…)!*''` with the same slots gives a JSON array `[{"source_position": 1, "source_name": "member_1", "result": "A"}, …]`. | Names and texts are exact, with no ambiguity. |
| F3 | A failed optional slot is absent from the broadcast rows. No marker, no null. | Absent row = the member did not answer. |
| F4 | `;quorum=N` gates the broadcast panel the same way. A miss raises `quorum_not_met` (transient) before the combine call runs. A failed required slot fails the whole expression. | Quorum and required-member rules stay in url4, as on main. |
| F5 | An empty answer is a row with `"result": ""`. `quorum=0` with every member failed gives `[]`. | Empty stays the existing `empty` reason. No rows means the combine abstains (`no_votes`). |
| F6 | The engine runs url4 with `default_process`. An empty intent returns each source unchanged. | The broadcast panel adds no model call. |
| F7 | A failed optional `$model_3` used directly in a struct stays the literal text `$model_3`. | Direct references are not an option. |
| F8 | The engine attributes outputs and accounting by each call's own fingerprint and expands `panel_N` sources (`operation_outputs._panel_sources`). | Member outputs, costs and combine evidence keep their attribution. |
| F9 | url4 2.0 code pointers (`(…)!/route;quorum=N`) also omit failed sources, but the engine has no code mount, and a code pointer cannot share the combine endpoint path. | Rejected for now: a second combine form and new engine wiring. |

## 3. Options

| Option | Result |
|---|---|
| A. The combine route parses main's text panel | Rejected: ambiguous (F1). |
| B. The combine context keeps `$model_N` references | Rejected: a failed optional reference reaches the route as literal text (F7). |
| C. Combine as a url4 2.0 code-pointer group | Rejected for now (F9). It can replace D later without a change in semantics. |
| **D. A broadcast panel for reducer Fusions** | **Chosen.** url4 enforces quorum and required members (F4). The combine route reads exact named rows (F2, F3). |

## 4. Design

### 4.1 Compile (SDK)

1. `_compile_fusion` keeps its fast path. A Fusion with `quorum="all"` and no optional member compiles
   as today, so every existing url4 stays byte-identical.
2. For a quorum or optional Fusion with a **reducer** synthesizer, the panel source is the same
   `panel_N` with the same slots and `;quorum`, but its intent operator is broadcast: `(…)!*''`.
   A Model or Recipe synthesizer keeps main's text panel `(…)!''`, with no change.
3. The combine context is `{input, panel: "$panel_N", signals?, sources?}`. The `panel` key replaces
   `outputs`. It is a different key, so the engine can never confuse the two forms.
4. Signal model calls (judge, writer projection) read the same context `{input, panel}`. One panel
   feeds every call, so the member expressions run once.
5. The judge prompt for a panel says that `panel` lists the members that answered, as rows with
   `source_name` and `result`. The template line becomes `judge-template@1 returns=<r> input=panel`,
   so a panel judge has its own replay identity. A judge with no panel keeps its bytes.
6. The block-form lowering (`fusion_recipe.py`) carries `quorum` and `optional` to the lowered
   Fusion. Today it drops them.
7. The `sf.Fusion` refusal from the 2026-10-12 rebase is removed. The 256-member cap stays.

### 4.2 Combine route (engine)

1. `parse_context` accepts exactly one of `outputs` (today's form, every member required) and
   `panel`.
2. A `panel` is parsed strictly:
   - It must be a JSON text of an array of objects with exactly the keys `source_position`,
     `source_name` and `result`.
   - `source_name` must be a spec member and must be unique.
   - `source_position` must equal that member's 1-based index in the spec.
   - `result` must be a string.
   - Any other shape is the permanent `combine_spec_invalid`.
3. `CombineContext.outputs` holds only the members that answered. `_read_members` gives every spec
   member that has no output an `Answer` with status `fail` and the new reason `missing`.
4. Every reducer and selector already skips `fail` members. `dropped` counts `missing` members.
   No voters means abstain (`no_votes`), as today.
5. The judge parsers (`parse_label`, `parse_scores`, the `score:judge` signal read) check the reply
   against the members that answered, not against every spec member.
6. Accounting signals do not change. A member that did not run has no recorded call, so its numbers
   are unknown (`None`), as today.

### 4.3 Evidence, report and replay

1. `AnswerReason` gains `missing` in the engine and in the SDK mirror. The evidence schema stays
   `screamingface.combine-evidence.v1`: E4a is not released, so the frozen v1 snapshot is regenerated.
2. `case.answers()` and the trace show a `missing` member with `text=None`.
3. url4 recovery needs no new rule. A quorum or optional Fusion recompiles from its `_sf_recipe`
   and must match byte for byte (`_validate_topology`). The reducer-call checks accept the `panel` key.

### 4.4 Behaviour table

| Situation | Model synthesizer (main) | Reducer synthesizer (this unit) |
|---|---|---|
| Every member answers | synthesizes all | combines all |
| An optional member fails, quorum met | synthesizes the others | combines the others; the failed member is `fail`/`missing` in evidence |
| Quorum not met | `quorum_not_met`, the synthesizer does not run | the same |
| A required member fails | the Fusion fails | the same |
| `quorum=0`, every member fails | the synthesizer gets an empty panel | the combine abstains (`no_votes`); the Case scores 0.0 and is marked abstained |

## 5. Where it lands

- Code: a new branch `e4a-quorum-reducers` (unit 13) on top of `e4a-combine-hardening`, as one
  reviewable unit. No cascade rebase of units 1–12.
- Docs: this plan, and erratum GE34 in the gap-closure overview §9 on this docs branch.

## 6. Test plan

| ID | Layer | Test |
|---|---|---|
| QR-1 | SDK | A reducer Fusion with quorum compiles a broadcast `panel_N` and the context `{input, panel}`; a Model Fusion with quorum keeps main's bytes. |
| QR-2 | SDK | A reducer Fusion with no quorum and no optional member keeps today's url4 bytes (the doc goldens still pass). |
| QR-3 | SDK | The block form with quorum lowers to `Fusion(m, Model, quorum=…)` and gives the same url4 as the named form. |
| QR-4 | SDK | A quorum reducer url4 round-trips through `Url4.to_python()` and replay validation. |
| QR-5 | Engine | `parse_context`: `panel` rows parse. Wrong keys, unknown or duplicate names, wrong positions, a non-string result, or both `outputs` and `panel` are `combine_spec_invalid`. |
| QR-6 | Engine | A missing member is `fail`/`missing`, does not vote, and counts in `dropped`. An empty panel abstains with `no_votes`. |
| QR-7 | Engine | Judge label and scores accept a reply over the members that answered and refuse one that names a missing member. |
| QR-8 | Engine world | End to end through url4: three members, one optional member fails, quorum 2. The vote uses two members, and the evidence lists three. |
| QR-9 | Engine world | Quorum not met: `quorum_not_met`, no combine call. |
| QR-10 | SDK | Evidence decode accepts `missing`; `case.answers()` shows it with `text=None`. |
| QR-11 | Both | The frozen schema snapshots are regenerated and pinned in the engine and the SDK. |

## 7. Risks

- `quorum_not_met` is transient in url4. This is main's behaviour for a Model synthesizer too, so it
  does not change here.
- The panel judge prompt is new text. Only quorum or optional judge Fusions use it.
- The engine and the SDK must ship together. The `panel` key is unknown to an older engine, which
  refuses it permanently (`combine_spec_invalid`) and never misreads it.

## 8. Out of scope

- Combine as a url4 2.0 code pointer (option C).
- A reducer that reads only the first `quorum` members to answer (an early race). Main's quorum is a
  floor checked after every member finishes, and this unit keeps that rule.
