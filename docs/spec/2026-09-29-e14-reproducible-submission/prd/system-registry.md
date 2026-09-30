# PRD: System registry — names, revisions, fingerprints (component)

**Source:** ticket (Irina answer 3) · ans:Q1, Q8, Q14, Q15 · **Priority:** P0 (the submit, replay and E8 flows need it)
**Lifecycle:** planned (new component in `apps/scoreboard`, plus a pure helper in `packages/url4`)
**Owner:** unassigned

## 1. Flows served

This is a component PRD. No single flow owns its rules.

- `prd/submit-and-cluster.md` resolves or claims a name on each public submit.
- `prd/replay-pinned-run.md` resolves `name`, `name@rN` and `name@<date>` pins.
- E8 (OME-1297, not this epic) will resolve `screamingface/<name>` to the latest revision.

## 2. Background and constraints

- "The leaderboard should somehow detect whether the existing url4 (minus the benchmark) was
  already submitted under a name before allowing a new name to be given. […] the system should
  be called the same." `[stated prompt]` (ticket, Irina answer 3)
- Names are global. The first submitter owns a name `[stated ans:Q8]`.
- The owner can declare a new url4 as the next revision of a name `[stated ans:Q14]`.
- When a known system arrives under a different name, the submission uses the existing name
  and returns a notice `[stated ans:Q15]`.
- Data model: `System`, `SystemRevision` (`erd.md` §2.3), with the invariants I-N1 to I-N4.

### 2.1 Current behavior

- A submission carries a free-form `spec_id` (the result name), up to 255 chars. It is not
  unique and has no owner `[existing apps/scoreboard/src/scoreboard/scores/models/score.py:16]`.
- No fingerprint of a url4 exists. The canonical text is the identifier
  `[existing packages/screamingface/src/screamingface/_evaluation/model.py:360-365]`.
- The benchmark wraps the candidate as a zero-weight `candidate` binding
  `[existing packages/screamingface/src/screamingface/_evaluation/linking.py:34-40]`, and the SDK
  can extract it again
  `[existing packages/screamingface/src/screamingface/_evaluation/url4.py:109-126]`.
- The scoreboard does not depend on `url4` today `[existing apps/scoreboard/pyproject.toml]`.

**Delta.** Add a `url4.fingerprint` module, a scoreboard dependency on `packages/url4`, the
two tables, and a `SystemRegistry` service with the operations below.

## 3. Scenarios and acceptance criteria

### 3.1 Behavior (operations)

The registry has three operations. The submit flow calls them inside its database transaction.

`resolve_for_submit(linked_url4, requested_name, revision_of, submitter, board_visibility)
→ Resolution(system, revision, notice | None)`

`resolve_pin(pin, benchmark_id) → SystemRevision | [SystemRevision]` (read-only)

`fingerprint(linked_url4) → str` (pure)

**SR-H1** `[stated prompt]` — new system, new name.
Given no revision has fingerprint F, and no system has name `kevins-best`,
when Kevin submits url4 U (fingerprint F) on a public board with name `kevins-best`,
then `System(name="kevins-best", owner=kevin)` and `SystemRevision(revision=1, fingerprint=F)`
exist, and the resolution has no notice.

**SR-H2** `[stated prompt]` — same system, other benchmark.
Given Ana named fingerprint F `opus-5.5` from a run on benchmark B1,
when Bruno submits the same candidate (fingerprint F) on benchmark B2 with name `opus-5.5`,
then the resolution returns the existing system and revision 1, and creates no new row.

**SR-H3** `[stated ans:Q15]` — same system, different name.
Given fingerprint F is named `opus-5.5` (owner Ana),
when Bruno submits fingerprint F with name `bruno-opus`,
then the resolution returns `opus-5.5` revision 1, with the notice
`{"code": "system_already_named", "name": "opus-5.5", "owner": "<Ana's published identity>"}`.
The submission is not rejected.

