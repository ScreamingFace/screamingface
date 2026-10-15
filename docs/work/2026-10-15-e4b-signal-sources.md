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
