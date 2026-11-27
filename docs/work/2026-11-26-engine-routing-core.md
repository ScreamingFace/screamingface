---
ticket: OME-2044
stack: screamingface-engine
status: in_progress
started: 2026-11-26
finished:
---

# engine-routing-core — Unit 5.2 shared Engine routing core

## Intent

Implement the Unit 5.2 Engine half of the Router Recipe extension
(`docs/spec/2026-11-16-router-recipe-extension/`, contracts C2-C8, C11, C16, C17): one Engine-owned
routing application boundary shared by named profiles and the future Router DAG. Named profiles
gain a dynamic-choice form; the fixed profile keeps its TOML, revision bytes, scalar classifier
body, `routed-answer-v1` wire and errors unchanged.

## Planned changes

New (Engine `src/screamingface_engine/`):

- `world/routing_policy.py` — the pure C6 decision over validated evidence; no HTTP, url4, config
  or recorder imports.
- `world/router_spec.py` — the strict C2 envelope/definition codec and the C3 revision.
- `world/router_decision.py` — the strict C5 draft and completed-record codec (moved to the leaves
  `router_decision.py` and `router_vocabulary.py`; see Decisions).
- `world/routing_core.py` — shared metadata/access preflight, evidence validation, selected-call
  dispatch port, C11 error normalization.
- `world/attempt_facts.py` — the C8 transport observer, the attempt-fact channel and the direct
  entry's private attempt scope.
- `world/router_runtime.py` — url4-free ADMIT/CLASSIFY/DECIDE/OPEN/JOIN handlers.
- `rest/classifiers.py` — C17 `GET /v1/classifiers`.

Modified:

- `world/routing_config.py` — the dynamic profile form and its C2 normalization.
- `world/routing.py` — consume the policy/core; dynamic choice input and preflight.
- `world/classification.py` — the C7 choice input on the classification port.
- `world/gateway_transport.py` — optional keyword-only attempt observer on `_post_completion` and
  `_post_answered`; the two-value return is unchanged.
- `world/gateway_endpoints.py` — Router runtime registration adapter; direct presenter.
- `world/factory.py` — install the Router runtime after the direct-mount snapshot.
- `error_text.py` — `ROUTER_CODES` joins `ENGINE_RESERVED_CODES`.
- The REST app wiring for C17.

Tests: new files under `apps/screamingface-engine/tests/unit/` only. Prior tests stay unchanged
unless an exact owner approval names the file.

## Test plan

RED first, in this order:

1. C3 vectors V1-V5 byte-exact; C2 strict refusals (missing/extra keys, wrong variant, NaN/1e999,
   boolean as number, bounds, duplicate labels, policy/source mismatch, Calls shape, revision
   mismatch).
2. Every C6 row, including the named-profile tie as `routing_ambiguous` and missing/extra labels
   as `routing_invalid_scores`.
3. Dynamic profile: choice input in branch order, hashed params, mixed config fails at startup,
   refusals make no branch call; fixed-profile TOML/digest/body/codes unchanged.
4. C8 facts: retries, missing header, lost reply, replay/cache zero, `possibly_billed`, observer
   through retries and on a final exception; direct-entry private scope.
5. C11 spoof matrix; C17 projection, freshness, bounds, private headers, zero inference.
6. Router runtime in a Gateway world without benchmarks: hand-authored C4 fixture, ADMIT
   refusals before I/O, `router_unsupported` outside a recorder scope, OME-1809 run-file
   admission, one C5 record per terminal path, draft never accepted by readers.

## Acceptance

- C2/C3 strict records and V1-V5 pass; all C6 rows pass.
- A dynamic profile makes one selected generation and zero unselected calls; a classifier
  failure never runs a default.
- Fixed profile TOML/digest/scalar body/wire/errors unchanged.
- `_post_completion` keeps its two-value return; unknown upstream attempts stay distinct from 0.
- C17 is fresh, caller-scoped, private, bounded and makes no inference.
- Router/branch/combine routes work in Gateway worlds without benchmarks.
- Layering, URL4 allowlist, Engine CI path guard, repo and full Engine gates pass on Python 3.12
  and 3.13.

## Decisions during work

- **Subset scope (approved 2026-11-26).** Unit 5.2 keeps strict C2/C3/C5 codecs and the pure C6
  `select=all` decision, but executes only `select=one`, default and no-selection. The panel url4,
  Router-to-combine `selection`, quorum and synthesizer failures move to Unit 6, where C4 pins the
  panel. `combine._parse_selection` is unchanged. ADMIT refuses a `select=all` spec as
  `router_unsupported` (permanent, before any I/O), so subset stays unadvertised and unemitted.
  *Superseded in the fix iteration below:* ADMIT now admits and preflights `select=all`, DECIDE
  decides it purely, and OPEN/JOIN refuse a selected subset, as the C4 scope on main states.
- **Codec location.** The C5 codec is the shared leaf `router_decision.py`, not
  `world/router_decision.py`: JOIN publishes the record on its `OperationCall`, and
  `operation_calls` is a leaf that may not import the world (E4c precedent: `combine/decision.py`).
  The labels, policy, evidence, strict JSON reader and `field_rule` that C2 and C5 share live once in
  the leaf `router_vocabulary.py`; `world/router_spec.py` and `world/routing_policy.py` import them.
- **Runtime module split (deviation from one `world/router_runtime.py`).** The steps are split by
  responsibility to stay under 450 lines each: `router_steps` (routes, step context, ADMIT result
  and draft readers, iterate rows), `router_admit` (ADMIT + scoring CLASSIFY), `router_decide`
  (DECIDE + OPEN), `router_evidence` (classifier output to C6 evidence), `router_join` (the single
  publisher). None imports url4; `gateway_endpoints.install_router_runtime` is the only adapter
  that registers them on the node, called from `factory._install_internal_routes_or_close` after
  the direct-mount snapshot, so every Gateway world serves them with or without Benchmarks.
- **Run-file admission is shared.** `connector._ModelEndpoint._admit_run_files` became the
  module-level `connector.admit_run_files`, unchanged in behavior; ADMIT awaits it after its
  preflight, so a refused occurrence never waits for it and a file refusal ends the run unchanged.