**SR-H4** `[stated ans:Q14]` — owner declares a revision.
Given Kevin owns `kevins-best` with revision 1 (fingerprint F1),
when Kevin submits fingerprint F2 (new) with `revision_of="kevins-best"`,
then `SystemRevision(revision=2, fingerprint=F2)` is created under `kevins-best`.

**SR-H5** `[stated ans:Q7]` — pin resolution.
Given `kevins-best` has revisions 1 and 2,
then `resolve_pin("kevins-best@r1")` returns revision 1,
`resolve_pin("kevins-best")` returns the latest revision (2), and
`resolve_pin("kevins-best@2026-09-01")` returns every revision. The replay flow then selects
by result date (`prd/replay-pinned-run.md`).

### 3.2 Error paths

**SR-E1** `[stated ans:Q14]` — revision by a non-owner.
Given Kevin owns `kevins-best`,
when Bruno submits a new fingerprint with `revision_of="kevins-best"`,
then the submit fails with `403 not_system_owner`. No row is written.

**SR-E2** `[proposed — gap §per-flow/boundary]` — invalid name.
When a submission name is empty, longer than 64 chars, contains `/`, or fails the pattern in
`erd.md` §2.3.1, then the submit fails with `422 invalid_system_name` and a message that
names the rule.

**SR-E3** `[stated ans:Q17]` — name taken by a different system.
Given `opus-5.5` belongs to fingerprint F1,
when Bruno submits fingerprint F2 (new) with name `opus-5.5` and no `revision_of`,
then the submit fails with `409 system_name_taken`, including a suggested name.
The SDK keeps the report, so the resubmit with a new name costs no rerun
(`prd/submit-and-cluster.md` SC-E3).

**SR-E4** `[proposed]` — `revision_of` names an unknown system.
When `revision_of` names a system that does not exist, then the submit fails with
`404 system_not_found`.

**SR-E5** `[proposed]` — the linked url4 has no `candidate` binding.
When `url4_expression` has no `candidate` binding (for example, a direct run), then the
fingerprint is computed over the whole canonical url4 (`render(build(url4))`), and the
resolution proceeds `[stated ans:Q20]`. A direct run has no benchmark binding, so nothing is
stripped. When the expression does not parse, the submit fails with `422 invalid_url4`. When
the expression is longer than 32,000 characters, the submit fails with `422` before any parse
(the existing `ScoreSubmission` cap
`[existing apps/scoreboard/src/scoreboard/scores/schemas.py:378]`; D7, X-22).

**SR-E6** `[proposed D8]` — a `_sf_recipe` source that is not inert.
Given a linked url4 whose system has a top-level `_sf_recipe` source that is not inert (its
value is not text, or its weight is not the explicit scalar `0.0`, or a `$_sf_recipe`
reference stays in the rest of the system),
when the scoreboard computes the fingerprint,
then `url4.fingerprint` raises `ExcludedBindingError` (a `url4.Url4Error`, code
`malformed_source`), and the submit fails with `422 invalid_url4`. No row is written.
Why: if the function hid a working source, two systems that behave differently would get one
fingerprint (`erd.md` §2.3.2).

### 3.3 Derived scenarios (risk order)

**SR-D1 — the client lies about the fingerprint** `[proposed — gap §security]` · H×M
Given a client sends `system_fingerprint="<F of Ana's system>"` with a different url4,
when the scoreboard handles the submit,
then it ignores the client value, recomputes F from `url4_expression`, and resolves by the
recomputed value.
Why: a trusted client fingerprint would let an attacker claim another system's cluster or
dodge clustering.

**SR-D2 — two first submits of one new system race** `[proposed — gap §concurrency]` · H×M
Given no revision has fingerprint F,
when two submits with fingerprint F commit at the same time with names `a` and `b`,
then exactly one `SystemRevision` with fingerprint F exists. The loser hits the unique
violation on `fingerprint`, retries the lookup once in a new transaction, and resolves to the
winner's name with the SR-H3 notice.

