# PRD: Declared signals (`sf.Fusion(signals={...})`)

**Source:** ans:Q1, ans:Q7 · **Priority:** P0 (all sources use it)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned
Paths: [erd §1, §4, §5](../erd.md) · used by: [verbalized](verbalized.md), [logprob](logprob.md),
[entropy](entropy.md)

## 1. Flows served

This is a component PRD. The three source PRDs use it. It owns the name rules, the compile check,
the wire key `signals`, the evidence key `declared` and the rule "record every declared name".

## 2. Background and constraints

- "Declare, additive": a Fusion declares new sources by name, rules read `sf.signal("<name>")`,
  the E4a keys stay valid with no declaration, and a rule that reads an undeclared name fails
  before any member call. [stated ans:Q1]
- "Record every declared": each declared name gets a value per member in the evidence, read by a
  rule or not. [stated ans:Q7]
- One combine step reads at most one signal (E4a GE5). Part 3 keeps this rule; several signals in
  one step are part 6. [existing E/combine/endpoint.py:394-396]
- The cost key stays `cost_usd`. [stated ans:Q4]

### 2.1 Current behavior

- `sf.Fusion(members, *, name, synthesizer, quorum, optional)` has no `signals`.
  [existing S/fusion.py:34-42]
- `sf.signal(key)` accepts only the E4a keys and refuses all others at construction. A key that
  starts with `logprob` gets "comes with E4b (declared signals)". [existing S/_signals.py:18-58,176-193]
- The engine accepts the same closed set (`is_signal_key`) in `weights`, in the reduce args and in
  the signal read. [existing E/combine/ports.py:438-452]; [existing E/combine/spec.py:101-115];
  [existing E/combine/endpoint.py:381-397]
- The engine computes only the one read key per member. With no read, `signals` is `{}`.
  [existing E/combine/endpoint.py:219-233]

**Delta.** Add `signals=` to `sf.Fusion`. `sf.signal` also accepts a name with the declared-name
syntax. The Fusion checks every name its rules read. The SDK compiles the declaration into the
spec key `signals`. The engine parses it, computes every declared name for every member, and
writes the values and the `declared` map into the evidence.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **DS-1** Given `sf.Fusion(members=[a, b], signals={"conf": sf.Verbalized(r"Confidence: ([0-9]+)")},
  synthesizer=sf.Vote(weights=sf.signal("conf")))`, then the compiled spec has
  `"signals": {"conf": {"source": "verbalized", "pattern": "Confidence: ([0-9]+)"}}` and
  `"weights": {"signal": "conf"}`. [stated ans:Q1]
- **DS-2** Given a Fusion that declares nothing, then the compiled url4 is byte-identical to today.
  [implied]
- **DS-3** Given a Fusion that declares `conf` and whose rule reads `cost_usd`, then the evidence
  `members[].signals` holds both `conf` and `cost_usd` for each member, and `signal.key` is
  `cost_usd`. [stated ans:Q7]
- **DS-4** Given a declaration, then the evidence has `declared` equal to the spec `signals`.
  [stated ans:Q7]; [proposed] shape

### 3.2 Error paths

- **DS-E1** Given a rule that reads `sf.signal("lp")` and a Fusion that does not declare `lp`, then
  the Fusion constructor raises `ValueError` that names `lp` and the declared names. No member is
  called. [stated ans:Q1]
- **DS-E2** Given a spec whose `weights`, reduce args or signal read names an undeclared name,
  then the engine refuses it with `combine_spec_invalid`, and the message does not echo the name.
  [implied]; [existing ET/test_combine_spec.py:335-347] (no echo)
- **DS-E3** Given a name that breaks the name rules (`"Cost"`, `""`, `"a" * 33`, `"logprob_x"`,
  `"cost_usd"` as a declared name), then the Fusion constructor raises `ValueError`.
  [proposed]

### 3.3 Derived scenarios (risk-ordered)

- **DS-D1** (H×H) [existing ST/test_signals.py:25-28] Given `sf.signal("logprob_mean")`, then it
  still raises `ValueError` that matches `E4b` and names `cost_usd` (reserved prefix). The four
  engine pins that use `logprob_mean` as the unknown key still pass.
- **DS-D2** (H×M) [proposed] Given `sf.signal("cost")`, then it does NOT raise at construction
  (it is a valid name). The Fusion that does not declare `cost` raises `ValueError` that says
  "did you mean cost_usd". This changes the pinned case `ST/test_signals.py:33-35` (owner approval).