- **Attempt facts first (C11).** *Superseded below by recorded call outcomes.* A bound call's
  iterate row is read by its C8 attempt fact first
  (`router_evidence.read_call_row`): an answered call's row is its reply even when shaped like an
  error row, and a failed call's code is the fact's origin code. With no fact (no HTTP attempt),
  the row's shape decides.
- **Preflight codes are the shared preflight's.** ADMIT refusals reuse `routing_profile_not_found`,
  `routing_profile_mismatch`, `routing_connection_missing`, `routing_preflight_failed` and
  `routing_preflight_unavailable`; C11 adds no Router code for them. A Model this world cannot
  execute is `routing_profile_not_found`.
- **Frozen copies.** A scoring Router is `router_unsupported` in capture and replay (storing and
  replaying a classification is C9, Unit 6); selector Routers run there.
- **Parameter contract.** `world/parameter_contract.py` checks each Model parameter in the SDK
  E4c preflight's four stages (row exists, Gateway forwards it, provider does not refuse it, value
  fits the Gateway schema). The fixed profile keeps its shipped `max_tokens` check.
- **Classifier inputs.** The question is checked against the classifier's C7 text limits; the
  choice input is built once by `classifier_limits.choice_input`, shared by the dynamic profile
  and the Router. CLASSIFY records its operation only on success; a failure is data.
  *Superseded below:* a failed classification is also one unpriced classify operation.
- **Step naming.** OPEN intents and JOIN keys are `c<K>` per candidate and `d` for the default.
  url4 requires an intent on every call, so a step that takes none is written `!''`.
- **url4 structured rows (url4 spec 5.3.8).** url4 embeds a visibly structured iterate row (an
  error row, a KEYWORDS result, a JSON-shaped reply) as a JSON value written by Python's default
  encoder. `router_steps.read_rows` reads the array with the same codec and turns a structured row
  back into JSON text, so error rows, KEYWORDS and JSON answers all read; found by the regex runtime
  test, and the shared `rows` test fixture now packs rows as url4 does.
- **Classifier cost.** `classifier_call.cost` is the Budget's own charge rule (`budget.call_charge`)
  over the recorded provider call; an unpriced or unrecorded call stays null.

## Risks and findings

- **Resolved in the fix iteration: JSON-shaped answers are now returned byte for byte.** Before
  it, they were equal as JSON only. Through a Router, `{"a":1}` reaches
  the caller as `{"a": 1}`, and a `\u00e9` escape in the reply comes back as the raw character;
  the bytes are lost inside url4 before JOIN reads them. Scorers that parse JSON are unaffected;
  an exact-bytes scorer is not.
- **Pre-existing (not changed):** E4c JOIN `branch._slot` (`world/branch.py:788`) requires string
  rows, so a Gate branch whose answer is JSON-shaped fails as a contract error. Error rows never
  reach it (E4c bodies use `on_error=fail`). Read from the code, not reproduced in a run.
- **No-fact rows.** *Changed in the fix iteration:* a row is read from its call's recorded
  outcome. An answer needs an answered attempt fact (the Gateway owns the cache, so an answered
  call always makes an Engine attempt). A failure with no attempt keeps its recorded code, and C5
  then reports no attempts.
- **Engine-interpreted params.** `web_search`, `web_search_exclude` and `binding` need no Gateway
  row (`request_parameters.model_params`), so ADMIT does not check them; a value the Candidate
  adapter refuses fails at `generate`, not at ADMIT.
- **Preflight codes in a Case.** The reused `routing_*` codes are not C8-declared Router codes, so
  a Case reads them as `upstream_error`.

## Fix iteration: occurrence provenance and strict records (2026-11-26)

Every blocking, high and medium defect found in the first candidate was reproduced as a failing
test and then closed; each mechanism below has a test that fails on its mutation.

- **Occurrence provenance (C4, C8).** `operation_provenance.py` gives each capture scope one
  internal channel, opened and closed with the innermost `capture_operation_calls`. It holds C8
  attempt facts, one immutable `CallOutcome` per bound call, and the canonical ADMIT result and
  DECIDE draft per `(step, binding)`. Nothing in it reaches a projection, report or budget.
- **Single assignment.** A second ADMIT or DECIDE for one binding is a contract error, even when
  identical, and `first_run` refuses it before any read. A second call outcome for one binding
  never replaces the first: it marks the binding ambiguous, and a Router step that reads it fails
  closed. One logical call per Router binding and scope is the rule, because E4c may call one
  binding more than once.
- **Proven steps.** CLASSIFY, OPEN, DECIDE and JOIN accept an ADMIT result or a draft only when it
  equals the recorded canonical document. JOIN also requires `admit.router == draft.router ==`
  its binding. Outside a scope, ADMIT stays `router_unsupported`, so only a carried failure exists
  there.
- **Rows proven by their call.** The connector wraps every bound endpoint call in `outcome_of`.
  It records `answered` with the reply, `failed` with exactly what url4 writes into the error row,
  or `cancelled`. A selector row or a branch row is accepted only as the recorded outcome of its
  binding and Model. An answer also needs its answered attempt fact, a failure row its recorded
  failure, and a cancelled call proves no row. JOIN returns the recorded reply bytes, so
  JSON-shaped answers now reach the caller byte for byte.
- **Scoring classification.** DECIDE accepts scores only as the classify route's recorded
  document under `router_N`, with an answered attempt fact for an answer. A failed classification
  is one unpriced provider operation, so the E4c budget fold counts it once. A control-plane ending
  or a cancellation records only its internal outcome and propagates.