**SR-D3 — two different systems race for one new name** `[proposed — gap §concurrency]` · M×L
When two submits with different fingerprints claim the same new name at the same time,
then exactly one `System` row exists, and the loser gets `409 system_name_taken`.

**SR-D4 — two revision declarations race** `[proposed — gap §concurrency]` · M×L
When the owner declares two new fingerprints at the same time,
then they get revisions N+1 and N+2. No gap, no duplicate: unique `(system_id, revision)`,
with a retry.

**SR-D5 — answer seed and recipe name do not split a system** `[stated ans:Q20]` · M×M
Given candidate C submitted with `answer_seed=1` and again with `answer_seed=2`,
then both produce the same fingerprint.
Given two SDK candidates that differ only in the recipe display name (the JSON `name` and
`named` keys of the zero-weight `_sf_recipe` binding
`[existing packages/screamingface/src/screamingface/_evaluation/topology.py:14]`),
when the scoreboard calls
`system_fingerprint(linked, binding="candidate", exclude_bindings=frozenset({"_sf_recipe"}))`,
then both produce the same fingerprint. A rename is not a new system.
The function removes the `_sf_recipe` source only when it is inert: a text value, the explicit
scalar weight `0.0`, and no `$_sf_recipe` reference in the rest of the system
`[existing packages/url4/src/url4/fingerprint.py:92-133]`. The SDK writes `_sf_recipe` in that
form. Any other `_sf_recipe` source is an error (SR-E6).
Given two candidates that differ only in a `seed` parameter that the Candidate itself declares
(`sf.Model(..., params={"seed": 7})`, which is in the url4 text),
then they produce **different** fingerprints. A declared seed is part of the system.

**SR-D6 — canonical form is stable** `[proposed]` · H×L
Given two url4 texts that differ only in whitespace or in equivalent spelling that
`render(build())` normalizes,
then they produce the same fingerprint. This is a property test over generated expressions.

**SR-D7 — name case** `[proposed]` · M×M
When Bruno submits `Opus-5.5` and `opus-5.5` exists,
then the input is normalized to lowercase and resolves to the existing name.

**SR-D8 — private board never touches the registry** `[proposed]` · H×L
When a submit arrives on a private board,
then no `System` or `SystemRevision` row is read for name claims or written. The cluster
uses the private key (`erd.md` §2.4).

**SR-D9 — unicode and confusables** `[proposed]` · L×M
When a name contains a non-ASCII character, it fails SR-E2. The ASCII-only pattern blocks
homoglyph squatting.

**Not applicable:** cancel or resume (the operations are single-transaction and have no
multi-step state). Empty state: the first submit on an empty registry is SR-H1.

## 4. Non-functional requirements

- `resolve_for_submit` adds ≤ 20 ms p99 to a submit: two indexed lookups and at most two
  inserts `[proposed]`.
- `fingerprint` of a url4 at the 32,000-character cap finishes in ≤ 50 ms `[proposed]`. The
  parse bomb cap is the existing 32,000-character limit on `url4_expression`, with `422`,
  checked before any parse (D7, X-22). There is no separate 256 KiB / `413` cap.
- Observability `[proposed]`: counters `scoreboard_system_resolutions_total{outcome=new|existing|renamed_notice|revision}`,
  `scoreboard_system_name_conflicts_total`.
- Security: names and url4 are untrusted input. Validate before any write. A name is never
  rendered as HTML (the portal escapes it).

## 5. Out of scope

- Renaming or transferring a system. Squatting disputes are handled by an admin in the
  database (a future issue).
- Fuzzy "similar system" detection. Only an exact canonical match counts `[stated prompt]`.
- Namespaced names `screamingface/<user>/<name>` (rejected in `ans:Q8`).

## 6. Open questions

