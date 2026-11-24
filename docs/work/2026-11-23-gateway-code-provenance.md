---
ticket: OME-2010   # Engine; sibling OME-2011 (Gateway) lands in the same PR
stack: screamingface-engine, aigateway
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-23
finished:
---

# gateway-code-provenance — lift only Gateway-owned codes from an upstream error body

## Intent

`world/connector.py::_raise_for_status` lifts `detail.code` from a Gateway body, or from a proxy
in front of the Gateway, and the lifted code reaches the model-call log line
(`model call failed ... code=`) and `observation.failed()` before any route's own policy. A body
can therefore put a key, an origin, a path or a private model or deployment ID into the logs and
the observations of every chat, classification and frozen-copy call. The BYOM routing pilot
(`docs/spec/2026-11-04-byom-routing-pilot.md`, 6.1 C9) depends on this unit: it rewrites a relayed
failure's message and code on `/route-answer`, but claims no log closure for a branch code until
this lands, and does not merge before this lands or the security owner explicitly accepts the
risk (owner review, 2026-11-23). Found in the pilot's landing review on 2026-11-23 and split
out by the owner because it changes the provenance of every model call's error code.

## Starting point (uncommitted, carried over from the pilot worktree)

- `world/connector.py::_upstream_code`: a shape screen that lifted a code only when
  `public_identifier(code) == code` and `public_message(code, default="") == code`. The review
  showed that it keeps `byom_secret_deployment_alpha`, `byom-origin.internal.test:8443`,
  `hf_<32 chars>`, `ghp_<36 chars>` and `sk_live_abcdef123456`. Set aside, not shipped, on
  2026-11-24 when the branch moved from `de16e8e94` to `a5a7986ec`; `connector.py` is on main.
- `tests/unit/test_gateway_code_screen.py`: those five are RED (15 cases); the plain Gateway
  codes are green. To be rewritten for the closed rule in Phase 2.

## Design decision (owner, 2026-11-23; revised after review, 2026-11-24)

A closed Gateway-owned code vocabulary: the Engine lifts a code only when the Gateway declares
it; any other takes `aigateway_http_<status>`. A status-only fallback and a shape screen were
rejected (spec section 2). The 2026-11-24 review made parity exact, seeded `retired` from the
Gateway history, pinned the three Gateway codes the Engine reserves, made the Gateway check fail
closed on outbound sinks, and named the Engine leaf primary. A second 2026-11-24 review moved the
branch to `a5a7986ec` and set the rule for the hosted query: its values are untrusted evidence,
are never copied into the repo, and join `retired` only when traced to a fixed literal of a
deployed Gateway build. Spec: `docs/spec/2026-11-23-gateway-code-provenance.md`; plan:
`docs/plan/2026-11-23-gateway-code-provenance.md`.

Owner, 2026-11-24: spec and plan approved; implementation of Phases 1 and 2 approved.

- Q4: Q4 not run. Residual compatibility risk: a frozen copy produced by an unknown non-main
  Gateway build may replay as aigateway_http_<status> rather than preserving its original code.
  Confidentiality remains closed because no observed production value becomes trusted
  vocabulary without source provenance. It blocks neither implementation nor merge.
- Q2: the process and the strategy of spec section 4 are approved. After the full Engine run the
  owner saw each file's current blob, the exact diff and the kept status and permanence
  assertions, and on 2026-11-24 approved the six changes at their exact blobs (Planned changes).
  Any other change to them needs a new approval.

## Evidence (read-only)

Every item below was taken, or taken again, on `a5a7986ec` on 2026-11-24, after the branch moved
from `de16e8e94`. The five commits between them change frozen-copy retention (OME-1947), the
replay route, `world/connector.py` and `error_text.py`.
On 2026-11-24, before code, the branch moved again to `50375e34a`; its two commits
(OME-1999, a HubSpot doc fix) touch neither `apps/aigateway` nor
`apps/screamingface-engine`, so nothing below was retaken.
On 2026-11-24, after Phase 2, the branch was fast-forwarded to `d37932d61` (OME-1989, the
refused-key stop). It changes the Engine's `world/connector.py` (lines move by 7 to 30),
`error_text.py` (the new reserved code `provider_key_refused`) and the Gateway's
`routes/chat_dispatch.py` (logging only, no new `code`). What it could move was taken again on
`d37932d61`; the line numbers below are those of `d37932d61`.

- Gateway source: every `detail.code` is a fixed literal or comes from a fixed status-to-code
  map; no provider's own error code is copied into it. An `ast` pass finds 66 inline literal
  `code` values (one is the OAuth setting `true`), including the new `frozen_copy_expired` and
  `frozen_copy_not_sealed`, and 22 non-literal sites outside admission and OAuth, 28 with them.
  No central registry exists.
- Engine sinks of a lifted code: the observation and the model-call log line
  (`world/connector.py:310-312`), the benchmark report's `source_code`
  (`benchmarks/aggregation.py:176-181`), the run's terminal error. The HTTP problem body is
  already closed.
