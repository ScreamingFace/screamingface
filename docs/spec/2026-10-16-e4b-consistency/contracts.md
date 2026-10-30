# Contracts: E4b part 7, consistency@N

One section per connection. Path prefixes as in [erd](erd.md).

## C1 Consistency entry — SDK → Engine, combine spec `signals[name]` (url4 intent, JSON)

- **Shape.** An entry of the optional `signals` map of `screamingface.combine-spec.v1` (additive,
  no new id):

  ```json
  "cons": {"match": {"extract": {"args": {}, "op": "<extract@v>"},
                     "normalize": {"args": {}, "op": "<normalize@v>"} | null},
           "n": 1..32, "source": "consistency", "temperature": <finite number >= 0>}
  ```

  [stated ans:Q3]; [proposed] P2, P3
- **Policies.** The model is closed (`extra="forbid"`, E/combine/spec.py:107-110); `n`,
  `temperature` and `match` have no default; at most one consistency entry per spec. `match` is
  the step's own pinned extract and normalize when the step has an extract, else `last_line@1` and
  `text@1`; the SDK pins both ids against the Engine catalog at compile
  (`_OperatorCatalog.pin`). Without a consistency entry, the bytes do not change.
- **Failure behavior.** A bad entry is `combine_spec_invalid`; an unknown match id is
  `combine_operator_unknown`; the message never echoes a name, a pattern or a number.
  [existing E/combine/spec.py:199-206 precedent]
- **Contract tests.** CR#3, CR#4, CV#7, CA#5, CA#6.

## C2 Sample calls — SDK → url4 → Engine → gateway

- **Shape.** For member k and sample j: a url4 source `model_N:0.0:/<member route>(<member
  context>)!'<member prompt>'` with the params `binding=model_N`, the member's author params
  without `seed` and `temperature`, `temperature=<t>`, `seed=<s(k, j)>`; inside a slot
  `sample_j` (`weight=1.0`, optional) of a broadcast panel `panel_M` with `quorum=0` (erd §2,
  §3). One operation per call: `op_model_N`, kind `sample`, label `"{member name} sample"`.
  [stated ans:Q3]; [proposed] P4–P7
- **Policies.** The binding param is first and is stripped by the Engine before the gateway
  (E/world/request_parameters.py:26-28, :172-182). The params without `binding` go into
  `parameter_assignments`, so the SDK preflight checks `seed` and `temperature` per model before
  any spend (part 3 P12). The calls are never claimants (I-C2). The seeds are fixed by the recipe:
  a replay is served the same cached replies (distinct seeds give distinct cache keys).
- **Failure behavior.** A failed sample call drops its slot from the panel; the panel never fails
  (`quorum=0`); the Case does not fail. [stated ans:Q4]; [existing url4 broadcast]. A model that
  the catalog marks without `seed` or `temperature` fails the preflight with
  `unsupported_model_parameter`, before any call. [existing]
- **Contract tests.** CA#4, CA#7, CA#8, CA#10, CA#11.

## C3 Context `samples` — combine context (url4 struct) → Engine core

- **Shape.** `samples: {"member_1": "<rows>", ...}`: every spec member; each value the url4
  broadcast rows text `[{"source_position": j, "source_name": "sample_j", "result": "<text>"},
  ...]` of the samples that answered. Written after `outputs`/`panel`, before `signals`.
  [proposed] P9
- **Policies.** Present exactly when the spec declares consistency (CX-I1). Each row as in erd §4
  CX-I2; `parse_context` parses the rows with `_panel_rows`, the same helper as the quorum panel. The whole context keeps the 64 MiB cap (E/combine/endpoint.py:116, :649-654).
- **Failure behavior.** A missing, extra or bad `samples` value is `combine_spec_invalid` with a
  fixed message ("combine context samples ..."), never a text. Over the cap:
  `combine_input_too_large`. [existing codes]
- **Contract tests.** CR#5, CR#6, CV#6.

## C4 Consistency record — Engine → SDK, combine evidence (`screamingface.combine-evidence.v1`)

- **Shape.**

  ```json
  "consistency": {"cons": [
    {"member_id": "member_1", "matched": 2, "succeeded": 4, "failed": 0},
    {"member_id": "member_2", "matched": 2, "succeeded": 2, "failed": 2},
    {"member_id": "member_3", "matched": null, "succeeded": 0, "failed": 4}]}
  ```

  plus the values in `members[i].signals["cons"]` (0.5, 1.0, null) and the entry in
  `declared["cons"]`. [stated ans:Q4]; [proposed] P13
