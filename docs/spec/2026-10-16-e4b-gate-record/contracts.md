# Contracts: E4b part 5, gate record and verifier slot

One section per connection. Path prefixes as in [erd](erd.md).

## C1 Gate — SDK → Engine, combine spec `gate` (url4 intent, JSON)

- **Shape.** Optional top-level key of `screamingface.combine-spec.v1` (additive, no new id):

  ```json
  "gate": {
    "cmp": ">=" | ">" | "<=" | "<",
    "observe": "agreement" | "chosen:<name>" | "mean:<name>",
    "otherwise": "abstain" | "judge" | "writer",
    "threshold": <finite number>
  }
  ```

  [stated ans:Q1, ans:Q2, ans:Q3]; [proposed] P3, P4
- **Polarity.** `cmp` is the condition that KEEPS the majority: `observed cmp threshold` true →
  `branch: "majority"`. An escalate-when condition of E4c (`agreement < 0.8`) is stored as its
  keep form (`{"observe": "agreement", "cmp": ">=", "threshold": 0.8}`). [proposed] P4, owner
  decision at review (plan §6)
- **Policies.** The spec is closed (`extra="forbid"`, E/combine/spec.py:106). The key is valid only
  with `"reducer": "vote"`. `<name>` must be a key of the spec `signals`. For `agreement`: `cmp` is
  `>=` or `>`, and `0 <= threshold <= 1`. An explicit `"gate": null` is refused, as for `signals`
  (E/combine/spec.py:203-205). Without the key, the bytes do not change. [proposed]
- **Failure behavior.** Any rule break is `combine_spec_invalid`. The message names the rule and
  never echoes `observe`, a name or a number. [existing E/combine/spec.py:181-188 precedent]
- **Contract tests.** GR#3, GR#4, GR#5, GA#1, GA#4.

## C2 Fallback call — SDK → url4 → Engine → gateway, and its reply into the combine context