- **KEYWORDS recomputed.** KEYWORDS is pure, so DECIDE recomputes it from the admitted question
  (`router_keywords.py`, E4c's 65,536-character window) instead of trusting the row.
- **Strict metadata.** `limits: null` serves direct scalar classification only, and a Router
  refuses it. Model IDs are compared in their canonical colon form, never the route's `~` escape.
  Classifier rows with an unhashable ID or a repeated key are omitted, an envelope with a repeated
  key is the fixed 502, and Gateway documents read through strict JSON.
- **C5/C6 codec.** One reason table (`router_vocabulary.best_reason`/`exact_reason`) serves the
  policy and the codec. A record must also agree on its classifier call binding, its branches,
  quorum and synthesis (`router_record_parts.py`).
- **Subset.** `select=all` is admitted, preflighted (a Model synthesizer included) and decided
  purely; OPEN never opens `panel` and refuses a selected subset, and JOIN refuses to publish one.

### Risks added by the fix iteration

- A url4-level failure that never invokes the endpoint (a guard timeout, for one) leaves no
  recorded outcome, so a row it produces is a contract error rather than a branch failure.
- One logical call per Router binding and scope: a binding called twice fails the Router closed.
- A failed scoring classification now appears in the operations projection as an unpriced
  provider call.
- A KEYWORDS error row is a contract error, no longer a classify failure.
- `limits: null` classifiers cannot serve a Router.

## Second fix iteration: atomic steps, late phases, closed vocabulary (2026-11-26)

Status: DONE. Each change below was first a failing test.

- **Atomic step claims (C4, C5).** `operation_provenance.claim_step` claims `(step, binding)` in
  the innermost capture scope synchronously, before the step's first await, read, provider call or
  publication; `router_provenance.first_run` turns a second claim into a contract error. ADMIT,
  DECIDE and JOIN claim at entry, the scoring CLASSIFY once its ADMIT result is proven accepted. A
  second claim, sequential or concurrent, therefore makes no preflight, no classification call and
  no C5 record. The step documents stay as the proofs later steps read, and still refuse a second
  write. A CLASSIFY over a non-accepted ADMIT result has no binding and claims nothing; it returns
  `not_run` and has no effect to repeat.
- **Failed outcome phases (C5).** `outcome="failed"` is legal only at `input`, `admit`,
  `classify` or `decide`; a record pairing it with `generate`, `default` or `synthesize` refuses.
- **Classifier call binding without evidence (C5, C8).** When a failed record keeps no evidence,
  a present `classifier_call` must still be the policy's classifier call: `router_N` (the
  record's own binding) for `best`, a `selector_N` for `exact`. A null call stays legal: C5 makes
  it `null` when the classifier did not run, as for `{"not_run": true}` beside an accepted ADMIT,
  which C4 makes a `decide` failure with `router_evidence_invalid` and one published record.
- **Closed provider-support vocabulary.** A parameter row admits a value only when its
  `provider.support` is a string in the Gateway's closed vocabulary other than `unsupported`
  (`supported`, `conditional`, `unknown`); any other value or type misfits.
- **Tests.** `test_router_replay.py` runs each duplicate on the real url4 executor over a Gateway
  world: an ADMIT or CLASSIFY beside one held by the Gateway (the second refuses and the held one
  is cancelled: one preflight read, one classification request), a CLASSIFY after its occurrence
  ran, side-by-side classifications, a second DECIDE, a second JOIN (one C5 record), and
  `not_run` beside an accepted ADMIT (one `decide` record with a null call).
  `test_router_record_failures.py` holds the positive and negative failed records; the claim and
  vocabulary cases extend `test_operation_provenance.py` and `test_parameter_contract.py`.

### Risks added by the second fix iteration

- A Router step that refused keeps its claim, so the same scope cannot run that step again for
  the binding. No C4 block guards a Router step with `;retry=`.
- Without evidence, an `exact` record cannot tell an llm selector from KEYWORDS, so a
  `selector_N` call on a failed KEYWORDS occurrence is not refused by the codec alone; JOIN never
  builds one.
- Removing DECIDE's claim alone is not observable: DECIDE has no effect before its recorded
  draft, which refuses a second write with the same error.

## Fix: RE2 loads only for a regex selector (2026-11-26)

Status: DONE. Each change below was first a failing test.

- **Cause.** The SDK runtime CLI reads the world file through `world.config.load_config` before
  it starts an Engine, in an install without the Engine's `google-re2` dependency (the SDK's
  `runtime` extra carries it; its test lane installs only `notebook`). `parse_config` imports
  `world.routing_config`, which imported `world.router_spec`, whose module-level `compile_regex`
  import loaded `combine.operators.extract` and so `re2`. Twelve unchanged SDK runtime tests
  failed on Python 3.12 and 3.13 with `ModuleNotFoundError: No module named 're2'`.
- **Fix.** `router_spec.RegexRule` imports `compile_regex` inside its validator, and
  `router_keywords` imports `re2_head` and `compile_regex` inside `keyword_labels` and the cached
  `_compiled`. Reading a world file, its routing profiles included, and importing or running the
  Router steps for a fixed, scoring or llm selector no longer load RE2. The Engine server still
  imports RE2 at startup through the combine operators, as on `main`.
- **Fail closed.** Without RE2, a regex rule's validator raises `ModuleNotFoundError`, which
  pydantic does not turn into a validation error, so the definition is neither admitted nor
  refused as invalid. ADMIT raises before its preflight read: no Gateway request, no provider
  call and no C5 record. With RE2 installed, C2 still compiles every rule, and KEYWORDS keeps its
  RE2 semantics, its first 65,536-character window, its declared rule order (the first match
  unless `multi`) and its per-pattern cache.
- **Tests.** `test_router_optional_re2.py`. A fresh interpreter with `re2` blocked reads a world
  file with a fixed and a dynamic profile (the same revisions as with RE2), reads fixed, scoring
  and llm envelopes, imports every Router step module without loading `extract`, and does not
  admit a regex envelope. In process with `re2` blocked, ADMIT of a regex Router raises before any
  read, a regex block on the url4 executor calls nothing and records nothing, and fixed, scoring
  and llm blocks still answer with one record. With RE2, a lookahead, backreference or lookbehind
  rule (each compiles under Python `re`) is refused at C2, `$` and `\d` match as RE2 does, and the
  window, the order and the compile-once cache hold.

### Risks added by the RE2 fix

- Without RE2, a regex Router fails as an Engine fault (the missing module), not as a C4
  refusal. The Engine declares `google-re2` and its server imports it at startup, so only a
  process that never starts the Engine server can reach this.

## Correction round: C7 parity, provenance lifetime, shared vocabulary (2026-11-27)

Status: DONE (uncommitted, on `9d8a32d03`). Each behavior change below started as a failing
test.

- **C7 labels.** The Engine label rule refused only Unicode `Cc` and `Cs`. The Gateway
  (`core/classification_input.is_label`) and the SDK (`recipe._name`) refuse every category
  starting with `C`, so the Engine accepted labels such as U+200B, U+E000 and U+0378 that
  they refuse. Planned: the same whole-`C` rule, nonempty, at most 64 UTF-8 bytes.