- Gateway history: frozen-copy capture and replay began at `f06860621` (2026-10-12). Every
  first-parent snapshot of `src/aigateway/` from there to `a5a7986ec` (70 commits) gives five
  codes written then and not now: `credential_write_conflict`, `invalid_profile_defaults`,
  `profile_auth_conflict`, `profile_conflict`, `profile_index_conflict`. A second pass over the
  removed lines of the same diffs finds the same five.
- Retention: a replay reads only sealed copies. The OME-1947 sweep deletes the entries of idle
  open copies only (`core/frozen_copy/sweep.py`); the planned expiry rule keeps each claimed
  copy. Sealed copies therefore have no end date, and `retired` stays needed.
- Overlap: the Gateway writes `frozen_copy_miss`, `frozen_copy_unavailable` and
  `result_too_large`, all three in `ENGINE_RESERVED_CODES` (`error_text.py:77-86`). No other
  Gateway code is reserved. `frozen_copy_expired` is read by `_replay_refusal` and is not
  reserved.
- Sinks: a prototype of the sink rule finds 35 `HTTPException` and 7 `JSONResponse` sites in
  `src/aigateway/` whose detail is not a literal.
- Blast radius: the Engine unit suite under the current rule passes (10302); under the closed
  rule with a candidate vocabulary, exactly six prior test functions (eight cases) fail, each on
  a code the Gateway never writes (spec section 4). The same six failed on `de16e8e94`; none of
  their files changed in between. The candidate must hold the codes the Gateway reaches through
  status maps and constants, or the run shows false failures.
- Gateway check, on `50375e34a` and again on `d37932d61` (2026-11-24): the check proves every
  site but 22; 17 are
  reviewed with their codes and 5 are not codes (the OAuth authorization code). A sixth not-code
  site, the OAuth setting `code="true"`, is a literal, so the tables list 23 sites, 17 reviewed
  and 6 not codes. It found two
  shapes the prototype missed: an `HTTPException` subclass with no `__init__` of its own
  (`plugins/openrouter_provider/dispatch_errors.py`), and a body that wraps a forwarded `detail`
  in a dict (`merged_error_detail`, the replay and accounting paths). The fixture holds 95 codes
  (the 66 inline literals counted 65 codes plus `true`; the rest are module constants, producer
  arguments and the reviewed maps) and 5 retired. The history scan, rerun on `50375e34a` and on
  `d37932d61` (71 commits), gives the same five retired codes. The final set meets
  `ENGINE_RESERVED_CODES` in exactly the three pinned codes, so `GATEWAY_CODES` holds 97; the new
  reserved `provider_key_refused` is not a Gateway code.
- Refused-key watch (OME-1989): `note_refusal` keys on statuses 401, 402 and 403 and on the
  declared codes `auth_required` and `insufficient_credits`, which are still lifted. A 403 streak
  restarts when the code changes; under the closed rule two undeclared 403 codes are both
  `aigateway_http_403` and extend one streak. `test_refused_key_stop.py` passes under the closed
  rule.
- Six prior test files: their base blobs are the same on `d37932d61` as on `50375e34a`.
- Benchmark: `aigateway_http_<status>` is a declared failure code
  (`benchmarks/contract.py:187-189`), so the fallback reaches the report as itself with no
  `source_code`.

## Planned changes

- `apps/aigateway/tests/fixtures/gateway_error_codes/codes.json` (new).
- `apps/aigateway/tests/unit/test_gateway_error_codes.py` (new).
- `apps/aigateway/tests/unit/_gateway_error_code_ast.py`, `_gateway_error_code_scan.py` and
  `test_gateway_error_code_scan.py` (new; added in Phase 1, see Deviations).
- `apps/screamingface-engine/src/screamingface_engine/world/gateway_codes.py` (new).
- `apps/screamingface-engine/src/screamingface_engine/world/connector.py` (`_upstream_code`).
- `apps/screamingface-engine/tests/unit/test_gateway_code_screen.py` and
  `test_gateway_codes_parity.py` (new).
- `.github/workflows/screamingface-engine-tests.yml` (path filters).
- With the owner's approval of exact blobs only: `test_aigateway_connector.py`,
  `test_candidate_call_retry.py`, `test_frozen_copy_replay_failures.py`,
  `test_frozen_copy_replay_unserved.py`, `test_unsupported_content_part_refusal.py`,
  `test_mount_routes.py`. Approved by the owner on 2026-11-24, base to approved blob:
  `600a57ae` to `a95788e0`, `c85b22c7` to `7d47d6eb`, `dc1a6911` to `ebde4009`, `67b73b36` to
  `27fa6c50`, `8f10af43` to `95b020e4`, `42742dae` to `d2a5057c`; any other change needs a new
  approval. The manifest that pins the full hashes is
  `.claude/test-change-approvals/OME-2010.json`, written at PR-open for the branch
  `OME-2010-gateway-code-provenance`.

