# R-2026-10-12 — E14 design review fixes (owner walkthrough, 2026-10-12)

- **Source:** the owner's design review comment on the E14 epic (OME-1307), 2026-10-12. Each claim in it
  was checked against the branch heads of 2026-10-12. Section 0 gives the result.
- **Scope:** the eight open stack branches (#1330–#1337) and one new docs branch (D0, this branch).
- **Design (binding):** `docs/spec/2026-10-06-e14-reproducible-submission/02-frozen-copy-design.md` with
  the Q23–Q30 addendum, §4.2–§4.4, §5.2–§5.4, §6, §7, §9 and §10. Where this plan and an older `F-*` plan
  disagree, this plan wins. Where this plan and the design disagree, the design wins.
- **Rules:** `00-common.md`. Keep all work local. Push only on the user's word. Do not poll CI.
- **Approval:** the implementer approved Q23–Q30 and this plan on 2026-10-12, including the edits to
  existing tests that are listed below. The owner confirms Q23–Q30 on the D0 PR.

## 0. Findings map

| Review item | Verdict | Fix | Branches | Blocks merge |
|---|---|---|---|---|
| A. Local capture is partial | Confirmed. A clean local capture reads `complete`. The C1 docs say so. | Q23 | B3, B5, C1 | Yes |
| B. Public last-edit time | Confirmed. Not in the spec before. | Q24 | A1, C1 | Yes |
| 1. Private-board replay | Confirmed. Q16 already decides it. | Q25 and a regression test | D0, B4 | No |
| 2. Faked tool results | Confirmed. The engine forwards the user's identity, so a user can post results. | Q26, docs, FU-1 | D0, C1 | No |
| 3. Per-case exact | Confirmed. New requirement. | Q29 (SDK digest) | B4, B5, C1 | No (done now: a digest not stored at submit is lost) |
| 4. Runs over time | Confirmed. Not in the stack. | FU-3 | none | No |
| 5. Replay ordering | Confirmed. Replay used send order, capture used completion order. | Q27 call key | B1, B3, C1 | Yes |
| 6. Upgrades break replay | Confirmed. No version was stored. | Q28 engine version at seal, FU-4 | B1, B3 | Yes (record only) |
| 7. Deleting copies | Confirmed. | FU-2 | none | No |
| #1332 blockers 1 and 2 | Fixed in `ee4c6c3ce` (origin B3, was local `76b4ffd3c`). | Keep blocker 1's fix. Q27 removes the slot release. | B3 | Yes |
| New: Tavily cache poisoning | Confirmed (`apps/aigateway/DEPLOYMENT.md:486-487`). | Q30 | B2 | Yes |
| Stack shape | A1 does not descend from the current B3. | Phase 0 | A1…C1 | Yes |

## 0a. Interim stated-occurrence commits on origin B1 and B3 (2026-10-12, after this plan)

The replay-ordering bug of the #1330 review (must-fix 2) was fixed upstream of this plan with the
reviewer's option (a) in strict form — the engine states the slot it reserved at send:

- B1 `91b352d7b`: `capture()` stores the stated slot (header `X-AIGW-Capture-Occurrence`);
  `find()` serves replay successes by stated occurrence, per-digest fallback to `seq` for unstated
  entries; entries carry a nullable `occurrence`; `(frozen_copy_id, seq)` is unique (the #1330
  follow-up), which Phase 2 here replaces.
- B3 `3e5ee45eb` (on `ee4c6c3ce`): both capture lanes state their slot; the capture path never
  gives a slot back — a slot a non-stored call left unused collapses on replay.
- Where the two commits and the Q27 refinement differ, the refinement wins: the call key moves to
  headers, the occurrence counts logical calls (every transport attempt shares it) and is never
  given back, the column is `int not null default 0` with the
  `(frozen_copy_id, kind, case_key, request_digest, occurrence)` index (not unique),
  `X-AIGW-Capture-Occurrence` and `X-AIGW-Replay-Occurrence` are both replaced, and the lookup rule
  becomes §4.4's latest-success-else-latest-error. The Phase 2 edits below remain the binding work;
  they replace the interim header and drop the `(frozen_copy_id, seq)` uniqueness.
- The #1330 review's "a malformed `cache` field drops the Attempt number" find dissolves under this
  plan: the call key travels in headers, not in the request's `cache` object that
  `prepare_ingress_body` strips.

## 1. Phase 0 — restack (no behaviour change)

State on 2026-10-12 13:00: B1, B2 and B3 on origin are already rebased onto `main` `ba2d825f2`, and B3
carries the #1332 fixes (`ee4c6c3ce`). A1…C1 still sit on the older B3.

1. Make sure no other session works in the E14 worktrees. Run `git -C <worktree> status` in all of them.
2. Back up every local and origin E14 tip under `refs/e14-backup/pre-review-2026-10-12/<branch>`.
3. Fast-forward or reset local B1, B2 and B3 to origin. Check first that no local-only commit is lost
   (`git cherry origin/<b> <b>` shows only `-`).
4. Rebase B1 onto D0 (B1's base becomes D0). B2 and B3 follow with `--update-refs`.
5. Repair A1: find A1's own commits (`git cherry <B3> OME-1433-e14-a1-scoreboard-metadata` and the
   subjects in `A1-scoreboard-metadata.md`). Then `git rebase --onto <B3> <last non-A1 commit>` with
   `--update-refs` from the C1 tip, so B4, A2, B5 and C1 follow. `--update-refs` skips a ref that
   another worktree has checked out, so detach those worktrees first and switch them back after.
6. B5 carries `18ffd1f94` (Q22 text). D0 holds the same change, so the rebase drops it or the conflict
   resolves to D0's text.
7. Run the gates on every branch (commands in Phase 2).

## 2. Phase 1 — D0 (this branch)

- **Branch:** `OME-1307-e14-design-review` · **Worktree:** `.claude/worktrees/e14-d0-design-review` ·
  **Base:** `main` · **Stack:** docs.
- **Files:** `02-frozen-copy-design.md` (Q22 from `c7158dad7`, Q23–Q30, §3, §4.2–§4.4, §5.2–§5.4, §6, §7,
  §8, §9, §10), this plan, the ledger `docs/work/2026-10-12-e14-design-review.md`.
- **PR-open (not now):** ask the user first. Then file a Linear leaf under OME-1307, self-assigned, add
  the `docs/tasks/` mirror and `Refs: OME-N`.

## 3. Phase 2 — per-branch changes

After each branch: restack the chain above it and run that branch's gates. The work on B1, B2, B3,
A1, B4 and B5 touches separate files, so it runs in parallel in each worktree. C1 goes last.

### B1 — #1330 gateway (OME-1434) · decisions Q25, Q27, Q28

- **Worktree:** `e14-b1-gateway-frozen-copy` · **Base:** D0 · **Stack:** `aigateway`

| File | Change |
|---|---|
| `src/aigateway/migrations/0014_frozen_copies.py` | Amend in place (unreleased). Entries: add `case_key` varchar(32) not null default `""` and `occurrence` int not null default 0. Index `(frozen_copy_id, kind, case_key, request_digest, occurrence)`, not unique. Copies: add `provenance` JSON null. |
| `src/aigateway/core/frozen_copy/models.py` | The same fields. |
| `src/aigateway/core/frozen_copy/headers.py` | `CASE_KEY_HEADER = "X-AIGW-Case-Key"`, `OCCURRENCE_HEADER = "X-AIGW-Call-Occurrence"`, one parser for both (design §4.2). |
| `src/aigateway/core/frozen_copy/store.py` | `capture(..., case_key, occurrence)`. `find(copy, kind, request, case_key, occurrence)` per design §4.4: latest success, else latest error, else `None`. `seal(..., provenance)`; a repeat seal keeps the first provenance. |
| `src/aigateway/routes/chat.py` | Capture reads both key headers. A bad or missing key → `refused`. |
| `src/aigateway/routes/frozen_copies.py` | Replay, tool lookup and tool-results capture read both key headers; bad → 400 `malformed_call_key`. Remove `X-AIGW-Replay-Occurrence` and `malformed_replay_occurrence`. Seal takes the optional provenance body (design §4.3). |
| `tests/unit/test_frozen_copy_*.py` | New tests below. Lookup-rule and occurrence tests change (approved, see the header). |

TDD (risk order):
1. `same_request_in_two_cases_replays_each_case_its_own_answer`
2. `completion_order_does_not_change_replay` (occurrence 1 stored before occurrence 0)
3. `replay_returns_the_latest_success_at_the_key_else_the_latest_error_else_miss`
4. `no_fallback_to_another_occurrence_or_case_key`
5. `bad_or_missing_key_headers`: capture `refused`; replay and tool routes 400 `malformed_call_key`
6. `tool_results_capture_and_lookup_use_the_key`
7. `seal_stores_provenance_and_keeps_the_first`; `unknown_key_or_bad_value_is_422`
8. `replay_occurrence_header_is_gone` (the old header has no effect)
9. Migration applies on SQLite and Postgres; model and migration match.

**Verify:** `uv run .claude/scripts/run_gates.py aigateway --base OME-1307-e14-design-review`

### B2 — #1331 Tavily cache (OME-1045) · decision Q30

- **Worktree:** `e14-b2-engine-tavily-cache` · **Base:** B1

| File | Change |
|---|---|
| `apps/aigateway/src/aigateway/routes/tavily_retrieval_cache.py` | `_key_hash` mixes in the caller's account id (`CurrentAccount`) for lookup and fill. |
| `apps/aigateway/DEPLOYMENT.md` (around 462-500) | Replace "Identity never enters the key" with the account-scope rule and its reason (Q30). |

TDD: `fill_by_one_account_is_a_miss_for_another`, `same_account_hit_is_unchanged`,
`key_is_still_derived_server_side`.

**Verify:** `run_gates.py aigateway` and `run_gates.py screamingface-engine`, both with
`--base OME-1434-e14-b1-gateway-frozen-copy`.

### B3 — #1332 engine (OME-1435) · decisions Q23, Q27, Q28

- **Worktree:** `e14-b3-engine-frozen-copy` (origin `ee4c6c3ce` or later) · **Base:** B2 · **Stack:** `screamingface-engine`

| File | Change |
|---|---|
| `src/screamingface_engine/capture_outcomes.py` | Header constants for the key (design §5.4); remove `REPLAY_OCCURRENCE_HEADER`. `CaptureTally`: `local: bool = False`; `_REASONS` gets `"local"`; `status()` is `partial` when `local`; `attributes()` counts `capture.partial.local`. Replace `slots`/`freed`/`reserve`/`release` with `next_occurrence(case_key, lane, digest) -> int` (never given back). `_lost()`: every outcome that is not `stored` is lost (D2 removed). Keep the `ambiguous` rules. Add `case_key_for(case_id) -> str` (design §5.4). |
| `src/screamingface_engine/world/connector.py` | `_recorded_completion` takes the occurrence once per logical call and sends both key headers with `X-AIGW-Frozen-Copy`; every transport attempt reuses them. The replay fetch sends the same key. Remove the release on failure. `seal_frozen_copy` sends `{"provenance": {"engine_version": ...}}`. |
| `src/screamingface_engine/world/web_tools.py` | Tool-result capture and lookup send the key. Take the occurrence before the first `await` of each gathered task. |
| `src/screamingface_engine/benchmarks/case_context.py` | `current_case_key() -> str`: the candidate case from `case_scope`; else the grading case when it can be resolved (`grading_call_scope.current_grading_case`); else `""`. |
| `src/screamingface_engine/__init__.py` | `__version__ = importlib.metadata.version("screamingface-engine")`. |
| `src/screamingface_engine/runner/executor.py` (`_bind_frozen_copy_mode`) | Set `tally.local` when the run executes on the local runtime. No flag exists today: add a job-env marker that `local.py` (`_install_local_node` / `create_local_app`) sets for every run it starts, and read it here. |
| Tests | New tests below. Existing occurrence, release and overlap tests change (approved). |

TDD (risk order):
1. `capture_and_replay_send_the_same_key_sequence` (end to end with a fake gateway)
2. `same_request_in_two_concurrent_cases_takes_occurrence_0_in_each`
3. `transport_retries_of_one_call_reuse_its_occurrence`
4. `a_new_logical_call_takes_the_next_occurrence_and_it_is_never_given_back`
5. `gathered_identical_tool_calls_take_occurrences_in_task_creation_order`
6. `grading_call_uses_the_grading_case_key_or_empty`
7. `local_runtime_capture_is_partial_with_reason_local`; `hosted_capture_is_unchanged`
8. `an_unstored_error_is_no_longer_forgiven`
9. `seal_sends_the_engine_version`
10. The `ambiguous` tests from `ee4c6c3ce` still pass.

**Verify:** the `F-B3-engine-capture-replay.md` verify line with `--base OME-1045-e14-b2-engine-tavily-cache`.

### A1 — #1333 scoreboard metadata (OME-1433) · decision Q24

- **Worktree:** `e14-a1-scoreboard-metadata` (after the Phase 0 repair) · **Base:** B3

| File | Change |
|---|---|
| `apps/scoreboard/portal/spec.js` | Show "Metadata edited <date>" next to the paper link when `score.metadata_updated_at` is set. The score fetch already returns it. Use the date format of `last_reproduced_at`. No API change. |

TDD: the portal test harness if one exists; `public_score_detail_returns_metadata_updated_at_to_an_anonymous_caller`.

**Verify:** `uv run .claude/scripts/run_gates.py scoreboard --base OME-1435-e14-b3-engine-frozen-copy`

### B4 — #1334 scoreboard frozen copy (OME-1433) · decisions Q25, Q29

- **Worktree:** `e14-b4-scoreboard-cache-version` · **Base:** A1

| File | Change |
|---|---|
| `scores/migrations/0020_score_frozen_copy.py` | Amend in place: `case_digest` CharField(64) null. |
| `scores/models/score.py` | The same field. |
| `scores/schemas.py` | `ScoreSubmission.case_digest` (64 lowercase hex, optional, needs `capture_status`, fill-only on a same-owner resubmit). `ScoreSchema.case_digest` (omitted when null). `ReproductionSubmission.case_digest` (optional). |
| `scores/store.py` | Fill-only rule includes `case_digest`. Reproduction rows do not store a digest (no new column there). |
| `routes/scores.py` `_refuse_unless_exact` | If the score has `case_digest`, the body must carry an equal one, else 422 `not_exact`. |

TDD:
1. `reproduction_with_matching_case_digest_is_recorded`
2. `reproduction_with_a_different_or_missing_case_digest_is_422_not_exact`
3. `score_without_digest_keeps_the_three_field_rule`
4. `case_digest_without_capture_status_or_malformed_is_rejected`; `resubmit_fills_only_an_empty_case_digest`
5. `private_board_copy_id_never_reaches_a_non_owner` (score detail, leaderboard rows, history; Q25)

**Verify:** `uv run .claude/scripts/run_gates.py scoreboard --base OME-1433-e14-a1-scoreboard-metadata`

### A2 — #1335 SDK metadata (OME-1436)

No change. Restack only.

### B5 — #1336 SDK (OME-1436) · decisions Q23, Q29

- **Worktree:** `e14-b5-sdk-reproduce` · **Base:** A2

| File | Change |
|---|---|
| `_engine/contract.py` | Read the `capture.partial.<reason>` keys into `capture_partial_reasons` (sorted names with a non-zero count). |
| `report.py` `CandidateResult` | Public `capture_partial_reasons: tuple[str, ...]` (default `()`). |
| new helper (for example `_case_digest.py`) | `case_digest(cases) -> str` per design §7. |
| `_scoreboard/leaderboards.py` | `_capture_fields` sends `case_digest` (only with a capture status). `_reproduction_payload` sends the replay's digest. Score decode reads `case_digest`. |
| `_reproduction.py` | `_classify`: equal score and count but different digests → `failed`, reason `cases_differ` (only when the score has a digest). `_not_reproducible`: a local partial says that the copy exists only in the local gateway. |
| `tests/public_surface_snapshot.json` | Regenerate (standing approval). |

TDD:
1. `case_digest_is_stable_and_order_independent`, `changes_when_one_grade_or_status_changes`, `int_and_str_ids_differ`
2. `submit_sends_case_digest_with_the_capture_fields`
3. `reproduce_sends_the_replay_case_digest`
4. `cases_differ_when_digests_differ_but_score_is_equal`
5. `score_without_digest_reproduces_on_three_fields`
6. `local_partial_reason_shows_on_the_result_and_in_not_reproducible`

**Verify:** `uv run .claude/scripts/run_gates.py screamingface --base OME-1436-e14-a2-sdk-metadata` and the
second variant in `F-B5-sdk-capture-reproduce.md`.

### C1 — #1337 docs (OME-1556) · decisions Q23–Q30

- **Worktree:** `e14-c1-docs` · **Base:** B5

| File | Change |
|---|---|
| `public-docs/src/pages/learn/CachingPage.vue` | "Local runs": local capture is partial (Q23). The tool-result sentence near line 88: add the Q26 trust statement. "Replay from the copy": the call key (Q27). "When a replay fails": drop the local `frozen_copy_unavailable` case; add `cases_differ`. Exact includes the case digest (Q29). |
| `public-docs/src/pages/sf-client/api/LeaderboardsPage.vue` | Reason table: `cases_differ`; `not_reproducible` for a local capture. |
| `public-docs/src/pages/sf-client/api/CandidateResultPage.vue` | `capture_partial_reasons`. |
| Leaderboard learn page | "Metadata edited" (Q24). |
| `CONTEXT.md` | Capture Status: a local capture is partial. Reproduction: exact includes the case digest. |

**Verify:** public-docs build, lint and tests, and `prettier --check`.

## 4. Phase 3 — close out

1. Restack the whole chain. Run the gates on every branch. Run the e2e lane at the C1 tip if Docker is up.
2. Each branch: update its `docs/work/` ledger (a "Review round 2026-10-12" section, approved test edits).
3. Each branch: a design-reviewer pass with this plan and the design as the rubric.
4. Stop. Push, PR updates, the D0 PR, Linear filing and the reply to the owner wait for the user.

## 5. Follow-ups

FU-1…FU-5 are in design §10. File them only with the user's consent, under OME-1307 (FU-3 under OME-1319).

## 6. Routing

Opus plans and reviews; Sonnet implements (E14 routing). One implementer per branch, then one
design-reviewer pass.