- **C7 limits.** `classifier_limits.read_capability` accepted any integer limit up to
  2,147,483,647 and did not require `max_labels >= max_options`. Planned: a choice row takes
  the C7 choice ranges (`max_options` 1-32, `max_labels` from `max_options` to 32,
  `max_label_bytes` 1-64, `max_description_chars` 1-1024, `max_instructions_chars` 1-4096,
  `max_text_chars` 1-2,147,483,647). A text row keeps its three keys in 1-2,147,483,647.
- **Provenance lifetime.** A child task inherits the capture scope's provenance channel. After
  the scope exits it could still append facts, outcomes, step documents and claims. Planned: a
  scope closes its channel on exit. A context whose own scope has closed then reads and writes
  as outside every scope.
- **Dependency direction.** Planned: `Outcome` moves to `router_vocabulary`, so the pure policy
  does not import the completed-record codec. `operation_calls` imports `RouterDecision` for
  type checking only.
- **Typed step payloads.** ADMIT and DECIDE record their typed result beside the canonical
  document. A later step checks canonical equality first, then returns the recorded object
  instead of re-reading the document. Planned removals: the process-wide `_parsed` spec cache,
  `read_admit`'s re-validation and `AdmittedSpec.definition_json`. The draft's `policy` comes
  from the frozen typed definition.
- **One vocabulary.** Planned:
  - one strict base model;
  - one router-binding and revision rule;
  - one `REVISION_SCHEME` and `SCORES_CONTRACT`;
  - one selector-evidence rule for the C5 record and the C6 policy;
  - one draft decode.
- **KEYWORDS in DECIDE.** `world/router_keywords.py` moves into `world/router_decide.py`, its
  only caller, with the same window, order, cache and function-local RE2 imports.
- **Prior tests.** Operator-approved edits to five files, each pinned by its base and approved
  blob in `.claude/test-change-approvals/OME-2044.json`; any other edit fails the append-only
  check again:
  - `test_classifier_limits.py`: the boundary test's choice `max_labels` goes from 2,147,483,647
    to 32, the C7 maximum. The over-limit `labels` case sets `max_options` 2 with `max_labels` 2,
    so it still tests an input with more labels than allowed, not a row the relation refuses;
  - `test_routing_core_targets.py`: `_choice_keys` sets `max_options` 3. The text keys it is
    combined with set `max_labels` 3, so 4 options would break `max_options <= max_labels`;
  - `test_router_optional_re2.py` and `test_operation_provenance.py`: the import path and
    docstring move to `router_decide`;
  - `test_router_spec.py`: the `definition_json` assertion becomes an assertion on the typed
    definition's JSON dump.

### Correction round results

- **Drift found while sharing the selector rule.** The C6 policy accepted selector readings the
  C5 record refuses: `unparsed` with labels or unknown tokens, a repeated unknown token,
  `unrecognized` without an unknown token, regex `unparsed` or `unrecognized`, llm `no_match`.
  DECIDE reached `router_evidence_invalid` for them only through a codec error in `_draft`. Now
  `selector_rule` decides both.
- **Typed payloads.** One Router occurrence validates its spec once and its draft once (fixed
  with default, choice, llm, regex). The document path stays for a context that is not proven
  and for a step recorded without a value; canonical equality still comes first.
- **Provenance lifetime.** A scope marks its channel ended on exit. Every reader and writer cuts
  the channel stack at the innermost ended scope, so a late task sees only scopes it opened
  itself.
- **New tests** (`tests/unit/`): `test_router_c7_parity.py`, `test_provenance_lifetime.py`,
  `test_router_dependency_direction.py`, `test_router_typed_payloads.py`,
  `test_router_shared_vocabulary.py`.
- **Changed source:** `operation_calls.py`, `operation_provenance.py`, `router_decision.py`,
  `router_vocabulary.py`, `world/classifier_limits.py`, `world/router_admit.py`,
  `world/router_decide.py`, `world/router_join.py`, `world/router_provenance.py`,
  `world/router_spec.py`, `world/router_steps.py`, `world/routing_policy.py`; removed
  `world/router_keywords.py`. Largest file `router_decision.py`, 451 lines, one over the
  450-line limit (trimmed in the review fix below).
- **Delta against `9d8a32d03`:** production 13 files, +353/-236 physical lines (+117 net), one
  file fewer. By line kind: code +56 (2,391 to 2,447), docstrings +48, comments +7, blank +6.
  Prior tests 5 files, +7/-7. New tests 697 lines. The removals (spec duplicates, the
  `_parsed` cache, `AdmittedSpec`, `definition_json`, `router_keywords`) are smaller than the
  added C7 bounds, scope lifetime, shared selector rule and typed-payload lookup, because the
  document path must stay beside the typed value.
- **Gates (2026-11-27):**
  - Python 3.13: `run_gates.py screamingface-engine` ALL GATES GREEN; the append-only check
    passes through the three OME-2044 transitions it inspects. The two import-only edits are
    pinned in the manifest too.
  - Python 3.12.9: ruff check, ruff format, pyright 0 errors, layering OK, full suite
    13105 passed / 577 skipped, coverage 96.52%.
  - `run_gates.py repo`: ALL GATES GREEN; `git diff --check` clean.
  - SDK, installed without RE2, Python 3.13.11 and 3.12.9: 8624 passed / 54 skipped each,
    coverage 97.01%.
- **Mutation controls,** each restored byte-exact: 82 of 83 killed. That is the 59 earlier
  controls plus C7 labels and limits (8 of 9), scope lifetime (4), typed payloads (5), shared
  selector rule, unknown-token rule, candidate labels, policy imports, type-only record import
  and draft failure key (6). The survivor sets the choice `max_options` maximum to 33. It is
  equivalent: `max_options <= max_labels <= 32` already bounds it. A sixth typed-payload control
  showed a redundant scope check in the typed lookup; that check was removed instead.
- **Known warning:** the changed `test_router_spec.py` assertion dumps a typed choice definition,
  and Pydantic warns that the candidate union's callable discriminator returned no tag for a
  model instance (it reads only dicts). The dump is still correct. No production path dumps a
  candidate or classifier union; the draft dumps only `policy`.