None. DQ-1 is decided: a taken name is rejected with `409` and a suggestion (SR-E3,
`ans:Q17`).

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: core-out. The pure fingerprint first (everything depends on it), then the registry
rules, then the races. Each RED test must fail on a missing behavior, not on an import error:
create the empty module first.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| SR-1 | `fingerprint_ignores_client_supplied_value` — the registry resolves by the recomputed hash | unit | [proposed] SR-D1 | H×M | the service signature takes only `linked_url4`; there is no fingerprint parameter |
| SR-2 | `fingerprint_equal_for_normalizable_spellings` (property, Hypothesis) | unit | [proposed] SR-D6 | H×L | `sha256(render(build(candidate)))` |
| SR-3 | `fingerprint_strips_answer_seed` | unit | [stated ans:Q20] SR-D5 | M×M | remove the seed binding before render; the same file also pins `exclude_bindings={"_sf_recipe"}` (a recipe rename gives one fingerprint) and a declared `seed` that stays in the hash |
| SR-4 | `fingerprint_same_candidate_on_two_benchmarks` | unit | [stated prompt] SR-H2 | H×M | extract the `candidate` binding |
| SR-5 | `fingerprint_parity_sdk_and_scoreboard` — the SDK and the scoreboard give the same value for 50 fixture url4s | integration | [proposed] | H×L | both import `url4.fingerprint` |
| SR-6 | `new_fingerprint_new_name_creates_system_rev1` | unit | [stated prompt] SR-H1 | H×H | insert both rows |
| SR-7 | `known_fingerprint_reuses_name_no_rows` | unit | [stated prompt] SR-H2 | H×H | lookup by fingerprint first |
| SR-8 | `known_fingerprint_other_name_returns_notice` | unit | [stated ans:Q15] SR-H3 | H×H | build the notice |
| SR-9 | `owner_declares_revision_two` | unit | [stated ans:Q14] SR-H4 | H×M | max(revision)+1 |
| SR-10 | `non_owner_revision_rejected_403_no_write` | unit | [stated ans:Q14] SR-E1 | H×M | owner check before insert |
| SR-11 | `private_board_never_writes_registry` | unit | [proposed] SR-D8 | H×L | early return on private |
| SR-12 | `concurrent_first_submits_one_revision` (two DB sessions) | integration | [proposed] SR-D2 | H×M | catch the unique violation, re-read once |
| SR-13 | `taken_name_by_other_system_409_with_suggestion` | unit | [stated ans:Q17] SR-E3 | M×M | suggestion `<name>-<4 hex of fingerprint>` |
| SR-14 | `concurrent_name_claims_one_winner` | integration | [proposed] SR-D3 | M×L | unique on `name` |
| SR-15 | `concurrent_revisions_contiguous` | integration | [proposed] SR-D4 | M×L | unique `(system_id, revision)` plus retry |
| SR-16 | `name_rules_boundaries` (0, 1, 64, 65 chars; `/`; leading `-`; uppercase) | unit | [proposed] SR-E2 SR-D7 | M×M | regex plus lowercase |
| SR-17 | `non_ascii_name_rejected` | unit | [proposed] SR-D9 | L×M | same regex |
| SR-18 | `revision_of_unknown_404` | unit | [proposed] SR-E4 | M×L | lookup |
| SR-19 | `unparseable_url4_422_and_oversize_422` | unit | [proposed] SR-E5 (X-22) | M×L | size check (32,000 chars) before parse |
| SR-19b | `non_inert_excluded_binding_422_invalid_url4` (weight absent, weight `1.0`, a non-text value, a `$_sf_recipe` reference) | unit | [proposed D8] SR-E6 | H×L | map `ExcludedBindingError` like any `Url4Error` to `422 invalid_url4` |
| SR-20 | `resolve_pin_forms` (`name`, `name@r1`, `name@<date>`) | unit | [stated ans:Q7] SR-H5 | M×M | pin parser |

**Refactor notes.** Keep the registry behind a `SystemRegistry` port in the scoreboard core,
with the Tortoise adapter apart, so E8 can reuse the port without the submit route.