- **DS-D3** (H×M) [stated ans:Q7] Given a declared name that no rule reads, then the evidence still
  holds its value for every member, and no `signal` record names it.
- **DS-D4** (H×M) [proposed] Given 9 declared names, or two `sf.Entropy` sources, then the Fusion
  constructor raises `ValueError` (DS-I1, DS-I2).
- **DS-D5** (M×M) [proposed] Given `signals=` on a Fusion with a model synthesizer, then the
  constructor raises `ValueError` (DS-I3).
- **DS-D6** (M×M) [existing E/combine/endpoint.py:226-229] Given an empty quorum panel, then every
  declared value is None and the Case abstains with `no_votes`, as today.
- **DS-D7** (M×M) [implied] Given a member that a quorum panel left out (status `fail`, reason
  `missing`), then each of its declared values is None.
- **DS-D8** (M×L) [implied] Given `repr(fusion)` and its Python form, then the `signals` map
  round-trips, and a rebuilt Fusion compiles to the same bytes.
- **DS-D9** (M×L) [proposed] Given the same source declared under two names, then both names get
  the same value. This is allowed.

## 4. Non-functional requirements

- The name check runs at construction. It walks the reducer's signal references once.
  O(rules + names). [proposed]
- Declared values for `verbalized` cost no model call. `logprob` and `entropy` cost no extra call:
  they change only the params of the member calls. [implied]
- The evidence grows by one float per declared name per member: at most 8 × 256 values. [proposed]

## 5. Out of scope

- Several signals in one combine step, and sums with coefficients (part 6). [stated prompt]
- Showing the values in the report (part 4). [stated prompt]
- A scorer model as a declared source: `sf.Judge(returns="scores")` is the scorer (DB-6).
  [stated prompt]
- Declared signals on a Fusion with a model synthesizer (DS-I3). [proposed]

## 6. Open questions

None.

## 7. TDD plan

Order: characterize the E4a keys and the refusals, then build core-out (SDK name rules, compile,
engine parse, engine record).

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | CHAR `fusion_without_signals_compiles_the_same_bytes` | unit | DS-2 | H×M | passes today |
| 2 | CHAR `signal_logprob_mean_is_refused_with_the_e4b_message` | unit | DS-D1 | H×H | passes today; must stay green |
| 3 | CHAR `engine_refuses_undeclared_logprob_mean_everywhere` (weights, by_signal, filter) | unit | DS-D1 | H×H | passes today |
| 4 | `fusion_refuses_a_rule_that_reads_an_undeclared_name` | unit | DS-E1 | H×H | walk `reducer_signals` references |
| 5 | `fusion_refuses_invalid_and_reserved_names` | unit | DS-E3 | H×M | name regex, reserved prefixes, E4a keys |
| 6 | `signal_accepts_a_declared_name_syntax` (approved edit of `ST/test_signals.py:33-35`) | unit | DS-D2 | H×M | `is_signal_name` beside `is_signal_key` |
| 7 | `fusion_refuses_more_than_eight_names_and_two_entropies` | unit | DS-D4 | M×M | DS-I1, DS-I2 |
| 8 | `fusion_refuses_signals_with_a_model_synthesizer` | unit | DS-D5 | M×M | DS-I3 |
| 9 | `fusion_compiles_the_signals_map_into_the_spec` | unit | DS-1 | H×M | `combine_spec_text` |
| 10 | `engine_parses_signals_and_refuses_an_undeclared_read` | unit | DS-E2 | H×M | `CombineSpec.signals`, key check at plan level |
| 11 | `engine_records_every_declared_name_for_every_member` (one case declares one source twice) | unit | DS-3, DS-D3, DS-D9 | H×M | `_signal_values` over read key + declared names |
| 12 | `evidence_declared_equals_the_spec_signals` | unit | DS-4 | M×M | optional key, `exclude_if` like `mean` |
| 13 | `empty_panel_and_missing_member_get_none_for_declared_names` | unit | DS-D6, DS-D7 | M×M | — |
| 14 | `fusion_signals_round_trip_through_repr_and_rebuild` | unit | DS-D8 | M×L | `__repr__`, `_python`, rebuild |
| 15 | `sdk_decoder_reads_declared_and_rejects_unknown_keys` | unit | DS-4 | M×M | `_OPTIONAL_EVIDENCE_KEYS` |