## Review fix: recorder lifetime, score rows, file size (2026-11-27)

Status: DONE (uncommitted, on `9d8a32d03`). Each behavior change below started as a failing
test.

- **Recorder lifetime.** The correction round ended the provenance channel with its scope, but
  not the operation-call recorder opened beside it. A task that outlived its scope still read the
  scope's calls and published into it and into every enclosing scope. A late ADMIT saw a
  recorder, so it passed the `router_unsupported` check and ran the preflight and the run-file
  check. A late JOIN published its record into recorders that had already been returned. Now a
  recorder ends with its scope. `current_operation_calls`, `latest_operation_call` and every
  publication cut the recorder stack at the innermost ended scope, by the same `live_scopes`
  rule as the channel. A late ADMIT refuses `router_unsupported` before any read, call or file
  check. A late JOIN or call record reaches no recorder. A scope the late task opens itself,
  nested or isolated, records its own calls only.
- **Score rows.** DECIDE checked only the keys of each score row. A list or object label raised
  `TypeError` in the policy, and an integer score beyond the float range raised `OverflowError`.
  Now every row is validated as the C5 `ScoreRow` before the policy runs. A malformed label or a
  non-genuine or non-finite score is invalid evidence: a permanent `router_evidence_invalid`
  draft. The policy is unchanged.
- **File size.** `router_decision.py` was 451 lines. Its strict-JSON decode and model validation
  are one `_read` again, which still decodes a draft once. The file is now 441 lines.
- **C7 test wording.** `test_router_c7_parity.py` said the SDK holds the full label rule. The SDK's
  recipe-name rule refuses the `C` categories but has no byte bound; the full rule, with the
  64-byte bound, is the Gateway's. The module docstring now says so. No assertion changed.
- **Not changed:** the five prior-test edits and their manifest entries. The run-wide request
  accounting recorders are a separate ledger and stay as they are.

### Review fix results

- **New tests,** added to the correction round's new test files only:
  - `test_provenance_lifetime.py`: a late child reads no call and publishes none (nested,
    isolated); a late ADMIT refuses with no Gateway call and no file check; a late JOIN on a
    carried refusal publishes into neither scope; a scope a late child opens records its own
    calls only (nested, isolated).
  - `test_router_shared_vocabulary.py`: nine malformed score rows (list, object, number, empty
    and over-64-byte labels; boolean, string, huge-integer and overflowing-float scores). Each
    gives the same permanent invalid-evidence draft as a score above one.
  - Before the fix, five lifetime cases and three score cases failed. The others already held
    and stay as guards.
- **Changed source:** `operation_provenance.py` (the shared `live_scopes` rule),
  `operation_calls.py`, `world/router_decide.py`, `router_decision.py`.
- **Sizes,** every changed source file counted: the largest are `router_decision.py` 441,
  `operation_calls.py` 418, `world/router_decide.py` 413, `world/router_spec.py` 401 and
  `operation_provenance.py` 350. No file is over 450 lines.
- **Delta against `9d8a32d03`:** production 13 files, +406/-262 physical lines (+144 net), one
  file fewer. By line kind (a docstring is a string expression statement, a comment line holds
  only a comment): code +67 (2,391 to 2,458), docstrings +57, comments +6, blank +14. This fix
  alone: +27 net (code +11, docstrings +9, comments -1, blank +8). Prior tests 5 files, +7/-7,
  unchanged by this fix. New tests 901 lines (+204).
- **Gates (2026-11-27):**
  - Python 3.13.11, in an environment without the `inspect` extra (as the CI pyright lane, which
    runs after `uv sync --dev`): `run_gates.py screamingface-engine` ALL GATES GREEN; the
    append-only check passes through the three OME-2044 transitions it inspects. Direct unit
    run: 13068 passed / 530 skipped.
  - In an environment with the `inspect` extra installed, `uv run pyright` reports 17 errors in
    seven `tests/unit/inspect` files. A clean `9d8a32d03` copy gives the same 17 in that
    environment, so they come from the installed extra, not from this change.
  - The `tests/unit/inspect` suites with the extra, as the CI inspect lane runs them: 3862
    passed, 2 failed. Both failures are the `enigmaeval` catalogue row (its answer format and its
    draft-feedback page), and both fail the same way on a clean `9d8a32d03` copy.
  - Python 3.12.9: ruff check, ruff format, pyright 0 errors, layering OK, full suite
    13120 passed / 577 skipped, coverage 96.53%.
  - `run_gates.py repo`: ALL GATES GREEN; `git diff --check` clean.
  - SDK, installed without RE2, Python 3.13.11 and 3.12.9: 8624 passed / 54 skipped each,
    coverage 97.01%.
- **Mutation controls,** each restored byte-exact: 89 of 90 killed. That is the 83 earlier
  controls, with the two lifetime-cut controls re-anchored on `live_scopes`, plus recorder end,
  recorder cut, current and latest reads and publication (5), and score-row validation and row
  type (2). The survivor is the equivalent choice `max_options` maximum described above.

## Parameter schema parity (2026-11-27)

Status: DONE (uncommitted, on `9d8a32d03`). The behavior change started as failing tests.

- **Finding.** The Engine's parameter-row reader (`world/parameter_contract.py`) accepted two
  kinds of row that the Gateway never publishes (`ParameterSchema`) and the SDK's discovery
  reader refuses. One kind put `pattern` or `maxLength` on a schema whose top-level type holds
  no `string`, so the constraint could never fire. The other had a pattern without both `^` and
  `$` anchors. A Router Model with such a row passed the ADMIT preflight, so a paid call could
  follow.
- **Fix.** `_constraints_readable` now receives the schema's type names. A `pattern` or
  `maxLength` needs `string` among the top-level types; an item type does not count. A pattern
  must be a string anchored with `^` and `$` that compiles (`_pattern_readable`, which replaces
  `_compiles`). Any other row is unreadable, so the value misfits. ADMIT then refuses
  `routing_profile_mismatch` before any provider call. A `null` constraint stays absent, as in
  the Gateway and the SDK. Valid string and mixed string-capable schemas behave as before.
- **Not changed:**
  - The fixed routing profile's own `max_tokens` check (`routing_core._admits`) reads type and
    bounds only, as shipped.
  - The SDK alone also refuses duplicate type names and `minimum` above `maximum`. The Gateway
    does neither, and the Engine follows the Gateway there.
  - The Gateway, the SDK, the prior tests and their manifest.

