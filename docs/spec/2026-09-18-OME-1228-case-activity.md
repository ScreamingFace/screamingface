# Case identity for live model activity

Carry the benchmark's explicit Case ID alongside candidate input before model execution. Engine protocol builders opt in with `case_id`; an explicit `context_format=case-v1` parameter identifies a JSON envelope containing `input` and `case_id`. The candidate handler unwraps it before evaluation. Plain requests keep their existing meaning. Structured inputs are serialized exactly as URL4 currently serializes them; metadata never reaches the model prompt.

A benchmark-owned, run-bound context carries the ID through awaited nested calls. The optional activity adapter reads it when constructing model-call activity. Core execution imports no activity implementation. Missing context remains absent; concurrent tasks and nested runs must not inherit another case. Context tokens reset after exceptions and cancellation. Activity disabled remains silent.

All shipped benchmark candidate builders supply their case ID explicitly. MedXpertQA supplies its existing structured input as a mapping so wrapping does not turn URL4 struct syntax into model text. Request payloads and raw errors never become log fields. IDs use the existing benchmark validation and activity allowlist; unsupported telemetry identifiers must not suppress otherwise-valid model records.

This PR is independent of #980: it attributes existing model-call events only. Stage/grading attribution in #980 will consume the same context or explicit IDs already owned by grading endpoints. It does not add member/role attribution, case ordinals, score updates or URL4 features.

Activity-to-result identity joins compare `str(case_id)` on both sides. URL4 template interpolation carries integer IDs as decimal strings; do not parse numeric-looking strings, so `"007"` remains distinct from `7`. Benchmark result IDs retain their existing types. This is an identity, not a case ordinal. The shared Inspect builder supplies the same envelope for every imported board.


## Selected-case numbering — 2026-09-18

The shared protocol selection resolves the requested prefix once and annotates each selected row with one-based position and selected total. Candidate builders carry these as optional envelope fields, removed before model input. Scope isolates them per run and case. Position/count are both present or both absent, positive integers with position <= count. Model activity publishes safe scalar fields case_position and case_count; Client displays [Case n/N], falling back to Case ID. No role attribution or guessed ordinals.

## Review fix — validate selector dataset dependencies (2026-09-22)

The selected-cases wrapper must preserve installation-time validation of its dataset route.
Registry route discovery must inspect parseable local-call context source lists, including nested
calls, while retaining URL4's prose/holdings fallback and ignoring quoted text and remote-call
contexts. A missing literal dataset route fails registration before evaluation. Valid datasets,
selection order, expression fingerprints, prompts and scores remain unchanged.

## Native index supersedes selector (2026-09-23)

The native-index follow-up replaces synthetic row numbering and the selected-cases route.
See `2026-09-23-OME-1228-native-index.md`: the existing cases route validates selection,
URL4 supplies `$index`, and the candidate envelope carries case_index plus the known total.
Event fields remain one-based case_position and case_count.