## Test plan

- Every review counterexample and every path, origin, key and private ID shape takes
  `aigateway_http_<status>` at 400, 429 and 502, with permanence kept.
- Every code in `GATEWAY_CODES` is lifted unchanged; no Engine-reserved code is; an undeclared
  plain identifier is not lifted; a replayed retired code is.
- The model-call log line and the observation carry no undeclared code; the benchmark report
  gives exactly `aigateway_http_<status>` with no `source_code` for one.
- Parity is exact, with the three-code overlap pinned; the Gateway check fails on every
  synthetic shape of spec 3.2.

## Acceptance

- No upstream code outside the Gateway's declared vocabulary reaches a log line, an observation
  or a public boundary; a replayed retired code keeps its spelling; the benchmark report's relay
  contract stays green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus the three Gateway check files listed above. The six prior
  Engine tests are changed to exactly the blobs the owner approved on 2026-11-24, base to
  approved:
  - `test_aigateway_connector.py`: `600a57ae` to `a95788e0`;
  - `test_candidate_call_retry.py`: `c85b22c7` to `7d47d6eb`;
  - `test_frozen_copy_replay_failures.py`: `dc1a6911` to `ebde4009`;
  - `test_frozen_copy_replay_unserved.py`: `67b73b36` to `27fa6c50`;
  - `test_unsupported_content_part_refusal.py`: `8f10af43` to `95b020e4`;
  - `test_mount_routes.py`: `42742dae` to `d2a5057c`.

  Only code strings change: `401` `invalid_credential` to `auth_required`, `402`
  `quota_exceeded` to `insufficient_credits`, `503` `upstream_unavailable` to
  `provider_unavailable`, `502` `bad_gateway` to `provider_error`, `422` `provider_refused` to
  `unsupported_message`; the two replay tests keep `boom` and expect `aigateway_http_500`.
  Status, permanence, messages, retries and waits are unchanged. The approval manifest
  `.claude/test-change-approvals/OME-2010.json` pins these six transitions. Mirrors:
  `docs/tasks/2026-11-24-OME-2010-gateway-code-provenance.md` and
  `docs/tasks/2026-11-24-OME-2011-gateway-error-code-vocabulary.md`.
- **Commits:** three on `OME-2010-gateway-code-provenance`: the Gateway check, the Engine rule
  with the approved test changes and the manifest, and these docs. Their shas go in the close
  comment.
- **Gates (2026-11-24, on `d37932d61`, after the approval):**
  - aigateway, `run_gates.py aigateway --base origin/main`: all gates green on 3.13 (append-only
    check, ruff check, ruff format, pyright, `check_no_enterprise.py`, pytest with coverage).
    On 3.12, with the environment rebuilt on 3.12.9: the same gates, all green.
  - Engine, `run_gates.py screamingface-engine --base origin/main --skip-append-only`: ruff
    check, ruff format, pyright, the layering check and the full unit suite with coverage, all
    green on 3.13 and on 3.12. The gate runner prints no test counts for a green gate.
  - Engine append-only check before the manifest, run on its own: it flagged exactly the six
    approved files and no other. With the manifest, on `OME-2010-gateway-code-provenance`:
    each of the six is an approved OME-2010 transition, and the full
    `run_gates.py screamingface-engine --base origin/main`, with no skip, is all green on 3.13.
  - Focused, on `d37932d61`: the Gateway provenance tests, 36 passed; the Engine provenance
    tests with `test_refused_key_stop.py`, `test_terminal_error_detail.py` and the six changed
    files, 441 passed.
- **Pre-approval evidence (2026-11-24, on `50375e34a`):** the full Engine unit suite on 3.13
  gave 10479 passed, 529 skipped, 8 failed; the 8 were exactly the six prior functions of spec
  section 4, and their proposed versions, run as temporary copies, gave 176 passed. It describes
  the tree before the six changes and is not the final result.
- **Deviations:**
  - The Gateway check is three files, not one: an `ast` helper module, the scan and its
    synthetic self-test, to keep each file under 450 lines.
  - The Gateway set is 95 codes, not the 66 inline literals, because module constants, producer
    arguments and the reviewed maps write codes too.
  - Review finding (2026-11-24): `retired` was checked only as a superset of the audited list,
    so an extra plain identifier in the fixture passed and the Engine would lift it. The scan's
    `failures(retired=...)` now requires the fixture's `retired` to equal the audited list
    exactly; an extra entry and a missing one both fail
    (`test_retired_is_exactly_the_audited_set`), and the top-level test asserts equality.
  - The branch moved to `d37932d61` after Phase 2 (Evidence); no code change followed from it.
  - The Gateway check's counts: 22 sites it cannot prove (17 reviewed, 5 not codes), and 23
    listed sites (17 reviewed, 6 not codes), because the sixth not-code site is a literal.
  - The approval manifest needs the Engine leaf's number and the renamed branch, so it was
    written at PR-open; until then the Engine append-only check was red on the six files.