### Parameter schema parity results

- **New tests,** in `test_router_c7_parity.py` only (35 cases):
  - `pattern` and `maxLength` each on `integer`, `number`, `boolean`, `array` and `object`.
    Each value fits the same schema without the constraint.
  - A type list without `string`, and `string` items on an array.
  - Unanchored patterns, and patterns missing the start or the end anchor.
  - A pattern that is a number, a list or an anchored broken regex. A `maxLength` that is a
    boolean or zero.
  - Kept behavior: anchored match and miss, `maxLength` at and past its bound, mixed
    `string`/`array` schemas, and `null` constraints.
  - ADMIT with a malformed row on a candidate Model refuses `routing_profile_mismatch` with no
    POST: unanchored, pattern a number, pattern on an integer, `maxLength` on an array, pattern
    on an object. A mixed string-capable row is admitted.
  - Before the fix, 20 cases failed: every non-string-type, unanchored and type-list case, and
    four ADMIT cases. The others already held and stay as guards.
- **Changed source:** `world/parameter_contract.py`, 154 lines.
- **Delta against `9d8a32d03`:** production 14 files, +423/-267 physical lines (+156 net), one
  file fewer. By line kind: code +68 (2,479 to 2,547 over these 14 files), docstrings +68,
  comments +6, blank +14. This fix alone: +12 net (code +1, docstrings +11). Prior tests 5
  files, +7/-7, unchanged. New tests 1,044 lines (+143).
- **Gates (2026-11-27):**
  - Python 3.13.11, without the `inspect` extra: `run_gates.py screamingface-engine` ALL GATES
    GREEN, with the append-only check through the three OME-2044 transitions. Direct unit run:
    13103 passed / 530 skipped.
  - Python 3.12.9: ruff check, ruff format, pyright 0 errors, layering OK, full suite
    13155 passed / 577 skipped, coverage 96.53%.
  - `run_gates.py repo`: ALL GATES GREEN; `git diff --check` clean.
  - SDK, installed without RE2, Python 3.13.11 and 3.12.9: 8624 passed / 54 skipped each,
    coverage 97.01%.
- **Mutation controls,** each restored byte-exact: 8 of 8 killed.
  - The permissive reader restored.
  - Text constraints allowed on any type.
  - No anchor check; only the start anchor; only the end anchor; an anchor check that always
    passes.
  - The type rule guarding only `pattern`, or only `maxLength`.

## Parameter schema vocabulary (2026-11-27)

Status: DONE (uncommitted, on `9d8a32d03`). The behavior change started as failing tests.

- **Finding.** The Engine still read rows outside what the Gateway publishes and the SDK decodes:
  - enum members that are not strings, so `True == 1` let a value of another type pass;
  - blank, padded or repeated enum members;
  - an `array` item type;
  - repeated type names, and `minimum` above `maximum`;
  - a bound that is an integer too large for a float, which raised `OverflowError` out of ADMIT
    instead of a refusal.

  A Router whose candidate row had `{"type": "integer", "enum": [true]}` ran its paid chat call.
- **Fix,** in `world/parameter_contract.py`. The Engine now reads only the strict intersection of
  the two readers:
  - `_kinds` refuses a repeated type name.
  - Bounds must be numbers a float holds, with `minimum <= maximum`; `_number` turns an
    `OverflowError` into an unreadable row.
  - An enum is a list of distinct non-blank strings without surrounding blanks (`_enum_readable`).
    The SDK strips a member and the Gateway does not, so a padded member would name a different
    value to each.
  - An item type is one known name other than `array` (`_item_kind`).

  The `pattern`/`maxLength` rule is unchanged. This supersedes the earlier note that the Engine
  follows the Gateway on repeated type names and inverted bounds. That note also missed blank and
  repeated enum members, which the SDK refuses too.
- **Kept:**
  - Every real Gateway schema still fits. All 20 distinct `ParameterSchema` objects the Gateway
    builds at import were rendered, given a fitting value, and read by the Gateway, the SDK and the
    Engine, and all three admit the value.
  - An empty enum still admits no value, so it needs no rule of its own.
  - The fixed routing profile's `max_tokens` check is unchanged.
- **Not changed:** the Gateway, the SDK, the prior tests and their manifest. The SDK's own decoder
  raises a bare `OverflowError` for such a bound, outside its `TypeError`/`ValueError` handling.
  That is noted here only.

### Parameter schema vocabulary results

- **New tests,** in `test_router_c7_parity.py` only (25 cases):
  - 15 rows outside the shared vocabulary. Each misfits at `value_fits`, and ADMIT refuses it
    `routing_profile_mismatch` with no POST.
  - 7 published shapes, kept. Each fits, and ADMIT accepts it.
  - 3 full Router runs over a malformed row. Each ends with `routing_profile_mismatch`, with no
    classifier or chat POST and no provider call.
  - Before the fix, 17 cases failed. Three crashed with `OverflowError` (one through the run's task
    group); the full runs reached a paid chat answer. The empty enum already held.
- **Changed source:** `world/parameter_contract.py`, 180 lines.
- **Delta against `9d8a32d03`:** production 14 files, +462/-280 physical lines (+182 net), one
  file fewer. By line kind: code +79 (2,479 to 2,558), docstrings +79, comments +6, blank +18.
  This fix alone: +26 net (code +11, docstrings +11, blank +4). Prior tests 5 files, +7/-7,
  unchanged. New tests 1,145 lines (+101).
- **Mutation controls,** each restored byte-exact: 10 of 10 killed.
  - enum: any list; members of any type; an empty member; a padded member; repeated members.
  - Items: `array` allowed.
  - Types: repeated names.
  - Bounds: inverted allowed; a huge integer readable; no overflow guard.

  The 8 text-constraint controls were re-run, and all 8 are still killed.

## Parameter schema semantics (2026-11-27)

Status: DONE (uncommitted, on `9d8a32d03`). The behavior change started as failing tests.