- **Policies.** Optional; written only when the spec declares consistency; place after `cut`,
  before `declared` (overview P13). CS-I1..CS-I5 hold on both sides. The SDK decoder adds `consistency` to
  `_OPTIONAL_EVIDENCE_KEYS` with exact record keys.
- **Failure behavior.** The Engine model raises on a broken invariant (a plugin bug, never a
  declared code). The SDK decoder refuses an unknown key, a missing key or a broken invariant with
  `ExecutionError`. [existing strict decoder]
- **Contract tests.** CR#7–CR#13, CV#13, CV#14, CD#6.

## C5 Rebuild and replay — url4 → SDK Python, url4 → Candidate

- **Shape.** The topology reducer node may hold `samples` (erd §7). `Url4.to_python()` writes
  `signals={'cons': sf.Consistency(n=3, temperature=1.0)}` and leaves out every sample call.
  The replay recovers the sample operations (kind `sample`).
- **Policies.** Every consistency url4 is recompiled and compared byte for byte (the optional sample
  slots trigger `_require_recompiles`). The recompile catalog holds the match operators
  (`spec_operator_pairs`). A sample call needs its binding param first. The replay leaves the sample
  calls out of the fixed-seed warning.
- **Failure behavior.** A hand edit gives one of the existing errors: "URL4 Candidate Recipe
  topology does not match its model calls", "URL4 Candidate does not match its Recipe metadata",
  "URL4 Candidate has invalid Reducer topology metadata", "URL4 Candidate has a signals declaration
  this SDK version cannot rebuild". [existing S/url4.py, S/_evaluation/topology.py,
  S/signal_sources.py]
- **Contract tests.** CB#2–CB#9.

## C6 Attribution and accounting — Engine operation outputs → SDK accounting

- **Shape.** Each sample call is attributed to `op_model_N` inside its `panel_M` (one claimant,
  optional) with its output and its accounting (E/benchmarks/operation_outputs.py:165-209). The
  SDK accounts the kind `sample` as a `generation` row. [existing]; [proposed] P7
- **Policies.** The member reader (E/world/combine.py:82-120) indexes every recorded call by
  `(path, params)`. A sample call carries `binding=model_N`, so it never shares a fingerprint with
  a member call, and a member's accounting and logprob numbers stay known (SC-I1). [proposed] P6
- **Failure behavior.** A failed sample has no output (`output: null`) and no accounting row
  amount, as any failed optional call. [existing]
- **Contract tests.** CA#7, CA#11, CA#12.

## C7 Dependency rule

The new combine core module `E/combine/consistency.py` (`SampleCount`, `count_samples`) imports
only the standard library (never `combine.operators` or `combine.builtins`, the
`COMBINE_CORE_FORBIDDEN` rule of `.claude/scripts/check_layering.py:109`). It does no I/O. The
endpoint passes the resolved match steps in as a `read` function. The layering gate
(`run_gates.py screamingface-engine`) enforces it; no separate import test is written. [existing];
[proposed] P21

## C8 Shared surfaces with part 6 (built in parallel)

Part 6 (signal sums and the abstain band) changes some of the same files. This part keeps its
changes additive so that the later rebase is mechanical:

| Shared place | This part adds | Rebase rule |
|---|---|---|
| `E/combine/spec.py` `DeclaredSource` union, `_check_signals`, `parse_context`, `_panel_outputs` | `ConsistencySource`, one rule, `samples_n=`, the `_panel_rows` helper | keep both additions |
| `E/combine/endpoint.py` `_declared`, `_signal_values`, `_column`, `_combine`, `_evidence` | one branch each; `counts` on `_signal_values` and `_column`; `recorded` becomes a `_Recorded` mapping that also carries the counts (no new keyword on the exits) | keep both branches |
| `E/combine/evidence.py` field order | `consistency` between `cut` and `declared` | keep both keys; regenerate the evidence schema snapshot once after the rebase |
| schema snapshots, `ST/public_surface_snapshot.json` | new defs and names | regenerate after the rebase (owner approves the merged file) |
| README, CHANGELOG | a section before `## Install`; a bullet after the part 5 bullet | keep both; the docs tests check order, not a fixed index |
