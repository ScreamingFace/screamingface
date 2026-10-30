# Contracts: E4b part 6, signal sums and the abstain band

One section per connection. Path prefixes as in [erd](erd.md).

## C1 Sum source — SDK → Engine, combine spec `signals` entry (url4 intent, JSON)

- **Shape.** One entry of the optional `signals` map of `screamingface.combine-spec.v1`
  (additive union member, no new schema id):

  ```json
  "<name>": {"coefficients": {"<component>": <finite non-zero number>, ...}, "source": "sum"}
  ```

  1 to 7 components; canonical JSON sorts the keys. [stated ans:Q1]; [proposed] P1–P4
- **Policies.** Each component is a key of the same `signals` map and is not a sum entry (SU-I1,
  SU-I2). The union is closed (`extra="forbid"`, strict). Without a sum entry, the bytes do not
  change. [proposed]
- **Failure behavior.** Any rule break is `combine_spec_invalid`. The message names the rule and
  never echoes a name or a number (signal-sum §2.1 table, the quiet union message). [existing
  E/combine/spec.py:199-206 precedent]
- **Contract tests.** SM#2, SM#3, SM#13, SA#8, SA#12.

## C2 Sum value — Engine core → combine evidence (`members[].signals`, `declared`)

- **Shape.** `members[i].signals["<name>"]`: a float or null, beside the component values;
  `declared["<name>"] == {"source": "sum", "coefficients": {...}}`. The evidence schema does not
  change for this (`declared` is free JSON per entry). [existing E/combine/evidence.py:205]
- **Policies.** The value is the exact rational sum of the products, rounded once; null when a
  component is null or when the exact sum is outside the float range (SU-I3, SU-I4). The read key
  rule does not change: an operator sees only the key the step reads (E/combine/endpoint.py:782-797).
  [proposed] P5, P6
- **Failure behavior.** No new failure. A rule that reads a null sum excludes the member
  (`no_signal` or `no_weight`, part 2). [existing]
- **Contract tests.** SM#4–SM#12.

## C3 Sum rebuild — url4 → SDK Python (`Url4.to_python`)

- **Shape.** `declared_from_spec` maps `"sum"` to `sf.Sum` (`_SOURCES`); `python_signals` writes
  `sf.Sum({'a': 0.5, ...})` through `_python()`. [existing S/signal_sources.py:186-216]
- **Policies.** `Sum._from_spec` accepts exactly `{"source", "coefficients"}` and calls the
  constructor. The Fusion rules (C1 policies) run again on the rebuilt recipe. [proposed] P15
- **Failure behavior.** A hand edit gives the existing `"URL4 Candidate has a signals declaration
  this SDK version cannot rebuild"`. [existing]
- **Contract tests.** SA#10, SA#11.

## C4 Band — SDK → Engine, combine spec `gate.abstain_band`

- **Shape.** Optional key of the part 5 `gate` object: `"abstain_band": [<lo>, <hi>]`.
  [stated ans:Q2]
- **Policies.** Two finite numbers, `lo <= hi`; for `observe == "agreement"`,
  `0 <= lo <= hi <= 1`. An explicit null is refused. No rule ties the band to the threshold.
  Without the key, the bytes do not change. [proposed] P7, P8
- **Failure behavior.** `combine_spec_invalid` with a fixed message (abstain-band §2.1). [existing]
- **Contract tests.** AB#2, AB#3, AB#15, BA#4, BA#7.

## C5 Band record — Engine → SDK, combine evidence `gate` (`screamingface.combine-evidence.v1`)

- **Shape.**

  ```json
  "gate": {"observe": "agreement", "observed": 0.6666666666666666, "cmp": ">=", "threshold": 0.7,
           "passed": null, "branch": "band", "otherwise": "abstain", "abstain_band": [0.6, 0.7]}
  ```

  `abstain_band` is written only when the spec has a band, after `otherwise`. `branch` gains the
  word `band`. [stated ans:Q2]; [proposed] P10, P11
- **Policies.** GR-I1', GR-I4', GB-I1 to GB-I5 hold on both sides (erd §4). The band branch makes
  no comparison (`passed` null) and keeps the vote's tally, agreement and tie (the part 5
  `gate_not_met` precedent, P14 of part 5). The SDK decoder accepts the part 5 key set, or that set
  plus `abstain_band`. [proposed]
