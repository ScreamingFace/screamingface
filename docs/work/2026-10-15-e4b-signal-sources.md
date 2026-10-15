---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: repo, aigateway, screamingface-engine, screamingface
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-15
finished:
---

# e4b-signal-sources — E4b part 3, signal sources v1

One ledger for the whole part. The plan is
[docs/plan/2026-10-15-e4b-signal-sources.md](../plan/2026-10-15-e4b-signal-sources.md). The spec is
[docs/spec/2026-10-15-e4b-signal-sources/](../spec/2026-10-15-e4b-signal-sources/00-overview.md).
Each unit has its own section below.

## Unit 1 — characterize the gateway

### Intent

Record the two gateway answers that the logprob parser (C3) and the refusal mapping (C4) use, before
any product code. Make a small number of live calls to the local aigateway (cost cap: 10 calls,
`max_tokens` ≤ 64, `top_logprobs` ≤ 5, one synthetic prompt, total < 0.05 USD). Pick the pinned
model for RC#8 and a refusing model for RC#9. Decide the D1 branch. If the refusal is not distinct
(LC-E5), give it the aigateway code `unsupported_parameters` (C4b, LC#20).

### Planned changes

- `apps/screamingface-engine/tests/unit/data/logprobs/*.json`: the trimmed reply with `logprobs` and
  `top_logprobs`, and the refusal answer with its status.
- LC-E5 branch only: `apps/aigateway/src/aigateway/plugins/openrouter_provider/` (a detector for the
  OpenRouter parameter refusal and a gateway-authored error), and a new aigateway unit test.
- This ledger.

### Test plan

- LC-E5 branch only (LC#20, aigateway half): a new test file. A transport 404 from OpenRouter with
  the parameter-refusal text gives `404` with `detail.code == "unsupported_parameters"`, gateway
  text only, no provider text. Other 404 refusals (`max_price`, data policy, unknown model) keep
  `provider_error`. The embedded HTTP-200 shape keeps today's mapping. RED first.

### Acceptance

- The fixtures exist, have no id, `_aigw`, provider, model or header, and the token text is
  synthetic.
- The ledger names the pinned model, the refusing model, the refusal status and code, the D1
  branch, the number of live calls and the total cost.
- The repo gate is green (and the aigateway gate on the LC-E5 branch).

### Unit 1 note — the recorded gateway answers (2026-10-15)

Local stack: aigateway at `127.0.0.1:9105` (`~/sf-local`), OpenRouter. All calls used `curl` to
`POST /v1/chat/completions`, the prompt "What is 2+3? Reply with the number only.",
`max_tokens: 16`.

| # | Model | Body extras | Gateway | Cost (`_aigw` direct_cost) |
|---|---|---|---|---|
| 1 | `openrouter/openai/gpt-4o-mini` | `logprobs: true`, `top_logprobs: 5` | 200, one token, five top entries | 0.0000036 |
| 2 | `openrouter/anthropic/claude-haiku-4.5` | `logprobs: true`, `top_logprobs: 5` | 404 `provider_error` "The upstream provider returned an error." | none (refused) |
| 3 | `openrouter/anthropic/claude-haiku-4.5` | none (control) | 200 | 0.000045 |
| 4 | `openrouter/anthropic/claude-haiku-4.5` | `logprobs: true`, `top_logprobs: 5` | 404 `unsupported_parameters` (temporary gateway from this worktree, port 9115, on a copy of the local database; stopped and deleted after the call) | none (refused) |

- **Live calls:** 4 (cap 10). **Total cost:** 0.0000486 USD (cap 0.05).
- **Pinned model (RC#8):** `openrouter/openai/gpt-4o-mini`. It returns `logprobs.content[]` with
  `token`, `bytes`, `logprob` and `top_logprobs[]` (5 entries), plus `logprobs.refusal: null`. The
  one token had `logprob: 0.0`, so the parser must accept 0 (the C3 rule "finite and ≤ 0").
- **Refusing model (RC#9):** `openrouter/anthropic/claude-haiku-4.5`. The gateway catalog
  (`GET /v1/model-parameters`) marks `logprobs` and `top_logprobs` as `supported`
  (source `openrouter:static`), so the SDK preflight (LC-E4) does not stop it and the runtime path
  runs. Call 3 shows that the refusal comes from `logprobs`.
- **Refusal before LC-E5:** HTTP 404, `detail.code = "provider_error"`, text "The upstream provider
  returned an error.". The accounting attempt shows a transport failure
  (`failure_code: provider_status_error`), so the plugin re-raised a litellm `NotFoundError`.
- **D1 branch: LC-E5 (NOT distinct).** The route maps every upstream 404 to `provider_error`
  (`G/routes/chat_dispatch.py`, `_provider_error_code`). The same status and code also mean a
  `max_price` refusal, a zero-data-retention or data-policy refusal and a missing upstream model
  (pinned in `test_openrouter_routing_policy_routes.py` and
  `test_openrouter_no_eligible_endpoint.py`). Thus the engine cannot read it as a logprobs refusal.
- **LC-E5 change:** the OpenRouter plugin gives the transport 404 parameter refusal the code
  `unsupported_parameters` (status 404, gateway text "No upstream endpoint for this model supports
  every requested parameter.", not retried). Call 4 shows that the detector matches the live
  refusal. Unit 3 maps `unsupported_parameters` (with `logprobs: true` in the body) to
  `logprobs_unsupported` (the engine half of LC#20).
- **Fixtures** (`apps/screamingface-engine/tests/unit/data/logprobs/`), each `{"status", "body"}`:
  - `openrouter_reply_with_logprobs.json`: call 1. Content is `SYNTHETIC-ANSWER`; tokens are
    `tok0`, `tok0_alt1`..`tok0_alt4` (the `bytes` match the new text); the numbers, `finish_reason`
    and the token counts in `usage` are as recorded.
  - `openrouter_refusal_provider_error.json`: call 2, the answer before LC-E5.
  - `openrouter_refusal_unsupported_parameters.json`: call 4, the answer after LC-E5.
  - Removed: `id`, `_aigw`, `provider`, `system_fingerprint`, `created`, `model`, `object`,
    `service_tier`, `choices[].index`, `choices[].provider_specific_fields`, `message.role`,
    `message.tool_calls`, `message.function_call`, `message.provider_specific_fields`,
    `usage.is_byok`, `usage.cost`, `usage.cost_details` (removed by the review fixes), and every
    header. No provider text is in the refusal bodies.

### Unit 1 outcome

- **Actual files:** as planned. aigateway: `G/plugins/openrouter_provider/response_errors.py`
  (`is_parameter_refusal`, the detector), `G/plugins/openrouter_provider/dispatch_errors.py`
  (`_unsupported_parameters_error`, gateway text only), `G/plugins/openrouter_provider/plugin.py`
  (the transport branch of `chat_completion`), new test
  `apps/aigateway/tests/unit/openrouter/test_openrouter_parameter_refusal_code.py` (9 cases: two
  phrasings get the new code and one upstream call; five other 404 texts, a 400 with the same
  words and the embedded HTTP-200 shape keep their mapping). Engine: the three fixtures. This
  ledger.
- **RED:** the two new-code cases failed (`provider_error` != `unsupported_parameters`); the seven
  "keep the mapping" cases passed before and after (they pin what must not change).
- **Commits:** `feat(aigateway): give the OpenRouter parameter refusal its own code (E4b part 3
  unit 1)`, then `test(screamingface-engine): record the gateway logprobs reply and refusal (E4b
  part 3 unit 1)`.
- **Gates:** `run_gates.py aigateway --base 0f4b9e292` ALL GATES GREEN (append-only, ruff, format,
  pyright, no-enterprise, pytest with coverage ≥ 80). `run_gates.py repo --base 0f4b9e292` ALL
  GATES GREEN.
- **Pinned edits:** none. No existing test changed.
- **Deviations:** (1) Call 4 used a temporary gateway from this worktree (port 9115, on a copy of the
  local database) to prove the detector on the live refusal; the copy was deleted after the call.
  (2) The gateway health path is `/healthz`, not `/health` (`/health` gives 404). (3) The
  embedded HTTP-200 shape of the refusal keeps `provider_error`: an existing test pins it, and the
  live refusal is the transport shape. (4) The exact OpenRouter text is not visible through the
  gateway; the detector matches two fixed phrasings, and call 4 shows that one of them matches.
  The paid test RC#9 (unit 5) checks it again.

### Unit 1 review fixes (2026-10-15)

No live call. The fixes use only the recorded answers.

- **Intent.** Close the review findings for unit 1.
- **Planned changes.**
  - `G/plugins/openrouter_provider/provenance.py`: move `is_parameter_refusal` here from
    `response_errors.py`. It now also requires `classify_provenance(exc) is
    ErrorProvenance.TRANSPORT`, so it is correct without help from its caller.
  - `G/plugins/openrouter_provider/plugin.py`: import from `provenance`; raise the new error
    `from exc` (as the embedded branch above it does), so a server-side traceback keeps the
    litellm exception. The response is gateway text either way.
  - `G/plugins/openrouter_provider/dispatch_errors.py`: the docstring says what a client can do
    with the code, not what the engine does with it.
  - `apps/aigateway/tests/unit/openrouter/test_openrouter_parameter_refusal_code.py`: one local
    `_as_transport(exc, *, wire_status)` helper (the shape of the sibling
    `test_openrouter_no_eligible_endpoint.py`) for the 404 and the 400 cases; a new direct test
    of the detector on a 404 with the refusal text but no transport chain.
  - `ET/data/logprobs/openrouter_reply_with_logprobs.json`: remove `usage.is_byok` (an account
    fact), `usage.cost` and `usage.cost_details` (no later unit reads them).
- **Test plan.** RED first: the new direct test fails before the detector checks provenance.
  The nine existing cases stay green.

### Unit 1 review fixes — outcome

- **RED:** `test_the_detector_needs_a_proven_transport_failure` failed before the move:
  `AssertionError: assert True is False` (`is_parameter_refusal` of a `NotFoundError` with no
  transport chain). It passed after the detector checked provenance.
- **Code name `unsupported_parameters` (MAJOR finding): decision (a), keep the name.** Spec C4b
  sets the name, and a rename needs a spec erratum. The gateway already uses this code for a
  different answer: the parameter classifier (`G/routes/chat.py:621`,
  `G/routes/chat_profile_defaults.py:89`) sends HTTP **400** with a `rejected` map when the catalog
  does not enable a parameter. The new refusal is HTTP **404** with no `rejected` key. Thus the code
  alone is NOT distinct; the status and the code together are.
  - **Rule for unit 3 (replaces the rule "`unsupported_parameters` + `logprobs: true` ->
    `logprobs_unsupported`" above):** the engine maps to `logprobs_unsupported` only when the
    status is **404** AND `detail.code == "unsupported_parameters"` AND the body asked for
    `logprobs: true`. A 400 `unsupported_parameters` keeps its current mapping.
  - **Unit 3 adds an engine test** (with LC#20): a 400 `unsupported_parameters` with a `rejected`
    map on a call with `logprobs: true` (for example a disabled `temperature` or
    `provider_params.top_k`) keeps its current mapping and is NOT `logprobs_unsupported`.
  - **Owner decision pending:** approve (a) as a note on C4 and C4b, or choose (b), a distinct
    code (for example `no_endpoint_for_parameters`) with a spec erratum.
- **Other fixes:** the detector moved to `G/plugins/openrouter_provider/provenance.py` and
  requires a proven transport failure; `plugin.py` raises the new error `from exc`;
  `dispatch_errors.py` says what a client can do with the code; the test file has one
  `_as_transport` helper and one new direct test (10 cases now); the logprobs fixture has no
  account or cost data.
- **Commit:** `fix(screamingface-engine): review fixes for E4b part 3 unit 1`. One commit, as the
  run asked; the RED line above is the record of RED first. Later units commit RED separately, as
  part 1 did.
- **Gates:** `run_gates.py aigateway --base 0f4b9e292` ALL GATES GREEN (append-only, ruff, format,
  pyright, no-enterprise, pytest with coverage >= 80). `run_gates.py repo --base 0f4b9e292` ALL
  GATES GREEN.
- **Pinned edits:** none. No test from before this part changed.

### Open items (owner)

1. The `unsupported_parameters` name decision above ((a) kept; approve or choose (b)).
2. The embedded HTTP-200 shape of the parameter refusal still gives `provider_error` (deviation
   (3) of unit 1). C4b does not limit the shape, and the test plan rates this risk H×H. To close
   it: approve it as a C4b erratum, OR allow a pinned edit of
   `test_no_eligible_endpoint_embedded_in_a_200_body_surfaces_sanitized` in a later unit, and
   change `test_the_embedded_http_200_parameter_refusal_keeps_its_mapping` with it.
3. At PR-open, replace "E4b part 3" in the gateway comments (`provenance.py`,
   `dispatch_errors.py`, `plugin.py`) with the OME id.

## Unit 2 — declared signals and verbalized

### Intent

Let a reducer Fusion declare named signal sources (`signals=`) and read them with
`sf.signal(name)`. Add the first source, `sf.Verbalized(pattern)`: the number that a member states
in its text. A rule that reads an undeclared name fails in the Fusion constructor, before any
call (ans:Q1). The engine records every declared name for every member (ans:Q7) and writes the
optional evidence key `declared` (P11). A Fusion that declares nothing compiles to the same bytes.

### Planned changes

- SDK: `S/_signals.py` (`is_signal_name`, the name constants, the new refusal text),
  `S/_regex_rule.py` (`check_signal_pattern`), new `S/signal_sources.py` (`SignalSource`,
  `Verbalized`, `declared_from_spec`, `python_signals`), `S/fusion.py` (`signals=`, name and read
  checks), `S/_evaluation/fusion_recipe.py` (keep `signals` in the rewrites),
  `S/_evaluation/combine_spec.py` (emit and decode `signals`), `S/_evaluation/candidate.py`,
  `S/url4.py` (`to_python` rebuild), `S/combine_evidence.py` and `S/_evaluation/combine_evidence.py`
  (`declared`), `S/__init__.py` (`sf.Verbalized`).
- Engine: `E/combine/ports.py` (`is_signal_name`, `SourceDescriptor`), `E/combine/registry.py`
  (`sources=`, `source()`), `E/combine/operators/extract.py` (`check_signal_pattern`,
  `verbalized_value`, `SOURCES`), `E/combine/builtins.py` (`BUILTIN_SOURCES`),
  `E/combine/operators/signals.py` (arg checks accept a declared name), `E/combine/spec.py`
  (`signals`, `VerbalizedSource`), `E/combine/endpoint.py` (plan-level key check, values of every
  declared name), `E/combine/evidence.py` (`declared`).
- Data: the combine-spec and combine-evidence v1 schema snapshots, `ST/public_surface_snapshot.json`,
  new `ET/data/combine_contract/verbalized_vote_candidate.url4`, the pinned edit of
  `ST/test_signals.py:33`, the approval manifest `.claude/test-change-approvals/OME-1290.json`
  (PENDING owner approval).

### Design notes (errata E1–E8, also in 00-overview §10)

- E1: the verbalized reader reaches the combine core through the registry (`SourceDescriptor`),
  because the layering gate forbids the core to import a plugin or `re2`.
- E2: operators see only the read key in `Answer.signals`; the evidence records every declared
  name. A declared name in `Answer.signals` would change `weighted_mode@1` without weights.
- E3: DS#16 tests only "authored params stay"; the drop of injected params is LP#14 and EN#13.
- E4: DS#7 tests the "one entropy" rule with a test-local source, because `sf.Entropy` is unit 4.
- E5: the SDK `CombineSignal` keeps its E4a-only constructor (pins); a declared read uses
  `CombineSignal._declared`, and `CombineEvidence` checks the name is in `declared`.
- E6: `by_signal@1` and `filter@1` accept the declared-name syntax in their args; the plan-level
  check refuses a name that the spec does not declare.
- E7: VB#8 runs its own SDK-compiled fixture, not a README recipe (recipes are unit 5).
- E8: the append-only gate passes through a PENDING approval manifest; the owner must approve it.

### Test plan

27 rows: DS#1–16, VB#1–11, in the PRD order. CHAR: DS#1, DS#2, DS#3. RED for the other 24. New
test files: `ST/test_declared_signals.py`, `ST/test_verbalized.py`,
`ST/test_verbalized_contract_fixture.py`, `ST/unit/test_declared_name_conformance.py` (guard),
`ET/test_combine_declared_signals.py`, `ET/test_combine_verbalized.py`,
`ET/test_combine_verbalized_run.py`. Every oracle is hand-computed in the unit spec. No live call.

### Acceptance

- The 27 rows pass; the three CHAR rows passed before the change too.
- No compiled url4, golden fixture or evidence byte of an existing case changes.
- `run_gates.py screamingface-engine|screamingface|repo --base 0f4b9e292`: ALL GATES GREEN.
- The pinned edits are exactly the four files of the manifest.

### Unit 2 RED record (commit A, 2026-10-15)

Run: the six new test files, and `tests/test_signals.py`, in each package. No live call.

- **CHAR, pass before and after:** DS#1, DS#2 (`ST/test_declared_signals.py`), DS#3 (three cases,
  `ET/test_combine_declared_signals.py`).
- **RED, fails on behavior (one line per row):**
  - DS#4 `NotImplementedError: E4b part 3 unit 2` (the `Fusion(signals=)` stub, positive first).
  - DS#5 `NotImplementedError` (same stub, positive first).
  - DS#6 `ValueError: unknown signal key 'cost'` (today's closed key rule in `sf.signal`).
  - DS#7 `NotImplementedError` (the `Fusion(signals=)` stub).
  - DS#8 `NotImplementedError` (the `Fusion(signals=)` stub).
  - DS#9 `ValueError: unknown signal key 'conf'` (today's closed key rule, raised by `sf.signal`).
  - DS#10 `ValidationError: 3 validation errors for CombineSpec` (closed spec: `signals` extra).
  - DS#11 `SpecInvalid: combine spec is invalid: signals: Extra inputs are not permitted`.
  - DS#12 `SpecInvalid` (the same closed-spec message).
  - DS#13 `SpecInvalid` (the same closed-spec message).
  - DS#14 `NotImplementedError` (the `Fusion(signals=)` stub).
  - DS#15 `ExecutionError: ev contains unsupported field 'declared'`.
  - DS#16 `NotImplementedError` (the `Fusion(signals=)` stub).
  - VB#1 `NotImplementedError` in `verbalized_value`.
  - VB#2 `NotImplementedError` in `verbalized_value`.
  - VB#3 `NotImplementedError` in `verbalized_value`.
  - VB#4, engine half: `NotImplementedError` in `check_signal_pattern`.
  - VB#4, SDK half: `NotImplementedError` (the `sf.Verbalized.__init__` stub).
  - VB#5 `NotImplementedError` in `verbalized_value`.
  - VB#6 `NotImplementedError` in `verbalized_value`.
  - VB#7, engine half: `NotImplementedError` in `verbalized_value`.
  - VB#7, SDK half: `NotImplementedError` (the `sf.Verbalized.__init__` stub).
  - VB#8 `AssertionError: combine_contract/verbalized_vote_candidate.url4 is missing` (commit B
    writes the fixture).
  - VB#9 `SpecInvalid` (closed spec: `signals` extra, and `weights.signal` not known).
  - VB#10 `NotImplementedError` in `verbalized_value`.
  - VB#11 `NotImplementedError` (the `sf.Verbalized.__init__` stub).
- **Support test, no row:** `ST/test_verbalized_contract_fixture.py` fails with
  `AssertionError: ... verbalized_vote_candidate.url4 is missing` until commit B.
- **Pinned edit, passes:** `ST/test_signals.py` (the `cost` item is removed from the refused keys).
- **Totals:** SDK 13 failed, 9 passed (the failed count includes the fixture support test). Engine 14
  failed, 3 passed (the three DS#3 cases).

### Unit 2 deviations at commit A

1. **DS#1, the text check.** The row says `'"signals"' not in compile_recipe(name)`. That is false
   for the committed bytes: the judge topology of `recipe_s10.url4` and `recipe_s11_max.url4` has a
   `"signals"` list (the judge reads its signals). The test now asserts
   `"signals" not in spec_of(text)`, the decoded combine spec. The byte equality with
   `read_contract(name)` is unchanged.
2. **DS#9 and DS#14, decode helper.** The row uses `_calls(build(url4))[...].raw_intent`, a
   helper that is not importable. The test uses `spec_of(url4)` from `tests/_vote_run_fixtures.py`
   (the same decode), and `screamingface.url4._calls` where it needs the call.
3. **DS#5, the `field:x` case.** The row says `match "not a declared name"`. The §2.4 text
   (`_name_rejection`) gives `E4a signal key` for `field:x`, because `field:x` is a valid E4a field
   key (the same class as `score:judge`, which the row matches with `E4a signal key`). The test
   matches `E4a signal key`. Owner decision needed: keep the §2.4 text (this test), or change the
   §2.4 text and the test.
4. **VB#9 and the engine helpers.** The spec `real_vote(**overrides)` passes `reduce=` twice when a
   row overrides `reduce` (a `TypeError`). The helper merges the overrides into the defaults before
   `vote_spec`. The oracles are unchanged.
5. **Pinned edits made at commit A:** `ST/test_signals.py:33` only. The manifest
   `.claude/test-change-approvals/OME-1290.json` and the three data snapshots are commit B work.
   Commit A therefore fails the append-only check for `ST/test_signals.py`, as E8 says.
6. **VB#10 chosen N.** `N = 1000`: `re2.compile("Confidence: ([0-9]{1,1000})").programsize == 2017`,
   inside [1000, 5000].

### Unit 2 outcome

- **Actual files:** the code of spec §2 (SDK and engine, as planned above), the regenerated
  combine-spec and combine-evidence v1 schema snapshots, `ST/public_surface_snapshot.json`, the new
  `ET/data/combine_contract/verbalized_vote_candidate.url4` (written by `write_fixture()`), the
  conformance guard `ST/unit/test_declared_name_conformance.py`, and the approval manifest
  `.claude/test-change-approvals/OME-1290.json` (approver PENDING). The four approved blobs agree
  with `git hash-object` of the four pinned files.
- **RED:** see "Unit 2 RED record" above. All 24 RED rows pass after commit B; the three CHAR rows
  still pass.
- **VB#10:** `N = 1000`; `re2.compile("Confidence: ([0-9]{1,1000})").programsize == 2017`.
- **Commits:** `test(e4b): RED for declared signals and sf.Verbalized (E4b part 3 unit 2)`, then
  `feat(e4b): declared signals and sf.Verbalized (E4b part 3 unit 2)`.
- **Pinned edits:** `ST/test_signals.py:33` (the `cost` item), the two schema snapshots and
  `ST/public_surface_snapshot.json`. All four are in the manifest, PENDING owner approval.
- **Deviations (owner review):**
  1. **DS#14 oracle, erratum E9.** `repr(rebuilt) == repr(fusion)` cannot pass. The url4 rebuild
     of a Vote keeps the pinned operator ids (`extract='last_line@1'`, `normalize='text@1'`); the
     pins `ST/test_judge_url4_round_trip.py:184` and `ST/test_reducer_recovery_preference.py`
     require this. The test now asserts the exact rebuilt repr with the `@1` ids and the
     `signals` text. `_compiled(rebuilt) == url4` and the authored-repr assert stay. The rebuild
     code did not change. This is an edit of a RED-commit test.
  2. **DS#15, pyright narrowing.** After RED, `evidence is not None and` and `plain is not None and`
     were added to two asserts, because pyright refused the member access on the Optional result
     of `decode_combine_evidence`. No assertion was removed. This is an edit of a RED-commit test.
  3. **`_check_declared` in `S/fusion.py`.** A new private helper, so that the Fusion constructor
     passes the ruff complexity rules. No behavior change.
  4. **`# noqa: PLR0911` on `endpoint._signal_numbers`.** The review fixes below remove it.

### Unit 2 review fixes — outcome

- **DS#14 oracle (MAJOR):** amended in commit B as erratum E9 (see deviation 1 above). The url4
  rebuild code did not change.
- **Unit completion (MAJOR):** commit B is made; the outcome section above is written; the three
  gates ran after the fixes (see below). The stray `packages/screamingface/.coverage.*` files were
  deleted; files were staged by name only.
- **DS#15 narrowing edit:** kept; it is in deviation 2 above as an owner-review item.
- **`_is_signals`** in `S/_evaluation/combine_spec.py` moved directly after `_is_step`, above
  `spec_operator_pairs` and `__all__`.
- **`endpoint._signal_values`** dispatches a declared name to `_declared_numbers` through a
  `by_name` map. `_signal_numbers` has its E4a signature `(key, spec, context, accounting)` again,
  and the `# noqa: PLR0911` is gone.
- **`__all__` order:** `DECLARED_NAME` and `RESERVED_NAME_PREFIXES` in `E/combine/ports.py`, and
  `VerbalizedSource` in `E/combine/spec.py`, are in their sorted places (`ruff --select RUF022`
  passes).
- **DS#10 guard:** a NEW test, `test_a_bad_declaration_message_does_not_echo_the_name_or_the_pattern`,
  is appended to `ET/test_combine_declared_signals.py`. It uses `zq`-marked names and patterns in
  seven bad declarations and asserts `zq` is not in the message. The existing DS#10 test did not
  change. No RED was possible: the behavior was already correct; the test is a guard.
- **`signals: null` (schema says valid, validator refuses):** a `# WHY` comment in
  `E/combine/spec.py::_check_signals` records that an explicit null is refused and a spec with no
  declaration omits the key. Deviation: the finding suggested a docstring line, but the
  `VerbalizedSource` and `CombineSpec` docstrings are the `description` fields of the pinned
  combine-spec schema snapshot, so a docstring edit changes a pinned file. The comment does not.
  The validation did not change.
- **No change (by the finding):** the unit 4 forward fit of `_Declared.read` and
  `CombineSpec.signals` (unit 4 spec must say how to generalize: a per-member record reader or a
  source-kind tag, and a discriminated union on `source`); the two `{name!r: source}` repr helpers.
- **Pinned files:** none changed by the fixes. The four manifest blobs still agree with
  `git hash-object`.
- **Gates (after the fixes):** `run_gates.py screamingface-engine --base 0f4b9e292` ALL GATES
  GREEN (append-only with the two approved OME-1290 schema transitions, ruff, format, pyright,
  layering, pytest with coverage >= 80). `run_gates.py screamingface --base 0f4b9e292` ALL GATES
  GREEN (append-only with the two approved OME-1290 transitions, ruff, format, pyright, pytest with
  coverage >= 95, notebooks, build, distribution check). `run_gates.py repo --base 0f4b9e292` ALL
  GATES GREEN. No flaky test failed.
- **Commit:** `fix(e4b): review fixes for E4b part 3 unit 2`.

## Unit 3 — logprob capture

Status: done. The RED stage is commit `8a3ed217d`. The GREEN stage is commit B (see the outcome
below).

### Intent

A member call that asks for `logprobs` keeps the numbers of its terminal reply. The numbers are
the token count, the exact sum of the token log-probabilities, the asked `top_logprobs` k, and the
mean token entropy. The one member reader gives them to the combine step. The gateway refuses a
call with HTTP 404 `unsupported_parameters` when that call has `logprobs: true`. The call then
fails with the new permanent engine code `logprobs_unsupported` and fixed engine text. The author
sees the code in the activity view. The rows are LC#1–19 and the engine half of LC#20.

### Planned changes

- New `E/world/reply_logprobs.py`. It holds `reply_logprobs`, the two validations, and the entropy
  of entropy PRD §3.
- `E/operation_accounting.py` gets `ReplyLogprobs`. `E/operation_calls.py` gets the
  `reply_logprobs` field and parameter. `E/combine/ports.py` gets the three reader keys and the
  port docstring. `E/world/combine.py` gets `_member_logprobs` and one count-only warning.
  `E/world/connector.py` gets the terminal round, the fail-open parse, and
  `_raise_for_status(..., logprobs_requested=)`. `E/benchmarks/failure_classes.py` gets
  `logprobs_unsupported()`. `E/benchmarks/contract.py`, `E/error_text.py` and
  `E/activity/contract.py` get the code. SDK: `S/_report_primitives.py` and
  `S/_ui/activity_record.py` get the code.
- New tests: seven engine files, the helper `ET/logprobs_support.py`, and three SDK files.
- Pinned edits: `ET/test_failure_classes.py`, `ET/test_e4b_catalog_pins.py`, and
  `ET/test_terminal_error_detail.py`. `ST/unit/test_failure_code_conformance.py` has no edit.

### Decisions taken in the unit spec (for owner review)

- **D-U3-1.** The refusal mapping is in `_raise_for_status`, with the `logprobs_requested` flag.
  It is not in `_observed_round_trip`. Only `_raise_for_status` sees the HTTP status, and the
  callers hold the request body. The code still reaches `observation.failed` in
  `_observed_round_trip`.
- **D-U3-2.** The reader port keeps its type. Each member gets three more keys:
  `logprob_tokens`, `logprob_sum`, and `entropy_mean`. The existing reader fakes stay valid.
- **D-U3-3.** `ReplyLogprobs` is in `E/operation_accounting.py`. A shared module
  (`operation_calls.py`) cannot import `world`.
- **D-U3-4.** The entropy formula is built in this unit, because LC#17 needs it. Unit 4 rows EN#1,
  EN#2, EN-D1 to EN-D3, and EN-D6 pass at once.
- **D-U3-5.** `logprobs_unsupported` joins the activity `failure_code` sets of the engine and the
  SDK. Without it, the activity view shows `internal_error`, and P6 is false. This file was not in
  the plan's unit table.
- **D-U3-6.** LC#15 is CHAR in this unit. It uses authored params. Unit 4 adds the injected params
  and their test.
- **D-U3-7.** The engine names the gateway code once, in `_PARAMETER_REFUSAL_CODE`. Owner item (a)
  or (b) of unit 1 changes only this constant.

### Test plan

RED first (commit A), then GREEN (commit B). CHAR rows: LC#1, LC#2, LC#13 (guard), LC#15, LC#18,
LC#20e (guard), and the fixed-text check of LC#10. RED rows: LC#3–12, LC#14, LC#16, LC#17, and
LC#19. The oracles are hand-computed in the unit spec: fsum -0.6, EN-1 = 1.0296530140645737, and
the entropy of the recorded reply, 6.547567880357428e-07.

### Acceptance

- All LC rows pass. The neighbor tests pass. No fixture, schema or public-surface file changes.
- `run_gates.py screamingface-engine`, `screamingface` and `repo` pass with `--base 0f4b9e292`. The
  append-only check lists only the approved pinned files.

### Unit 3 outcome

- **Start commit:** `1349f0dce` (unit 2 tip, a descendant of `0f4b9e292`). The §0 checks passed:
  the unit 2 files are unchanged since the part base, and the `AccountingReader` anchor and the
  three fixtures exist.
- **RED (commit A, run 2026-10-15):**
  - Engine, 10 files: 122 tests, 56 failed, 66 passed. Each failure is an `AssertionError` or a
    `NotImplementedError` from a stub. No `ImportError` and no collection error. The CHAR rows pass:
    LC#1 (2), LC#2, LC#13, LC#18, LC#20e (4), and the fixed-text check of LC#10 (10 CHAR tests in all).
  - SDK, 4 files: 2 failed, 11 passed. `test_logprobs_unsupported_vocabulary.py` fails on an
    `AssertionError` (the code is not declared). `test_logprobs_unsupported_activity.py` fails with
    `ValueError: unknown activity category`, raised by the closed set check of
    `S/_ui/activity_record.py:138`. This is the D-U3-5 gap, and it is the expected RED reason. The
    LC#15 preflight rows (3) pass as CHAR.
- **GREEN (commit B):**
  - Engine: the seven new unit 3 test files and the three pinned files pass: 122 tests passed. The
    neighbor tests of the unit spec (14 files) pass: 247 tests passed.
  - SDK: the three new unit 3 SDK files and the three neighbor SDK files pass: 58 tests passed.
  - No test file was edited in GREEN. No fixture, schema or public-surface file changed.
- **Commits:** A: `8a3ed217d` `test(screamingface-engine): RED for E4b part 3 unit 3 logprob-capture`.
  B: `feat(screamingface-engine): keep reply logprobs and map the logprobs refusal (E4b part 3
  unit 3)`. Commit B holds the code and this outcome. There is no commit C: the unit spec says the
  PRD asks for no README or CHANGELOG change in this unit. Unit 5 writes them.
- **Gates (RED stage, `--base 0f4b9e292`):**
  - `screamingface-engine`: the append-only check listed ONLY the three approved pinned files
    (`test_e4b_catalog_pins.py`, `test_failure_classes.py`, `test_terminal_error_detail.py`). Rerun
    with `--skip-append-only`: ruff check, ruff format, pyright and layering passed. The suite gave
    56 failed (the RED rows only), 5868 passed, 108 skipped. The coverage step did not run, because
    the pytest step failed. The red result is expected at this stage.
  - `screamingface`: append-only passed. Ruff, format and pyright passed. Pytest gave 2 failed
    (the two SDK RED rows: LC#10 SDK and the activity view), 4269 passed, 32 skipped.
  - `repo`: ALL GATES GREEN.
  - No `--skip-append-only` rerun was needed for the SDK or the repo stack.
- **Gates (GREEN, `--base 0f4b9e292`):**
  - `screamingface-engine`: the first run failed on the append-only check only. The check listed
    ONLY the three approved pinned files: `tests/unit/test_e4b_catalog_pins.py`,
    `tests/unit/test_failure_classes.py` and `tests/unit/test_terminal_error_detail.py`. The rerun
    with `--skip-append-only` gave ALL GATES GREEN (ruff check, ruff format, pyright, layering,
    and pytest with coverage at 80 percent or more). No flaky test appeared.
  - `screamingface`: ALL GATES GREEN, the append-only check included. No offender was listed.
  - `repo`: ALL GATES GREEN, the append-only check included.
- **Pinned edits (unchanged in GREEN; each blob matches the RED stage):** no new edit in this
  unit. The blobs are the same as the RED section above.
- **Pinned edits for owner approval** (base blob, then approved blob):
  - `apps/screamingface-engine/tests/unit/test_failure_classes.py`: `1d214eff0af8da49d40f642d5377583209835d12` to `6d8699ab03d5e02491e30bed688356b974d7caad`. One line added to the exact set in `test_the_declared_vocabulary_is_exactly_the_agreed_set`.
  - `apps/screamingface-engine/tests/unit/test_e4b_catalog_pins.py`: `60a41ea9c7ea5001b2d4d298db5f34367deb74a2` to `2fe20d9b61f54f95375331977ce9c51c8a675471`. The file was replaced as the spec says (it had 20 lines).
  - `apps/screamingface-engine/tests/unit/test_terminal_error_detail.py`: `6c6824dfd7b379e0efccddd4e3c43b35cb2f7758` to `31a4e7875a33f83816768fda200f39b1c337db58`. One line added to `ALLOWLISTED_CODES`.
- **Deviations:**
  1. The spec gives the pinned range of `test_failure_classes.py` as lines 88 to 110. The
     `combine_input_too_large` line is at line 165, in the same test function. The edit follows the
     anchor text, not the line range.
  2. The spec's oracle for LC#3 said that a plain `sum([-0.1, -0.2, -0.3])` differs from -0.6. That
     is false: it gives -0.6. The premise line was removed from `test_reply_logprobs.py`. The
     assertions on `reply_logprobs` are unchanged.
  3. The SDK preflight test handler `_engine` uses one route table, not four `if` branches. The
     four branches broke ruff PLR0911. The answers are the same as the spec's.
  4. `ruff check --fix` and `ruff format` changed the import order and the layout of the new files
     and of the stubs. No behavior changed.
  5. GREEN (commit B), no behavior change: ruff reported PLR0911 (too many returns) on
     `_content_entries` and `_entropy_mean` in `world/reply_logprobs.py`, and on `_member_logprobs`
     in `world/combine.py`. The unit spec does not name this rule. I restructured those three
     functions. `_entropy_mean` moved its top-list loop into a new helper `_top_values`. The return
     values stay the same. The gate needs the ruff check green.
  6. GREEN (commit B): two lines longer than 100 characters (a comment in `error_text.py` and a
     docstring line in `world/reply_logprobs.py`) were wrapped by hand, because ruff format does not
     wrap comments or docstrings.

## Unit 4 — logprob and entropy sources

Status: done (commit B and the review fixes). Unit spec: v2 (`p3-unit4-logprob-entropy-v2.md`).

### Intent

Add the declared sources `sf.Logprob("mean" | "sum" | "prob")` and `sf.Entropy(top_logprobs=5)`.
A Fusion that declares one of them asks each member call for logprobs. The SDK refuses the cases
that cannot work, writes the context `sources`, and rebuilds from url4 without the injected params.
The engine reads the declaration as a discriminated union. It turns the reply numbers of each
member (unit 3) into the declared value. Rows: LP#1–14 and EN#1–13 (27 rows). This commit is the
RED stage (commit A): the tests and the stubs only.

### Step 0 — facts at the start

- HEAD at start: `df3afd6cc5d3ee23f23105d29aa6c7ad6bbb467a`. The tree was clean.
- Reference folder checksums: equal to the values in the unit spec §0.
- `git apply --check` of the stub patch: passed.
- SDK source API (unit 2): `SignalSource` has abstract `_spec()` and `_from_spec(entry)`, and a
  concrete `_python()`. `fusion.signals` is None when nothing is declared.
- Engine before this unit: `CombineSpec.signals: dict[str, VerbalizedSource] | None`. Every
  declared entry resolves through `registry.source(...)`.
- `reply_logprobs` has the residual entropy formula (unit 3, D-U3-4). EN#1–5 and EN#11 are CHAR
  rows. EN#12 (LC#17) and LP#11 (LC#3) are CHAR rows too.
- DS#7 is closed by unit 2, with a test-local fake. This unit adds the support test
  `test_fusion_refuses_two_entropy_sources` with the real `sf.Entropy` (CHAR).
- DS#16 is open. Its drop half closes in this unit with LP#14 and EN#13.
- LC#15 is pinned by `ST/test_logprobs_parameter_preflight.py` (authored params, CHAR). Its
  injected-params half (D-U3-6) closes with the LP#6 preflight test.
- No helper fakes gateway logprobs for a full Candidate run. This unit creates
  `ET/_logprob_world.py`.
- No approval manifest exists (removed at `df3afd6cc`). The append-only gate has no manifest.

### Planned changes

- Commit A (this commit): stubs in `S/signal_sources.py`, `S/__init__.py` and
  `E/combine/logprob_forms.py`. Seven new test files: six test modules and the helper
  `ET/_logprob_world.py`. The existing surface test `ST/test_public_surface.py` does not change;
  it fails in commit A because of the new exports.
- Commit B (GREEN, not this commit): the SDK product code (`S/fusion.py`,
  `S/_evaluation/candidate.py`, `S/url4.py`), the engine product code (`E/combine/spec.py`,
  `E/combine/endpoint.py`), ten `ET/data/combine_contract/*.url4` fixtures, and two pinned files.
- Pinned edits (owner approves; commit B only): `ST/public_surface_snapshot.json` (adds `Entropy`
  and `Logprob`); `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json` (adds the
  two source shapes; owner approved 2026-10-15).

### Unit decisions (for owner review)

- U4-D1: a Fusion that declares `sf.Logprob` or `sf.Entropy` refuses a member Model that sets
  `logprobs` or `top_logprobs` itself. Reason: the injection owns these two params.
- U4-D2: `sf.Logprob(form)` has no default. `sf.Entropy` is keyword-only with `top_logprobs=5`.
- U4-D3: a bad `form` or `top_logprobs` (any type, also `bool` and `float`) raises `ValueError`.
- U4-D4: the form arithmetic is the new pure core module `E/combine/logprob_forms.py`.
- U4-D5: the injected params follow the author params: `logprobs` first, then `top_logprobs`.
- U4-D6: the engine declaration is a discriminated union on `source`. `VerbalizedSource` does not
  change.
- U4-D7: a logprob or entropy name is a `_ReplyDeclared` in the plan, not a registry source.
- U4-D8: one member reader call per combine call. `_accounting_numbers` is merged away.
- U4-D9: the url4 rebuild drops the params that `injected_member_params(declared)` names. The
  Fusion branch moves to `_fusion_from_topology` (ruff PLR0915).
- U4-D10: the commit A stubs store the value with no check. `_spec`, `_from_spec`, `logprob_value`
  and `entropy_value` raise `NotImplementedError("E4b part 3 unit 4")`.
- U4-D11 (owner item): the `parse_context` text still says "when the spec reads an accounting
  signal". The text is pinned, so it does not change here.
- Erratum E-1: PRD LP-6 writes `sf.Rank(2, by=...)`. The API is `sf.Rank(k, *, by_signal=...)`.
- Erratum E-2: PRD EN-2 says H = 0.2 and H = 0.6. The test uses H = ln 2 and H = ln 4. The oracle
  is 1.5 · ln 2.
- Erratum E-3: `sum([-0.1, -0.2, -0.3])` gives `-0.6`. The v1 claim of `-0.6000000000000001` is
  false.
- Erratum E-4: run the layering script with `uv run python`. The system `python3` is too old.
- Erratum E-5: the source methods are unit 2's `_spec()` and `_from_spec()`, not `_wire()`.

### Test plan

- Source of the tests: the reference folder of the unit spec (copied, not rewritten). Their
  checksums equal the spec §0 values.
- RED rows: 19 of the 27 rows. CHAR rows: LP#11, EN#1–5, EN#11, EN#12 (8 rows).
- Support tests (not counted in the 27): `test_logprob_refuses_an_unknown_form` (RED),
  `test_declared_from_spec_rebuilds_and_refuses_logprob_and_entropy_entries` (RED),
  `test_fusion_refuses_two_entropy_sources` (CHAR), `test_one_reader_call_feeds_the_reply_names_and_the_accounting_key`
  (RED), and the 10-case fixture drift guard (RED).
- The engine world tests read their fixtures inside the test body. In commit A they fail with
  `AssertionError: combine_contract/<name> is missing`, not with a collection error.

### Acceptance

- Commit A: every RED row fails for the reason of §4 of the unit spec. Every CHAR row passes.
  No `ImportError`, no `NameError`, no collection error.
- Commit A: ruff check, ruff format --check and pyright pass in both stacks.
- Final (after commit B): all 27 rows and the support tests pass; no existing fixture changes; the
  combine-evidence schema does not change; the schema and surface diffs are additive.

### Unit 4 outcome

- Audit before commit A: the seven new test files are byte-equal to the reference test files. The
  three product files are byte-equal to the result of the stub patch on `df3afd6cc`. No production
  behavior is in the stubs. No existing test or pinned file changed in commit A.
- RED (commit A), SDK (`test_logprob_source.py`, `test_entropy_source.py`,
  `test_logprob_entropy_url4_fixtures.py`, `test_public_surface.py`): 34 failed, 11 passed. The 11
  passes are the 3 LP#4 controls, the two-entropy support test and 7 other surface tests.
- RED (commit A), engine (`test_logprob_forms.py`, `test_reply_entropy.py`,
  `test_logprob_entropy_world.py`): 13 failed, 13 passed. The 13 passes are the CHAR rows.
- Failure line per RED row:
  - LP#4 `test_vote_weight_refuses_logprob_mean_and_sum_with_a_prob_hint` (6 cases) ->
    `Failed: DID NOT RAISE ValueError`.
  - LP#1 `test_logprob_forms_mean_sum_prob` -> `NotImplementedError: E4b part 3 unit 4`.
  - LP#2 `test_logprob_of_zero_tokens_is_none` -> `NotImplementedError: E4b part 3 unit 4`.
  - LP#5 `test_logprob_refuses_non_openrouter_and_recipe_members` ->
    `Failed: DID NOT RAISE ValueError`.
  - LP#6 `test_logprob_compiles_logprobs_true_on_each_member_call` and
    `test_logprob_preflight_refuses_a_model_the_catalog_marks_without_logprobs` (2 cases) ->
    `NotImplementedError: E4b part 3 unit 4` (from `Logprob._spec`).
  - LP#7 `test_pick_max_by_logprob_mean` -> `AssertionError: combine_contract/logprob_pick_mean_candidate.url4 is missing - write it with the SDK`.
  - LP#8 `test_vote_weighted_by_logprob_prob` -> `AssertionError: ... logprob_vote_prob_candidate.url4 is missing`.
  - LP#3 `test_logprob_prob_underflow_is_none` -> `NotImplementedError: E4b part 3 unit 4`.
  - LP#9 `test_filter_by_logprob_threshold_records_the_values` and
    `test_steer_filter_records_the_member_mean_and_its_pass` -> `AssertionError: ...
    logprob_filter_mean_candidate.url4 is missing` and `... logprob_steer_filter_candidate.url4 is missing`.
  - LP#10 `test_samples_members_get_their_own_logprob` -> `AssertionError: ...
    logprob_samples_pick_candidate.url4 is missing`.
  - LP#12 `test_rank_by_logprob_mean_keeps_the_top_k` -> `AssertionError: ...
    logprob_rank_mean_candidate.url4 is missing`.
  - LP#13 SDK `test_pick_and_filter_accept_sum_and_prob` -> `NotImplementedError: E4b part 3 unit 4`;
    engine `test_pick_and_filter_accept_sum_and_prob_in_the_engine` -> `AssertionError: ...
    logprob_pick_sum_candidate.url4 is missing`.
  - LP#14 `test_logprob_fusion_rebuilds_from_url4_without_injected_params` (2 cases) ->
    `NotImplementedError: E4b part 3 unit 4`.
  - EN#7 `test_vote_weight_refuses_entropy_with_an_order_min_hint` (3 cases) ->
    `Failed: DID NOT RAISE ValueError`.
  - EN#8 `test_entropy_compiles_top_logprobs_on_each_member_call` ->
    `NotImplementedError: E4b part 3 unit 4`; `test_entropy_refuses_non_openrouter_and_recipe_members`
    -> `Failed: DID NOT RAISE ValueError`.
  - EN#9 `test_pick_min_by_entropy` -> `AssertionError: ... entropy_pick_min_candidate.url4 is missing`.
  - EN#6 `test_entropy_refuses_bad_k` -> `Failed: DID NOT RAISE ValueError`.
  - EN#10 `test_logprob_and_entropy_share_one_reply` -> `AssertionError: ...
    logprob_entropy_shared_candidate.url4 is missing`.
  - EN#13 `test_entropy_fusion_rebuilds_from_url4_without_injected_params` (2 cases) ->
    `NotImplementedError: E4b part 3 unit 4`.
- Support tests in commit A: `test_logprob_refuses_an_unknown_form` -> `DID NOT RAISE ValueError`;
  `test_declared_from_spec_rebuilds_and_refuses_logprob_and_entropy_entries` ->
  `NotImplementedError`; `test_one_reader_call_feeds_the_reply_names_and_the_accounting_key` ->
  `SpecInvalid: combine spec is invalid: signals: Value error, signals must map declared names to
  known sources`; `test_fusion_refuses_two_entropy_sources` passes (CHAR); the drift guard
  `test_logprob_entropy_fixture_matches_the_sdk_compile` (10 cases) -> `AssertionError:
  combine_contract/<name> is missing - run write_fixture()`. Note: the unit spec §4.3 expected
  `NotImplementedError` from the builder for the drift guard. The reference test checks the
  fixture file first, so the missing-fixture assertion comes first. The test file is byte-equal to
  the reference; this is a note, not a change.
- `test_public_surface_matches_the_committed_snapshot` fails in commit A (new exports). This is
  expected; commit B regenerates the pinned snapshot.
- CHAR rows (pass in commit A): LP#11, EN#1, EN#2, EN#3, EN#11, EN#12 (6 cases), EN#4, EN#5.
- Other checks in commit A: ruff check, ruff format --check and pyright (0 errors) pass in both
  stacks; the layering script passes; the SDK regression neighbours (98 passed) and the engine
  regression neighbours (66 passed) pass with no fixture change.
- Behavior RED of the world rows (after B2, before B3): the 9 world tests fail with
  `CandidateExecutionError: combine spec is invalid: signals: Value error, signals must map
  declared names to known sources`. The one-reader test fails with `SpecInvalid` (same text).
- Commits: commit A `test(e4b): RED for E4b part 3 unit 4 logprob-entropy`; commit B
  `feat(e4b): sf.Logprob and sf.Entropy declared sources (E4b part 3 unit 4)`; review fix
  commit `fix(e4b): review fixes for E4b part 3 unit 4`.
- Pinned edits: none in commit A. Commit B changes the two pinned files (blob before at
  `df3afd6cc` -> blob after):
  - `ST/public_surface_snapshot.json`: `d3ef76bfb32bf9e1cc2ac43ae674ace395e97a14` ->
    `77a76cc650d3366f512913c7a1d0fa3d7391b760` (18 lines added, 0 removed; byte-equal to the
    reference).
  - `ET/data/combine_contract/schemas/screamingface.combine-spec.v1.json`:
    `179800a9d4b31df6482815c3e364b71f234f0aba` -> `b3acb2a5cd5c489c570a57384cd40fa5c9f30273`
    (+68/-1; byte-equal to the reference).
- Gates: not run in the RED stage (RED-step rule).
- Commit B checks: SDK focused run after B1: 34 passed, 11 failed (the 10-case drift guard and
  the surface test, as expected). SDK regression neighbours: 98 passed. The 10 fixtures are
  byte-equal to the reference. After B3: engine focused run 26 passed, engine regression
  neighbours 66 passed, schema freeze 10 passed, layering OK. SDK new tests and the surface
  test: 45 passed. Ruff check and ruff format are clean in both stacks. Pyright: 0 errors in
  the SDK, 2 errors in the engine (see the next item).
- Erratum E-6: the unit spec §0 says pyright had 0 errors at the commit B state. This is
  false. U4-D6 makes `CombineSpec.signals` a union, so the unit 2 test line
  `parsed.signals["conf"].pattern` in `ET/test_combine_declared_signals.py:103` gives 2
  pyright errors (`reportAttributeAccessIssue` for `LogprobSource` and `EntropySource`). The
  review fix commit closes this (next section).
- README and CHANGELOG notes for LP-D3 (`sum` favors short replies), EN-D5 (keep k small) and the
  nats unit go to unit 5.
- Deviations: none in commit A.

### Unit 4 review fixes

- R-1 (pyright, Erratum E-6): `ET/test_combine_declared_signals.py` imports `VerbalizedSource`
  and asserts `isinstance(parsed.signals["conf"], VerbalizedSource)` before it reads `.pattern`.
  This is one added assert and one changed import line. It makes the test stronger. The file is
  NOT on the unit 4 PINNED list, so the owner must approve it. Blob `9a7a101be00f1b0331569c4f0562f8ae947121e4`
  -> `d6bf10b39b7f42c0b61687495281b21ed34d5a9a`. The append-only gate does not list this file
  (the change is an insertion and an import). RED: pyright gave the 2 errors at commit B; after
  the edit pyright gives 0 errors. The test passed at runtime before and after.
- R-3: the `_reader_numbers` invariant text is now "combine context sources are missing for an
  accounting or reply-logprob signal". No test pins this text. The pinned `parse_context` text
  (U4-D11) does not change.
- R-4: `_check_logprob_sources` in `S/fusion.py` returns early when nothing is declared, and
  asserts that the synthesizer is a `Reducer` (`_declared` already refuses a model synthesizer).
  The behavior does not change; the existing LP and EN tests cover it.
- Not done, as the review says: R-5 (a `declares_reply_sources` SDK predicate, unit 5 or later),
  R-6 (keep `_injected_names` and the three-form dict, spec choices), R-7 (move
  `_wrapped_candidate` to a support module later).
- Gates after the review fixes (base `0f4b9e292`): repo ALL GATES GREEN. Engine and SDK: the
  only red check is append-only. Engine offenders: the combine-evidence and combine-spec schema
  snapshots, `test_e4b_catalog_pins.py`, `test_failure_classes.py`,
  `test_terminal_error_detail.py`. SDK offenders: `public_surface_snapshot.json`,
  `test_signals.py`. Each one is on an allowed or pinned list. With `--skip-append-only`, engine
  (ruff, format, pyright 0 errors, layering, pytest with coverage) and SDK (ruff, format, pyright,
  pytest with coverage, notebooks, build, distribution) are ALL GATES GREEN. No flakes.

## Unit 5 — recipes, README, CHANGELOG, paid test

### Intent

Give one tested recipe for each paper shape of part 3 (S12 to S16). The SDK compiles each recipe
into a url4 fixture. The Engine runs each fixture offline over fake replies to a hand-computed
answer. Add the README section "Signal sources" with the guidance of the PRDs, a CHANGELOG entry,
and two paid tests that the owner runs. Spec: `docs/spec/2026-10-15-e4b-signal-sources/prd/recipes.md`
(RC#1–9). Unit spec: `p3-unit5-recipes.md` (build folder, not in the repo).

### Dependency check (unit 2–4 names, confirmed in the branch code at commit A)

- `sf.Verbalized`, `sf.Logprob`, `sf.Entropy` exist (`screamingface.signal_sources`).
  `sf.Fusion.__init__` has `signals`.
- `reply_logprobs` exists: `E/world/reply_logprobs.py`.
- `logprobs_unsupported` is in `E/error_text.py` (the code name list).
- Engine refusal text: `LOGPROBS_UNSUPPORTED_TEXT` in `E/benchmarks/failure_classes.py`. It starts
  "the model cannot return token log-probabilities; choose another OpenRouter model or remove ...".
  It contains `cannot return token log-probabilities`, so the RC#9 assertion uses the full phrase.
- Evidence `declared` key: yes, in `E/combine/evidence.py` (field `declared`) and in
  `S/combine_evidence.py` (`CombineEvidence.declared`). The optional assert of RC#8 is included.
- The 64 KiB window: `_SIGNAL_WINDOW = 65_536` in `E/combine/operators/extract.py`.
- Logprob reply helper from units 3–4: `ET/_logprob_world.py` (`run_logprob_candidate`,
  `by_model`, `logprobs_object`). It takes the reply text per model, the token logprobs and the
  top lists per model, and returns the decoded run record. The §4.4 rule applies, so F4 uses it.
  No local `_Reply` or `_gateway` helper is written.
- `sf.Rank` takes `order=` (`inspect.signature`: `order: Literal['max', 'min']`). The README
  phrase "`sf.Rank` with `order="min"`" is therefore true. Checked here; the README is written at
  commit B.
- The part 1 fixtures (13 files) have the SHA-256 of base `0f4b9e292`, as pinned in
  `test_signal_recipe_fixtures.py`. Checked with `git show 0f4b9e292:<path> | shasum -a 256`.

### Planned changes

- New `packages/screamingface/tests/_signal_recipes.py`: one builder per recipe S12–S16, its own
  registry, `compile_signal_recipe`, `write_signal_recipe_fixture`.
- New `packages/screamingface/tests/test_signal_recipe_fixtures.py`: the CHAR pin of the part 1
  fixtures (RC#1) and the drift guard of the new fixtures.
- New `packages/screamingface/tests/test_signal_recipes_readme.py`: the README code compiles to
  the fixtures and the section has the guidance (RC#7).
- New `apps/screamingface-engine/tests/unit/test_signal_recipes.py`: engine runs (RC#2–6).
- New `packages/screamingface/tests/paid/test_signal_sources_paid.py`: RC#8, RC#9 (paid lane).
- New `apps/screamingface-engine/tests/unit/data/combine_contract/recipe_s12.url4` to
  `recipe_s16.url4` (generated, commit B).
- `packages/screamingface/README.md`: new section "Signal sources" before "Fusion as a named
  recipe" (commit B).
- `packages/screamingface/CHANGELOG.md`: one entry (commit C).
- No source change. No pinned test edit. No schema change.

### Test plan

- CHAR first: the 13 part 1 recipe fixtures keep the SHA-256 of base `0f4b9e292`, and the SDK
  compile gives the same bytes (RC#1).
- RED next, in the PRD order: S12 vote weighted by stated confidence (B wins, 90 over 20 + 30);
  S13 vote weighted by `prob` (B wins, 0.8187… over 0.1851…); S14 pick by `mean` (member 2,
  -0.2; a `sum` pick would choose member 1); S15 pick by entropy `min` (member 2, H = 0); S16
  Filter `>= -0.3` at -0.1, -0.3 and -0.5 (kept, kept, dropped; the writer runs each time); the
  README code compiles and the section carries the guidance.
- Paid (owner only): the pinned model gives a finite `lp` ≤ 0; the refusing model passes the
  preflight and fails with `logprobs_unsupported`.
- Invariant protected: the part 1 recipe bytes do not change; the README code is the code that
  the Engine runs.

### RED record (commit A, before any fixture or README text)

- SDK focused run: `tests/test_signal_recipe_fixtures.py tests/test_signal_recipes_readme.py
  tests/test_combine_recipe_fixtures.py tests/test_combine_recipes_readme.py
  tests/test_pick_output_url4_fixtures.py`: 6 failed, 30 passed.
  - 30 passed: the 13 CHAR cases (`test_recipes_s1_to_s11_fixtures_are_unchanged`), the cover
    test, and the part 1 guards.
  - 5 failed: `test_signal_recipe_fixtures_match_the_sdk_compile[recipe_s12..s16.url4]`,
    `combine_contract/recipe_sNN.url4 is missing - run write_signal_recipe_fixture(...)`.
  - 1 failed: `test_readme_signal_sources_blocks_compile_and_carry_the_guidance`,
    `README.md has no '### Signal sources' section`.
- Engine focused run: `tests/unit/test_signal_recipes.py tests/unit/test_combine_recipes.py`:
  7 failed, 15 passed. The 7 failures are the 5 S12–S16 runs (S16 has 3 cases):
  `combine_contract/recipe_sNN.url4 is missing - write it with the SDK`. The 15 passed are the
  part 1 engine runs.
- Paid collection with `SCREAMINGFACE_TEST_PAID=1`: 2 tests collected. Not run (no live call).

### Deviations at commit A

- F4 (`test_signal_recipes.py`) imports `by_model` and `run_logprob_candidate` from
  `_logprob_world.py` (the §4.4 rule). It does not write the §3.4 helpers `_Reply`,
  `_logprobs_block`, `_gateway` and `_run`. It keeps `_recipe`, `_envelope` and `_member_calls`.
- F1 and F2 and F3 wrap two 64-character hash values in parentheses in `_PART1_FIXTURE_SHA256`,
  and wrap one `write_text` call and two comments, to meet the 100-column limit (ruff E501 has no
  `noqa` convention in this repo). Values are unchanged; the CHAR cases pass.
- Row 9 (paid) checks the full refusal phrase, not the first 30 characters (§2 found the phrase).
- Row 8 (paid) includes the optional `combine.declared` assert (§2 found `CombineEvidence.declared`).

### Outcome

- **Actual files:**
  - Commit A: this ledger section, `_signal_recipes.py`, `test_signal_recipe_fixtures.py`,
    `test_signal_recipes_readme.py`, `test_signal_recipes.py` (engine) and
    `test_signal_sources_paid.py`.
  - Commit B: the five fixtures `combine_contract/recipe_s12.url4` to `recipe_s16.url4`, made by
    `write_signal_recipe_fixture`, and the README section "Signal sources".
  - Commit C: the CHANGELOG bullet and this Outcome.
  - No file under `S/` or `E/` changed. No schema snapshot changed. No existing test, fixture or
    pinned data file changed.
- **RED:** see "RED record" above. The RED run at commit A HEAD gave the same failures.
- **GREEN:**
  - SDK focused run (the six files of spec §7.2, SDK part): 76 passed.
  - Engine focused run (`test_signal_recipes.py` and `test_combine_recipes.py`): 22 passed. That is
    7 new cases and 15 part 1 cases.
  - The paid file collects 2 tests with `SCREAMINGFACE_TEST_PAID=1`, and 2 are deselected without it.
- **Commits:** A `04614e265` (test(e4b) RED); B `a1eab4f88` (feat(e4b) fixtures and README); C is
  the commit that adds this text (docs(e4b) CHANGELOG and outcome).
- **Gates:**
  - `repo`, base `0f4b9e292`: ALL GATES GREEN.
  - `screamingface`, base `c912513b9`: ALL GATES GREEN.
  - `screamingface-engine`, base `c912513b9`: ALL GATES GREEN.
  - Base `0f4b9e292` is red for `screamingface` and `screamingface-engine` on the append-only check
    only. See Deviations.
  - No flaky test failed in this unit.
- **Paid:** not run (owner action). Command: see the unit spec §7.5.
- **Deviations:**
  - See "Deviations at commit A".
  - The append-only check against `0f4b9e292` lists offenders from units 2 to 4. They are the
    pinned edits that those units wrote in their ledger sections, with the status "pending owner
    approval". The engine offenders are `screamingface.combine-evidence.v1.json`,
    `screamingface.combine-spec.v1.json`, `test_e4b_catalog_pins.py`, `test_failure_classes.py`
    and `test_terminal_error_detail.py`. The SDK offenders are `public_surface_snapshot.json` and
    `test_signals.py`. Unit 5 changed none of them. Per unit spec §6, the two stacks were rerun
    with base `c912513b9` (the branch HEAD before commit A), and both are green.
  - The unit spec §6 forbids `--skip-append-only`, so it was not used. The rerun with base
    `c912513b9` gives the same proof.