- **Shape.** One url4 source per gated Vote with a judge or writer fallback:
  `judge_N:0.0:/<route>(<fusion context>)!'<judge label template + rubric>'` with params
  `binding=judge_N` then the judge params; or `writer_N:0.0:/<route>(<fusion context>)!'<prompt>'`
  with `binding=writer_N` then the Model params. The combine context gets
  `signals: {fallback_judge: '$judge_N'}` or `signals: {fallback_writer: '$writer_N'}` (after any
  `judge` key, in the reducer's declared order). [existing S/_evaluation/reducer_signals.py:98-167];
  [proposed] P5
- **Policies.** The call is a `_ModelSignal` in `plan.signal_calls`. Its params go into
  `parameter_assignments`, so the SDK preflight checks them before any spend
  (S/_evaluation/reducer_signals.py:250). Its `binding` param keeps its fingerprint apart from a
  member on the same route (S/_evaluation/reducer_signals.py:226-227). It is never a member claimant
  (S/_evaluation/candidate.py `calls=_member_calls(members)`). [existing]
- **Failure behavior.** A failed fallback call fails the Case (it is a required dependency of the
  combine call), on both branches. [existing url4 behavior]; [implied] — E4c removes this cost and
  this risk on the majority branch.
- **Contract tests.** GA#2, GA#3, GA#9, GA#10, GA#17.

## C3 Gate record — Engine → SDK, combine evidence `gate` (`screamingface.combine-evidence.v1`)

- **Shape.**

  ```json
  "gate": {"observe": "agreement", "observed": 0.6666666666666666, "cmp": ">=",
           "threshold": 0.7, "passed": false, "branch": "fallback", "otherwise": "judge"}
  ```

  Key order as shown (the Engine model field order; the encoder keeps no `sort_keys`,
  E/combine/evidence.py:7-10). [proposed] P9
- **Policies.** Optional; written only when the spec has a gate. Place: after `declared`, before
  `result`. The invariants GR-I1 to GR-I6 hold on both sides (erd §4). The SDK decoder adds `gate`
  to `_OPTIONAL_EVIDENCE_KEYS` (S/_evaluation/combine_evidence.py:64) with exact keys.
- **Failure behavior.** The Engine model raises on an invariant break (a plugin bug, never a
  declared code). The SDK decoder refuses an unknown key, a missing key or a broken invariant with
  `ExecutionError` (strict, S/_evaluation/combine_evidence.py:76-86). [existing]
- **Contract tests.** GR#6–GR#11, GD#19.

## C4 Verifier reservation — SDK API and evidence schema

- **Shape.** `sf.Vote(..., verify=None)`; evidence top-level `"verifier": null` (typed null, never
  written in this part). [stated ans:Q4]
- **Policies.** No combine-spec key in this part (P15). The SDK decoder accepts `verifier` only with
  the value null and does not keep it. [proposed]
- **Failure behavior.** `verify=<not None>` → `ValueError` at construction. An evidence with a
  non-null `verifier` → `ExecutionError` in the SDK; a validation error in the Engine model.
- **Contract tests.** VS#1–VS#6.

## C5 Abstain reason — Engine → SDK

- **Shape.** `result: {"member_id": null, "value": null, "status": "abstain", "reason": "gate_not_met"}`.
- **Policies.** `gate_not_met` joins `AbstainReason` and `AnswerReason` on both sides (P13). It is a
  scored decline: the Case is `candidate_abstained`, not failed. No failure code changes
  (`DECLARED_FAILURE_CODES` and `ENGINE_ERROR_CODES` stay the same).
  [existing E/benchmarks/operation_outputs.py:94-111]
- **Failure behavior.** An SDK without the word refuses the evidence (strict words). The SDK and the
  Engine ship together. [implied]
- **Contract tests.** GR#2, GR#12, GD#2, GD#18.

## C6 Context fallback signals — combine context (url4 struct) → Engine core

- **Shape.** `signals` keys `fallback_judge`, `fallback_writer` beside `judge` and `writer_<field>`.
  The Engine `_SIGNAL` pattern becomes `judge|fallback_judge|fallback_writer|writer_[A-Za-z_][A-Za-z0-9_]*`
  (one `re.compile` string, so `ST/unit/test_signal_key_conformance.py` keeps reading it).
  [existing E/combine/spec.py:53]; [proposed]
- **Policies.** CX-I1, CX-I2 (erd §3). The fallback judge reply has the 64 KiB cap of a judge reply
  (`judge_reply`, E/combine/ports.py:601-613, with a `key` argument). The writer reply has the 8 MiB
  result cap (E/combine/endpoint.py:690-691). [existing]; [proposed]
- **Failure behavior.** A fallback key with no matching gate, or a missing key on the fallback
  branch: `combine_spec_invalid`. A bad label: `judge_reply_invalid`. An oversize writer reply:
  `combine_input_too_large`. [existing codes]
- **Contract tests.** GD#11–GD#15, GD#21, GA#16.

## C7 Rebuild — url4 → SDK Python (`Url4.to_python`)

- **Shape.** `decode_combine_spec` accepts the optional key `gate` (dict). The topology decoder
  accepts the signal keys `fallback_judge` (role `judge`, no projection) and `fallback_writer` (role
  `writer`, no projection). [existing S/_evaluation/combine_spec.py:147-165];
  [existing S/_evaluation/topology.py:503-525]
- **Policies.** `Vote._rebuild` splits the signals by key: `judge` → the weights judge (today's
  rule), `fallback_*` → the gate fallback. A fallback judge prompt is recovered in its outputs form
  (`outputs_form_prompt`, S/judge.py:257-265) like a `judge` key. A writer prompt equal to
  `DEFAULT_SYNTHESIS_PROMPT` rebuilds as `prompt=None` (the url4.py:284 rule). A spec with `gate`
  rebuilds only as `sf.Vote` (`_rebuilt_reducer` gives no `sf.Reduce` fallback for it). The fallback
  judge is rebuilt with the existing helper, unchanged:
  `judge_from_signals((dataclasses.replace(signal, key="judge"),), "label")` (S/judge.py:275-296
  refuses any key other than `judge`, so the key is renamed before the call). The compile side
  uses `dataclasses.replace(judge._signal_call(), key="fallback_judge")`, so the prompt is never
  built twice. [proposed] P17
- **Failure behavior.** A hand edit gives `ValueError("URL4 Candidate has a vote spec this SDK
  version cannot rebuild")` or the topology error `_REDUCER_INVALID`. [existing S/reducer.py:185-186]
- **Contract tests.** GA#5, GA#12, GA#13.

## C8 E4c reading contract (no wire change)

- **Shape.** E4c reads: the spec `gate` (C1), the topology signal key of the fallback call (C2), and
  writes the same evidence record (C3).
- **Polarity (P4).** The stored `cmp` keeps the majority when true. E4c's API and report show this
  stored form: an author's `agreement < 0.8` (escalate when) is stored and shown as
  `agreement >= 0.8` (keep when), and the branch says which way the step went. E4c needs no wire
  change to read it. If the owner picks the other polarity at review (store the escalate
  condition: `cmp` true → fallback, and `agreement` takes only `<` or `<=`), that change is made in
  this part, before any wire ships.
- **Policies.** FB-I1: the majority branch never reads the fallback reply. GR-I1: when the vote finds
  no answer, the gate does not run and no fallback output is used. So E4c can skip the call on the
  majority branch and on the "not run" branch and produce the same evidence bytes. [proposed] P8
- **Failure behavior.** A context with no fallback signal on the majority branch is valid today
  (GD-8), so E4c can omit it.
- **Contract tests.** GD#8, GD#9.

## C9 Dependency rule

The combine core (`E/combine/`) stays pure: the gate logic is in `E/combine/gate.py`, which imports
only the standard library, `combine.ports` and `combine.spec` (never `combine.operators` or
`combine.builtins`, the `COMBINE_CORE_FORBIDDEN` rule of `check_layering.py`). It does no I/O. [existing E/combine/endpoint.py:11-14]
The layering gate (`run_gates.py screamingface-engine`) enforces it. [existing .claude/sdlc.local.md]
