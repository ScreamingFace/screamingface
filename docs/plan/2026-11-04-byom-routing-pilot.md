# Plan: BYOM routing pilot, one routed answer

Spec: `docs/spec/2026-11-04-byom-routing-pilot.md`. Ledger:
`docs/work/2026-11-04-byom-routing-pilot.md`. Branch `OME-1822-byom-routing-pilot` from
origin/main `89e6acfeb`. Stacks: `screamingface-engine`, `screamingface`. Epic `OME-1306`,
leaves `OME-1822` (Engine) and `OME-1823` (SDK).

## Preconditions

- Spec approved with edits on 2026-11-04; decisions D1 to D7 in spec section 6.
- The two leaves filed before Phase 1 (D5); the branch renamed to `OME-N-<desc>` before the
  approval manifest, because the manifest pins the branch name.
- No Tortoise model, query or migration change.
- Gates one stack at a time, from the worktree root:
  `uv run .claude/scripts/run_gates.py <stack> --base origin/main`. Before each run, check for a
  foreign pytest run; after an external process installs extras into a venv, `uv sync --dev`.
- Every prior test stays unchanged. A red prior test is a finding to raise, not to edit.

## Phase 1: Engine profile configuration (TDD)

New `tests/unit/test_routing_config.py`, written first and red:

- a valid `general`, `code`, `math` profile parses, with branches in file order and the
  revision format;
- the revision is equal for equal files and differs when any bound value changes;
- one test per rule R1 to R7 of spec 3.1, each naming the profile and key, never a value,
  including a fourth label, a missing label, `temperature` and a boolean `max_tokens`;
- a world without `[routing]` parses exactly as before.

Then `world/routing_config.py` and the `routing` key and field in `world/config.py`.

## Phase 2: Engine endpoint (TDD)

New test files, red first, driven through the real executor (direct run) with a fake Gateway
that records every request by path, model, identity headers and body:

- `tests/unit/test_routing_endpoint.py`: steps 1 to 9 of spec 3.3. Each label selects its
  branch with zero calls to the others; the input reaches the classifier and the branch byte for
  byte (quotes, `)`, `!`, `&`, `%41`, newlines, non-ASCII); the branch body holds one user
  message, the bound `max_tokens` and no other parameter, and no tools; tie, extra, missing and
  renamed labels, wrong model or contract (relayed from Unit 3, spec 6.1 C1);
  `classifier_not_found` and an
  ungranted branch both become `routing_profile_not_found` without naming a path; relayed
  classifier and branch errors; seed, capture and replay refused before any Gateway call;
  envelope-shaped and empty inputs refused; cancellation during classification never calls a
  branch.
- `tests/unit/test_routing_preflight.py`: every preflight outcome of spec 3.3 step 4, each with
  zero inference calls, including a `max_tokens` above the published `maximum`, a disabled
  `max_tokens` rule, an ungranted later branch hiding an earlier pending Connection, and a
  transient read.
- `tests/unit/test_routing_world.py`: the route is a direct mount on a cold world and on the
  shared warm world; a declared model at `/route-answer` fails composition; preflight and
  startup call no model; the cold and warm revisions are equal.
- `tests/unit/test_routing_run_cost.py`: a routed run with a priced branch stays unpriced; its
  one span frame is unpriced with the branch's own token counts; a control shows the branch's
  answer alone is priced (spec 6.1 C2).
- `tests/unit/test_routing_mount.py`: through the App, statuses of spec 3.5, `414`, undecodable
  escapes refused before a run, and no profile ID in `/openapi.json` or a metric label.

Then `world/routing.py`, `_install_routing` in `world/gateway_endpoints.py` (spec 6.1 C3), the
undecodable-escape route table in `rest/mounts.py`, `ROUTING_STATUS` in `world/serving.py`, and
`ROUTING_CODES` in `error_text.py` (spec 6.1 C6). Gate `screamingface-engine`.

## Phase 3: SDK call (TDD)

- Move the transport to `_engine/direct_get.py`. `tests/test_classify.py` stays unchanged and
  must stay green: it is the regression proof for the move.
- New `tests/test_route_answer.py` and `tests/test_route_answer_errors.py`, with shared helpers
  in `tests/_route_answer_fixtures.py`, red first, against a fake Engine: path and envelope bytes;
  size and Unicode refusals before any request; one GET only, never re-sent; `Prefer: wait=60`
  and the 75 s read; every decoder rule of spec 3.6, each refused alone (wrong object, contract,
  policy or classification contract; another profile; a bad revision; a duplicate or empty
  label; a boolean, infinite or out-of-range score; a selected label that is not the unique
  maximum); every row of the spec 3.6 table; the artifact path rule and the one re-fetch after an
  Access login.
- Then `_engine/routed_answer.py`, `routing.py`, `Client.route_answer`, the export, and the
  `CHANGELOG.md` entry.
- Regenerate `tests/public_surface_snapshot.json` on the branch base, adding only
  `RoutedAnswer` with its `__init__`, its `__all__` entry and `Client.route_answer`. Pin both
  blobs in `.claude/test-change-approvals/OME-1823.json`. Gate `screamingface`.

## Phase 4: loopback integration (outside Git)

- Rebuild the wrapper for `model_router_v1` from the 2026-11-03 prototype, with offline tests:
  exact body, fixed question, extra fields refused, auth before I/O, native order and ties kept,
  malformed labels and scores, the byte bound, no redirect or key leak.
- A loopback harness: a real Gateway with an isolated SQLite store, admin attach of fake keys,
  grants for caller A only, a fake Laya and three fake experts that record destination, role and
  key match; the Engine in local mode, cold and warm; the SDK method. Caller A gets each label's
  answer; caller B is refused before any model call; a missing Connection is refused.
- No live endpoint, no production setting, no real key.
- The ledger records the bundle's location, the commands that start it and their results.

## Phase 5: live pilot (blocked on spec section 7)

Only after the operator supplies every input of spec section 7 and approves a window:
one smoke per chat endpoint, then routing only through `Client.route_answer`, with the chat
cache opted out to count sends. A labelled set of 30 short English questions, 10 per role, then
ambiguous and negative cases. Record expected and selected role, model, native scores, answer,
latency per phase and available usage; report wrong routes and unknown cost honestly. Stop only
pilot processes, delete the temporary store, scan artifacts for keys.

## Phase 6: hosted proof (separate)

A Linux, NATS and JetStream environment with real workers and authentication repeats the SDK
call. Local evidence does not pass this gate. Hosted readiness is not claimed before it.

## Done

Phases 1 to 3 green on both stacks with the diff reviewed; Phase 4 evidence recorded in the
ledger; Phases 5 and 6 either done or explicitly pending. Merge waits for the
`gateway-code-provenance` unit to land, or for the security owner's explicit acceptance of its
known risk (spec 9; owner review, 2026-11-23).