- **Finding.** Three gaps were still open after the vocabulary fix.
  - **Bounds compared as exact integers.** The Gateway and the SDK both turn a bound into a float
    and compare the sent value with that float. The Engine compared the value with the exact
    integer instead. With `maximum: 2**53 + 1`, both readers hold the bound as `2**53` and refuse
    `2**53 + 1`, but the Engine admitted it, and a Router run went on to make its classifier and
    chat calls. The same drift changed the decision for other values next to `2**53`. It also
    made `minimum: 2**53 + 1, maximum: 2**53` read as inverted, although both readers see two
    equal bounds.
  - **Unknown keys were ignored.** `{"type": "integer", "exclusiveMaximum": 1}` admitted `999`,
    and an item schema's `maxLength` was skipped. The Gateway model forbids any key it does not
    render; the SDK skips one.
  - **Regex compiler failures escaped.** Two patterns made the compiler raise out of
    `value_fits` and out of a Router run:
    - a pattern nested past the compiler's recursion limit raised `RecursionError`;
    - a repetition count past the compiler's limit (`^a{4294967296}$`) raised `OverflowError`.
- **Fix,** in `world/parameter_contract.py`:
  - **Bounds.** `_bound` reads a bound as the finite float both readers hold. `_in_bounds` and
    the `minimum <= maximum` check compare with that float. A bound no float holds is still
    unreadable.
  - **Keys.** The schema's keys must be ones the Gateway renders (`_SCHEMA_KEYS`). An item schema
    holds `type` alone (`_items_readable`).
  - **Patterns.** `_pattern_readable` treats a `RecursionError` or an `OverflowError` from the
    compiler as an unreadable pattern.
- **Empty enum.** Both readers accept an empty enum, and no value fits it. Its case therefore moved
  out of the rows outside the vocabulary and into a value-level test. That test asserts that the
  row is readable and that the value misfits, separately.
- **Test layout.** The parameter-schema tests moved, unchanged, from `test_router_c7_parity.py`
  into a new `test_router_parameter_parity.py`, which also holds the new cases. The C7 file keeps
  its labels and classifier rows. Without the move it would have grown past 450 lines.
- **Kept:**
  - all 20 real Gateway schemas still fit;
  - the fixed profile's `max_tokens` check;
  - every earlier rule.
- **Not changed:** the Gateway, the SDK, the prior tests and their manifest.
- **Noted only:** for the same patterns, the Gateway model and the SDK decoder raise a bare
  `RecursionError` or `OverflowError`. In the SDK decoder these get past its
  `TypeError`/`ValueError` handling.

### Parameter schema semantics results

- **Tests,** in `test_router_parameter_parity.py`:
  - **Rows outside the vocabulary:** 3 more cases, an unknown key, an item key, and a repetition
    count past the limit. The empty enum moved out of this group.
  - **5 value-level cases:** bounds held as floats next to `2**53`, bounds equal as floats, and
    the empty enum. Each asserts readability, `value_fits`, the ADMIT outcome, and no POST.
  - **3 non-finite bound cases** (`Infinity` maximum, `-Infinity` minimum, `NaN` maximum). Each
    is unreadable and misfits. This guards an earlier rule that no test covered; a
    strict-JSON transport cannot carry such a number, so the cases stop before ADMIT.
  - **4 full Router runs:** a maximum held as `2**53`, a pattern nested too deep, an unknown key,
    and the empty enum. Each ends with `routing_profile_mismatch`, with no classifier or chat POST
    and no provider call.
  - **Before the fix, 9 cases failed:**
    - Unknown keys fitted.
    - The repetition count raised `OverflowError`.
    - Values next to `2**53` were decided against the exact integer.
    - The full run over `2**53 + 1` reached a paid chat answer.
    - The deep pattern raised `RecursionError` through the run's task group.

    The empty enum already held.
- **Three-reader vectors:** 655 in total, 75 structural and 580 value-level. Before the fix, 58
  cases differed from the Gateway-and-SDK intersection; after it, none differ. One family is the
  stricter Engine rule on a padded enum member, and there the value outcome still matches.
- **Changed source:** `world/parameter_contract.py`, 197 lines.
- **Delta against `9d8a32d03`:**
  - production: 14 files, +487/-288 physical lines (+199 net), one file fewer. By line kind:
    code +85 (2,479 to 2,564), docstrings +90, comments +6, blank +18;
  - this fix alone: +17 net in `parameter_contract.py` (code +6, docstrings +11);
  - prior tests: 5 files, +7/-7, unchanged;
  - new tests: 6 files, 1,210 lines. `test_router_c7_parity.py` is 182 lines and
    `test_router_parameter_parity.py` is 309.
- **Mutation controls,** each restored byte-exact: 11 of 11 killed.
  - Bounds: compared with the raw bound; inverted check on the raw bounds; inverted allowed;
    a huge integer read as a bound; no overflow guard; a non-finite bound read.
  - Keys: unknown top-level keys allowed; an item schema holding other keys.
  - Patterns: `RecursionError` escapes; `OverflowError` escapes.
  - Enum: an empty enum made unreadable.

  The earlier controls were re-run on this code: the enum, item and type-name controls, 7 of
  7 killed, and the text-constraint controls, 8 of 8 killed.

## Outcome (fill at the end — required before COMMIT)

- **Actual files** (all under `apps/screamingface-engine/`):
  - New source: `operation_provenance.py`, `router_record_parts.py`, `router_decision.py`,
    `router_vocabulary.py`, `catalog/classifiers.py`, `world/router_keywords.py`,
    `world/router_provenance.py`,
    `world/attempt_facts.py`, `world/classifier_limits.py`, `world/parameter_contract.py`,
    `world/router_admit.py`, `world/router_decide.py`, `world/router_evidence.py`,
    `world/router_join.py`, `world/router_spec.py`, `world/router_steps.py`,
    `world/routing_core.py`, `world/routing_policy.py`.
  - Modified source: `app.py`, `local.py`, `error_text.py`, `operation_calls.py`,
    `combine/ports.py`, `catalog/aigateway.py`, `catalog/executable.py`, `catalog/port.py`,
    `rest/catalog.py`, `world/classification.py`, `world/connector.py`, `world/factory.py`,
    `world/gateway_endpoints.py`, `world/gateway_transport.py`, `world/routing.py`,
    `world/routing_config.py`.
  - New tests (`tests/unit/`): `router_support.py`, `router_decision_support.py`,
    `router_block_support.py`, `router_join_support.py`, `classifier_catalog_support.py`,
    `test_operation_provenance.py`, `test_router_provenance.py`,
    `test_router_runtime_provenance.py`, `test_router_decision_matrix.py`, `test_router_open.py`,
    `test_router_subset.py`,
    `test_attempt_facts_direct.py`, `test_attempt_observer.py`, `test_classifier_catalog.py`,
    `test_classifier_limits.py`, `test_parameter_contract.py`, `test_router_admit.py`,
    `test_router_classify.py`, `test_router_codes.py`, `test_router_decide.py`,
    `test_router_decision.py`, `test_router_decision_record.py`, `test_router_evidence.py`,
    `test_router_join.py`, `test_router_preflight.py`, `test_router_record_call.py`,
    `test_router_runtime.py`, `test_router_spec.py`, `test_routing_core_targets.py`,
    `test_routing_dynamic_config.py`, `test_routing_dynamic_endpoint.py`,
    `test_routing_policy.py`. No prior test changed (append-only check green).