- **Failure behavior.** The Engine model raises on an invariant break (a plugin bug, never a
  declared code). The SDK decoder refuses an unknown key, a bad band or a broken invariant with
  `ExecutionError` (strict). [existing]
- **Contract tests.** AB#4–AB#10, AB#12, AB#13, AB#16, AB#17.

## C6 Band rebuild — url4 → SDK Python

- **Shape.** `_rebuilt_gate` reads the optional `abstain_band` and passes it to `sf.Gate`.
  [existing S/reducer.py:513-537]; [proposed]
- **Policies.** `repr`/`_python` write `abstain_band=(lo, hi)` after `otherwise=`, only when set.
  [proposed] P15
- **Failure behavior.** A hand edit gives `"URL4 Candidate has a vote spec this SDK version cannot
  rebuild"`. [existing]
- **Contract tests.** BA#5, BA#6.

## C7 Abstain reason `in_band` — Engine → SDK

- **Shape.** `result: {"member_id": null, "value": null, "status": "abstain", "reason": "in_band"}`.
- **Policies.** `in_band` joins `AbstainReason` and `AnswerReason` on both sides (P12), after
  `gate_not_met`. It is a scored decline: the Case is `candidate_abstained`, not failed. No failure
  code changes (`DECLARED_FAILURE_CODES` and `ENGINE_ERROR_CODES` stay the same). It is not E4c's
  `fail_closed`, which will be a failure code. [existing E/benchmarks/operation_outputs.py:94-111]
- **Failure behavior.** An SDK without the word refuses the evidence (strict words). The SDK and the
  Engine ship together. [implied]
- **Contract tests.** AB#11, AB#14, AB#15.

## C8 E4c reading contract (no wire change)

- **Shape.** E4c reads the spec `gate` (with the optional band), the topology key of the fallback
  call (part 5 C2), and writes the same evidence record.
- **Policies.** FB-I1 holds for the band branch: the band branch never reads a `fallback_*` reply
  (AB-D2). So E4c can skip the fallback call on the majority branch, on the band branch and on the
  "not run" branch, and produce the same evidence bytes. The band check comes before the comparison,
  so E4c evaluates the band first too. [proposed] P9
- **Failure behavior.** A context with no fallback signal on the band branch is valid.
- **Contract tests.** AB#7.

## C9 Dependency rule

`E/combine/signal_sum.py` imports only the standard library (`fractions`, `collections.abc`).
`E/combine/gate.py` keeps its part 5 imports (standard library, `combine.ports`, `combine.spec`).
Neither imports `combine.operators` or `combine.builtins` (`COMBINE_CORE_FORBIDDEN`,
`check_layering.py`). Neither does I/O. The layering gate (`run_gates.py screamingface-engine`)
enforces it. [existing part 5 C9]

## C10 Merge contract with part 7 (`consistency@N`, built in parallel)

- **Shared files.** `E/combine/spec.py` (the `DeclaredSource` union), `E/combine/endpoint.py`
  (`_declared`, `_Plan.declared`), the two v1 schema snapshots, `ST/public_surface_snapshot.json`,
  `S/signal_sources.py` (`_SOURCES`, `__all__`), `S/__init__.py`, `ET/data/combine_contract/evidence_cases.json`,
  `ST/test_frozen_record_fields.py:184`, `packages/screamingface/README.md`, `CHANGELOG.md`.
- **Policies.** This part only appends: one union member, one branch in `_declared` before the
  registry lookup, one class and one `_SOURCES` entry, one README section, one CHANGELOG bullet. A
  generated file (a schema snapshot, the public surface snapshot, `evidence_cases.json`) is
  regenerated after the rebase, never merged by hand. A sum may take a `consistency` name as a
  component with no change (any declared non-sum name). [stated brief]; [proposed]
- **Failure behavior.** The rebase that comes second regenerates the snapshots, adds both case
  counts, and orders the two CHANGELOG bullets (part 6 at position 3, part 7 after it, or the
  reverse, as the owner merges).
