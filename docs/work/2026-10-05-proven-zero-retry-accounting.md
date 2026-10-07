---
ticket: OME-1446
stack: aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-05
finished:
---

# proven-zero-retry-accounting — preserve priced retries without inventing evidence

## Intent

Let AIGateway mark an identifiable OpenRouter rejection as zero cost only when provider evidence
proves the complete charge in scope. Preserve successful retry cost without weakening
unknown-poisons-total or pretending a billing waiver proves zero token processing.

Spec: `docs/spec/2026-10-06-OME-1446-proven-zero-retry-accounting.md`.

## Planned changes

- Add an explicitly approved provenance-specific zero-cost status to AIGateway taxonomy and schema.
- Pass only the minimum trusted per-attempt transport facts required by the provider predicate.
- Add a pure OpenRouter classifier that never overwrites measured evidence.
- Count proven-zero attempts as cost coverage while keeping them out of reported subtotals.
- Add standalone mapper, route, schema/fixture and boundary regressions.
- Update `apps/aigateway/docs/usage-accounting.md`.
- Do not modify Engine unless a separately filed landing proves necessary.

## Test plan

- RED: covered native rejection + reported retry success yields complete cost and one subtotal.
- RED: bare 429/503, upstream ambiguity, auxiliary/BYOK uncertainty and malformed evidence remain
  unknown.
- RED: billed failed attempts retain positive usage/cost; classifier failures preserve measured data.
- RED: attempts and dispatch indexes remain complete; embedded HTTP-200 errors are not native proof.
- RED: tokens remain unknown unless the owner approves stronger no-execution evidence.
- Existing cache, streaming, hidden resend, bounds and exact-money tests stay unchanged.
- Full gate: `uv run .claude/scripts/run_gates.py aigateway --base origin/main`.

## Acceptance

- D0 provider evidence, D1 status semantics and D2 token acceptance are explicitly approved.
- A covered zero-charge rejection no longer blanks the successful retry's cost.
- Uncovered attempts remain unknown and no existing billed usage is dropped.
- Engine and SDK production code remain unchanged on the preferred path.
- A separately authorized retry-containing smoke verifies the covered class.

## Approved boundary

On 2026-10-06 the owner authorized a narrow cost-only implementation. It accepts only a native 429
whose complete opted-in router metadata proves non-BYOK and no billable pipeline stage; everything
else remains unknown. Insurance does not prove token counts, so this unit emits no synthetic token
zero. An all-proven-zero request remains partial unless it also has a reported subtotal.

## Review-fix iteration — 2026-10-06

Adversarial review found that the classifier did not recognize the current Chat Completions
`usage.server_tool_use_details` shape, did not reject a contradictory `usage.is_byok`, and did not
require the error body's `code` to agree with the native HTTP 429. This iteration will:

- add fail-closed regressions for those current provider fields and malformed/conflicting errors;
- minimally tighten the existing OpenRouter predicate without changing status or renderer semantics;
- add a real installed-LiteLLM/httpx observer regression proving raw router metadata reaches
  finalization, plus a separate provider-response regression proving account-specific metadata is
  removed from the returned payload;
- synchronize the scratch and public documentation with the implemented state.

Acceptance: every conflicting or potentially billable case remains unavailable, the documented
insured 429 still receives `provider_guaranteed_zero`, all prior tests remain unchanged and green,
and the full AIGateway gate passes without live or paid provider calls.

## NOT READY correction iteration — 2026-10-07

Independent review reproduced additional fail-open cases on the complete observer → collector →
finalizer → renderer path. Missing pipeline evidence could certify a request that had asked for a
billable OpenRouter plugin; pipeline `cost_usd`, generated-token evidence and malformed or nonzero
cost details could also be ignored. A supplement attribute getter could violate the finalizer's
non-raising contract. This correction will:

- derive only a boolean auxiliary-charge risk from the prepared request, inside the trusted
  finalizer boundary, while keeping prompts and credentials out of provider mapper inputs;
- require explicit pipeline evidence and reject request-side plugins, OpenRouter server tools and
  file parts;
- reject nonzero, null or malformed pipeline cost, output-token and customer-charge evidence;
- validate any router attempt chain conservatively and make supplement lookup non-raising;
- add independent RED cases for each reproduced path plus mutation gaps, schema negatives and
  preservation of base evidence;
- correct documentation and test claims that overstate what the installed-transport regression
  proves.

Acceptance: no reproduced counterexample can become `provider_guaranteed_zero`; positive
certification still requires affirmative zero evidence; prior tests remain unchanged and green; the
focused suite, Python 3.12 usage-accounting suite and full AIGateway gate pass against frozen base
`d578cba9e` without live or paid calls.

## Post-commit review iteration — 2026-10-07

Review of `73e70185c` returned `NOT READY` with two HIGH findings, both reproduced and fixed:

- The raw body parser kept the last of two repeated JSON object keys, so
  `"is_byok": true, "is_byok": false` or a second empty `usage` hid BYOK and a reported cost and
  certified the attempt as guaranteed zero. A repeated key at any depth now makes the body
  unavailable raw evidence.
