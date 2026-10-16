# PRD: Verifier slot (`verify=None`, reserved `verifier`)

**Source:** ans:Q4 ("Reserved param + key (Recommended)") · **Priority:** P1
**Lifecycle:** planned
**Owner:** unassigned
Paths: [erd §4](../erd.md) · contract: C4

## 1. Summary and user story

As the author of a later part that adds a verifier ("winner must pass an extra check, else try the
runner-up, else abstain"), I want a named place on the vote and in the evidence now, so that the
check comes with no new join type and no rename.

## 2. Background and constraints

- "the vote gets `verify=` that accepts only None now (clear error otherwise); the evidence schema
  reserves an optional `verifier` key. A later part adds the check with no new join type."
  [stated ans:Q4]
- "Do not block E4b on building it. Leave a named place on the vote." [stated epic]

### 2.1 Current behavior

- `sf.Vote(*, extract, normalize, weights, judge)` (S/reducer.py:477-493) has no `verify`.
- The evidence has no `verifier` key (E/combine/evidence.py:133-166).

**Delta.**

- `sf.Vote.__init__(..., judge=None, gate=None, verify=None)`. The dataclass gets the field
  `verify: None`. A value that `is not None` raises
  `ValueError("sf.Vote verify= is reserved for a later part; pass None or leave it out")`. The repr,
  the Python form and the compile do not show it (P15).
- Engine `CombineEvidence.verifier: None = Field(default=None, exclude_if=lambda value: value is None)`,
  after `gate`. The JSON schema property is `{"default": null, "title": "Verifier", "type": "null"}`.
  The endpoint never sets it.
- SDK decoder: `verifier` is in `_OPTIONAL_EVIDENCE_KEYS`. When present, its value must be `None`;
  any other value raises `ExecutionError(f"{label} verifier is reserved and must be null")`. The SDK
  `CombineEvidence` has no `verifier` field: a decoded null is dropped, and `to_dict()` does not
  write it. This is the one documented exception to "`to_dict()` equals the wire" (no Engine of this
  part writes the key).
- No combine-spec key. A later part adds an optional `verify` key with the check, the way this part
  adds `gate`. [proposed] P15

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **VS-1** Given `sf.Vote(verify=None)` and `sf.Vote()`, then both are equal, `vote.verify is None`,
  and both compile to the same bytes as today's `sf.Vote()`. [stated ans:Q4]
- **VS-2** Given the evidence v1 schema snapshot, then `properties.verifier ==
  {"default": None, "title": "Verifier", "type": "null"}` and `"verifier"` is not in `required`.
  [stated ans:Q4]
- **VS-3** Given an evidence wire (the GR-3 wire) plus `"verifier": null`, then the SDK decodes it,
  and `decoded.to_dict()` equals the wire without the `verifier` key. [proposed]

### 3.2 Error paths

- **VS-E1** Given `sf.Vote(verify=lambda answer: True)`, `sf.Vote(verify="model")` or
  `sf.Vote(verify=False)`, then `ValueError` whose message has `verify=` and `reserved`.
  [stated ans:Q4]
- **VS-E2** Given an evidence wire with `"verifier": {}` or `"verifier": "ok"`, then the SDK raises
  `ExecutionError` with `verifier is reserved`; and the Engine
  `CombineEvidence.model_validate({..., "verifier": {}})` raises `ValidationError`. [proposed]

### 3.3 Derived scenarios

- **VS-D1** (M×M) [proposed] Given any evidence the Engine writes in this part, then it has no
  `verifier` key (the 37 contract cases).
- **VS-D2** (M×L) [proposed] Given a compiled Vote, then `repr(vote)` and `Url4.to_python()` have
  no `verify`, and a rebuilt Vote has `verify is None`.

## 4. Non-functional requirements

None beyond the house rules.

## 5. Out of scope

The check itself, the runner-up rule, a `verify` spec key (D5).

## 6. Open questions

None.

## 7. TDD plan

Rows 1–3 belong to build unit 1 (with the gate record); rows 4–6 belong to unit 3 (with the SDK
API). New test files: `ET/test_combine_gate_words.py` (row 1–2 Engine part), `ST/test_gate_words.py`
(row 3), `ST/test_gate_api.py` (rows 4–6).

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| 1 | `evidence_schema_reserves_an_optional_null_verifier` | unit | VS-2 | M×M | field after `gate` |
| 2 | `engine_evidence_refuses_a_non_null_verifier_and_never_writes_it` | unit | VS-E2, VS-D1 | M×M | typed `None` |
| 3 | `sdk_decoder_accepts_a_null_verifier_and_refuses_any_other_value` | unit | VS-3, VS-E2 | M×M | `_OPTIONAL_EVIDENCE_KEYS` |
| 4 | `vote_accepts_verify_none_and_keeps_its_bytes` | unit | VS-1 | M×M | the field `verify` |
| 5 | `vote_refuses_any_verify_value_but_none` | unit | VS-E1 | M×M | the check |
| 6 | `vote_repr_and_rebuild_leave_verify_out` | unit | VS-D2 | M×L | `_render` unchanged |
