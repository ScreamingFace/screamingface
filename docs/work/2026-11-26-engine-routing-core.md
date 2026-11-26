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
- **Commits:** none yet; the candidate is uncommitted.
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
- **Deviations:** the runtime is five `router_*` modules plus `install_router_runtime`, not one
  `world/router_runtime.py`; C17 lives in `catalog/classifiers.py` served by `rest/catalog.py`,
  not a new `rest/classifiers.py`; the C5 codec is the leaf `router_decision.py`.