- Zero certification ignored unknown or misplaced usage fields (`usage.server_tool_cost`,
  `usage.future_auxiliary_cost`). It now accepts only the known chat usage shape and fails closed on
  any other field, a null `cost` included.
- Docstrings no longer call every direct cost provider-authored.

Tests: `test_openrouter_proven_zero_strict_evidence.py` (RED 10 failed, 2 control passed before the
fix), including an installed LiteLLM/httpx retry with the duplicate-key 429 body. No prior test was
changed. A live OpenRouter retry smoke still needs separate authorization for a paid call.

## Final review correction iteration — 2026-10-07

Review of `d6c79c02d` found that direct `usage` key allowlisting did not validate every accepted
nested shape or router-metadata child. It also identified two compatibility boundaries: rejecting a
duplicate key globally discarded otherwise measurable evidence, and the new closed-enum value had no
wire-version signal. This iteration will:

- add RED cases for malformed token fields and nested charge evidence under usage details, pipeline
  stages, router attempts and router metadata;
- preserve parseable measured evidence from an ambiguous JSON body while marking that attempt's
  evidence incomplete, so supplements cannot certify zero and request economics stay partial;
- emit `aigw.provider_attempt.v2` only for the new provenance status, retain v1 for prior statuses,
  and give the combined schema document a versioned identity;
- rerun the focused, Python 3.12, Engine and full AIGateway gates, then independently falsify the
  complete PR before committing and pushing.

Acceptance: every reproduced nested/malformed counterexample remains unavailable; duplicate JSON
never certifies zero but does not erase unique measured cost; old attempt statuses retain their v1
wire marker; guaranteed-zero attempts carry v2; no prior test changes; all gates pass.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** updated the OpenRouter dispatch/accounting plugin, provider-neutral direct-cost
  taxonomy, mapper, schema, finalization/route seam, renderer and accounting docs; added a focused
  zero-insurance proof module and six focused
  modules: `test_openrouter_proven_zero.py`, `test_openrouter_proven_zero_observer.py`,
  `test_openrouter_proven_zero_fail_closed.py`, `test_openrouter_proven_zero_route.py`,
  `test_openrouter_proven_zero_strict_evidence.py` and
  `test_openrouter_proven_zero_metadata_shapes.py`. Engine and SDK production code are unchanged.
- **Commits:** implementation and post-review strict-evidence correction captured by the branch
  commits; exact SHAs are recorded in Git and the PR.
- **Gates:** RED was recorded as 14 expected failures before production edits, followed by targeted
  RED cases for legacy-header ambiguity, auxiliary-charge conflicts and router-metadata leakage. The
  first review correction added five expected failures for current `server_tool_use_details`,
  conflicting/malformed `usage.is_byok`, and missing/mismatched `error.code`. The 2026-10-07
  `NOT READY` correction then reproduced 27 fail-open/non-raising failures; one initial schema test had
  an incorrect JSON path and was corrected before production edits. The final four focused modules
  pass 82 tests; all 602 usage-accounting tests pass on Python 3.12; 56 read-only Engine accounting
  boundary tests pass. The final full gate is green against frozen base `d578cba9e` for append-only
  tests, Ruff check/format, Pyright, the enterprise-import guard and full pytest coverage. Mutation
  probes for response guards and the real `RateLimitError` route branch are killed. Independent
  post-correction review reports `READY`. Mirror status and `git diff --check` pass. `origin/main`
  advanced during
  final verification to `b83b96708`; rerunning the exact command against that moving ref stops at the
  append-only check on unrelated upstream admission-test changes, so this worktree was not rewritten.
- **Deviations:** initial scratch plan incorrectly used the shared checkout, stale main and a
  recommended Engine multi-source change. Corrected on 2026-10-06 with an isolated worktree from
  current `origin/main` and the `archive_matched` provenance precedent. The classifier stayed in the
  existing OpenRouter accounting module rather than adding a one-function module. A paid/live retry
  smoke was not run because it requires separate authorization. Independent review found and the
  implementation corrected auxiliary-evidence misclassification and router-metadata cache leakage;
  follow-up review then found current ChatUsage and malformed-error fail-open cases. Those are now
  rejected, and a real installed-LiteLLM/httpx observer → gateway retry → finalization → renderer
  regression protects the integration seam. The final `NOT READY` review required request-side risk,
  explicit pipeline/stage-money, token/cost-detail/attempt-chain checks and mutation-sensitive route
  coverage. Request-fact helpers landed in the existing taxonomy mapper rather than a new file because
  the architecture test fixes that package's file allowlist. The final review correction split the
  provider proof into `zero_insurance.py`, retained measured evidence for benign duplicate keys while
  making capture partial, dropped accounting-sensitive duplicate evidence across OpenRouter and
  Anthropic shapes, and versioned only the new attempt wire status. Final verification passes 116
  focused tests, 636 Python 3.12 usage-accounting tests, 78 Engine consumer tests and the complete
  AIGateway gate. Two independent final reviews report `READY`; the financial refuter checked 191
  mutation/probe cases with no unsafe pass. No live or paid call was made.