- **Commits:** `341cd384b` (`feat(screamingface-engine): add shared routing core`); the RE2
  fix is uncommitted on top of it.
- **Gates (2026-11-26, worktree on `4efb34bc6`):**
  - Python 3.13: `run_gates.py screamingface-engine` ALL GATES GREEN (append-only, ruff check,
    ruff format, pyright, layering, full suite with coverage >= 80%).
  - Python 3.12 (separate venv, 3.12.9): ruff check, ruff format, pyright 0 errors, layering OK,
    full suite 12807 passed / 577 skipped, coverage 96.49%.
  - `run_gates.py repo`: ALL GATES GREEN.
  - The url4 allowlist (`test_url4_executor.py`), the url4 private-import ratchet and the Engine
    CI path-guard tests (`test_engine_ci_*`) run inside the full suite; the ratchet caught one
    private url4 import in a new test, replaced by a spec mirror.
  - Mutation controls, each restored byte-exact, 11/11 killed: ADMIT recorder-scope refusal,
    `select=all` refusal, fact-first row reading, error shape before the fact (spoof order),
    provider stage of the parameter contract, `bounded_code`, classify control-plane re-raise,
    run-file await, JOIN unchosen-branch check, structured-row conversion, a classifier failure
    never opens the default.
- **Fix iteration gates (2026-11-26, same base; current main `35efe84ac` changes only docs and
  `e2e/reference`, with no path in common with the candidate):**
  - Python 3.13: `run_gates.py screamingface-engine` ALL GATES GREEN; full suite
    12963 passed / 576 skipped.
  - Python 3.12.9: ruff check, ruff format, pyright 0 errors, layering OK, full suite
    12962 passed / 577 skipped, coverage 96.51%.
  - `run_gates.py repo`: ALL GATES GREEN.
  - Mutation controls, each restored byte-exact, 38/38 killed: step and outcome single
    assignment, ambiguity, outcome recording (answered, failed, cancelled, the connector
    boundary), `first_run`, recorded ADMIT/draft, scores (document, fact, empty output, route),
    rows (cancelled, Model, fact, reply, recorded bytes, failure, failed attempt), url4 row
    re-encoding, KEYWORDS recompute, classifier fact in JOIN, subset refusal in OPEN and JOIN,
    Model-synthesizer preflight, the failed classify operation and its outcomes, `limits: null`,
    canonical IDs, unhashable IDs, strict catalog JSON, C6 reason, classifier binding, answered
    branch, failed branch code.
  - All new files are at most 450 lines; `connector.py` gains only the outcome wrapper.
- **Second fix iteration gates (2026-11-26, same base; `origin/main` still has no path in common
  with the candidate):**
  - Python 3.13: `run_gates.py screamingface-engine` ALL GATES GREEN; full suite
    13015 passed / 576 skipped.
  - Python 3.12.9: ruff check, ruff format, pyright 0 errors, layering OK, full suite
    13014 passed / 577 skipped, coverage 96.51%.
  - `run_gates.py repo`: ALL GATES GREEN; `git diff --check` clean.
  - Mutation controls, each restored byte-exact, 49/49 killed: the 38 earlier controls plus claim
    refusal, claim kept, the ADMIT, CLASSIFY and JOIN claims, failed outcome before any branch,
    call binding without evidence, the policy naming the classifier, a null call without evidence,
    the closed support vocabulary and its type check.
  - New files: `tests/unit/test_router_replay.py`, `tests/unit/test_router_record_failures.py`.
    Changed candidate files: `operation_provenance.py`, `router_decision.py`,
    `world/router_provenance.py`, `world/router_admit.py`, `world/router_join.py`,
    `world/parameter_contract.py`, `tests/unit/test_operation_provenance.py`,
    `tests/unit/test_parameter_contract.py`.
- **RE2 fix gates (2026-11-26, on `341cd384b`; `origin/main` is still `35efe84ac`):**
  - SDK, installed as its test lane installs it (`uv sync --frozen --extra notebook`, no RE2),
    Python 3.13.11 and 3.12.9: the twelve failing runtime tests pass, and so does the full SDK
    suite (its typing tests read the package's own `.venv`, so that path named the same
    environment for them).
  - Python 3.13, in an environment synced from the lock without extras: `run_gates.py
    screamingface-engine` ALL GATES GREEN; full suite 13029 passed / 576 skipped.
  - Python 3.12.9: ruff check, ruff format, pyright 0 errors, layering OK, full suite
    13028 passed / 577 skipped, coverage 96.52%.
  - `run_gates.py repo`: ALL GATES GREEN.
  - Mutation controls, each restored byte-exact, 10/10 killed: a module-level RE2 import in
    `router_spec` and in `router_keywords`, a missing RE2 admitted, a missing RE2 refused as an
    invalid definition, C2 without the RE2 compile, KEYWORDS without its cache, with Python `re`,
    without its window, with the last match, and in reversed rule order.
  - Changed: `world/router_spec.py`, `world/router_keywords.py`; new
    `tests/unit/test_router_optional_re2.py`.
- **Deviations:** the runtime is five `router_*` modules plus `install_router_runtime`, not one
  `world/router_runtime.py`; C17 lives in `catalog/classifiers.py` served by `rest/catalog.py`,
  not a new `rest/classifiers.py`; the C5 codec is the leaf `router_decision.py`.
