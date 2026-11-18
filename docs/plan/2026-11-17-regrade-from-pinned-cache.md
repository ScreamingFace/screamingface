# Re-grade from a pinned cache — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Amended 2026-11-18 (owner):** Task 5's bump of the 47 revisions was built here, then moved to OME-1958's PR so it deploys right before the batch re-grade. This PR keeps Tasks 0-4 and Task 5's docs.

**Goal:** a ScreamingFace team member can move an old leaderboard entry onto its Benchmark's bumped revision by replaying the entry's pinned cache under the new grading, at no Candidate cost, and the PR that adds this also bumps the 47 revisions OME-1907's grader change touches.

**Architecture:** the Engine catalogue serves, per Benchmark, the old revisions it may be re-graded from; each is declared on the row with that revision's Case Digest, and assembly refuses a declaration whose digest no longer matches (so "same Cases" is checked at build time). The SDK's `Client.regrade(score_id)` rebuilds the published run's url4 against the current catalogue (the partial-replay rebuild, `_replay_partial.py`), replays it from the pinned cache, refuses on any cache miss, and posts the result to a new Scoreboard route that creates a linked entry credited to the original submitter. An optional live-judge header sends chosen Cases' judge calls live while every Candidate call still replays.

**Tech Stack:** Python 3.12, uv; Engine (FastAPI, url4, inspect_ai extra), SDK `packages/screamingface` (httpx), Scoreboard (FastAPI, Tortoise ORM + migrations).

**Spec:** [OME-1909](https://linear.app/openmined/issue/OME-1909/re-grade-an-old-leaderboard-entry-from-its-pinned-cache-after-a) (design on the ticket: TLDR, decisions of 2026-11-17, Data Flow, Architecture, agent notes) and the revision rule in `apps/screamingface-engine/docs/adding-an-imported-benchmark.md` ("Changing a Benchmark's published revision", changed in commit `4856d193d`).

## Global Constraints

- One PR, stacked on #1783 (branch `OME-1907-wrapped-answer-letter`); title `feat(screamingface-engine): re-grade an old entry from its pinned cache, and bump the 47 revisions (OME-1907, OME-1909, PR 2 of 2)`. #1783 keeps its revisions held; this PR bumps them.
- Landing: merge this PR into #1783's branch, then squash #1783 into main, so prod never serves the new grader under an old revision.
- A re-grade makes **no Candidate model call**. Any `frozen_copy_miss` on a Candidate call refuses the whole re-grade: no partial score, no submit.
- Judge calls go live only when the caller names them (`live_judge=`); otherwise every judge call replays too.
- Who may re-grade: identities listed in the Scoreboard setting `regrade_identities`; the route refuses everyone in `auth_mode="disabled"`.
- The new entry: `submitted_by` and `authors` copied from the source score; `regraded_from` = source id (unique per source and revision, so the root can be re-graded again under each later revision); `regraded_by` = caller; `frozen_copy_id` NULL (the column is unique and belongs to the source).
- Revision, not grade: the score's own `case_digest` hashes grades and is never compared for a re-grade.
- Prior-test edits carry `.claude/test-change-approvals/OME-1909.json` (byte-exact, `.claude/scripts/approved_test_changes.py`).
- Repo conventions: plain `test_` functions, typed locals, a one-line intuition docstring on every function, `uv run --isolated` for tests, no `Co-Authored-By`, stage explicit paths.

## Review Focus

1. **A Fusion entry** (several members plus a synthesiser): the rebuilt url4 must keep the whole Candidate part byte-identical and change only the Benchmark part. Pinned in Task 4 with a Fusion url4.
2. **An entry already on the current revision** (re-graded once, or submitted after the bump): refuse before any run, `already_current`. Task 4.
3. **A partially captured entry** (`capture_status="partial"`) or one with no pinned cache: refuse before any run, reusing `_not_reproducible`. Task 4.
4. **Two people re-grade the same entry at once:** the second gets 409 `already_regraded`, from the unique (`regraded_from`, `benchmark_revision`) index, not from a read-then-write check. Task 3.
5. **A private entry** the caller cannot read: refuse with the Scoreboard's own 404, never a silent skip. Task 4.

---

### Task 0: Revision rule (done)

Commit `4856d193d`: the rule doc, the `benchmark-bump` warning and checklist, and the fingerprint test's message now say a grading change moves the published revision. The approval entry for the fingerprint test's message edit is added in Task 5 with the other prior-test edits.

### Task 1: Engine — declare and serve the revisions a Benchmark may be re-graded from

**Files:**
- Modify: `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py` (`BenchmarkSpec` near `:246`; `_assemble`)
- Modify: `apps/screamingface-engine/src/screamingface_engine/benchmarks/definition.py` (`Benchmark` fields; `to_dict` near `:386`)
- Test: `apps/screamingface-engine/tests/unit/inspect/test_regradable_from.py` (new)

**Interfaces:**
- Produces: `BenchmarkSpec.regradable_from: tuple[tuple[str, str], ...] = ()`: pairs of (old published revision, that revision's Case Digest). `Benchmark.regradable_from: tuple[str, ...] = ()`. The catalogue entry and resource carry `"regradable_from": [<old revision>, …]`.
- Not identity: neither field enters the fingerprint or the revision (like `description`).

- [ ] **Step 1: Write the failing tests**

```python
def test_a_row_lists_the_old_revisions_it_may_be_regraded_from() -> None:
    """The catalogue entry names each old revision whose Cases match the current ones."""
    benchmark = _assembled(regradable_from=(("145edec84bfc2324", _CURRENT_DIGEST),))
    assert benchmark.to_dict()["regradable_from"] == ["145edec84bfc2324"]

def test_a_row_whose_cases_changed_since_the_old_revision_is_refused_at_assembly() -> None:
    """INVARIANT: a re-grade is only for the same Cases; a stale digest fails the build."""
    with pytest.raises(ValueError, match="Case Digest"):
        _assembled(regradable_from=(("145edec84bfc2324", "0" * 64),))

def test_regradable_from_moves_no_fingerprint() -> None:
    """Declaring old revisions changes nothing a score depends on."""
    assert _fingerprint(regradable_from=(("145edec84bfc2324", _CURRENT_DIGEST),)) == _fingerprint()

def test_no_declaration_serves_an_empty_list() -> None:
    assert _assembled().to_dict()["regradable_from"] == []
```

`_assembled` / `_fingerprint` assemble one real catalogue row (mmlu_pro) with a replaced spec; `_CURRENT_DIGEST` is that row's `cases_spec.case_digest`.

- [ ] **Step 2: Run, expect FAIL** — `cd apps/screamingface-engine && uv run --isolated --extra inspect pytest -q tests/unit/inspect/test_regradable_from.py` → fails on the unknown field.
- [ ] **Step 3: Implement.** Add the two fields; in `_assemble`, for each pair compare the digest with `cases_spec.case_digest` and raise `ValueError("<key>: regradable_from <rev> names Case Digest <x>, the Cases now digest to <y>")`; pass the revisions to `Benchmark`; add the key to `to_dict`. Keep it out of the fingerprint builder (`benchmarks.py:~8611-8640`).
- [ ] **Step 4: Run, expect PASS**, plus `tests/unit/inspect/test_benchmark_fingerprints.py` and `test_published_revisions.py` unchanged-green.
- [ ] **Step 5: Commit** `feat(screamingface-engine): serve the old revisions a Benchmark may be re-graded from`.

### Task 2: Engine — send chosen judge calls live during a replay

**Files:**
- Modify: `apps/screamingface-engine/src/screamingface_engine/request_scope.py` (header constant, parser beside `frozen_copy_mode_from_headers` `:269`, `RequestScope.replay_live_judge`)
- Modify: the path `X-Replay-Frozen-Copy` already travels: `rest/routes.py:464,866`, `job_env` (`FROZEN_COPY_ID` beside it), and wherever the job rebuilds its `RequestScope`
- Modify: `apps/screamingface-engine/src/screamingface_engine/world/connector.py` (`_recorded_completion` `:1414`)
- Test: `apps/screamingface-engine/tests/unit/test_replay_live_judge.py` (new)

**Interfaces:**
- Produces: header `X-Replay-Live-Judge`, value `all` or a comma list of Case ids; `RequestScope.replay_live_judge: frozenset[str] | Literal["all"] | None = None`; `parse_live_judge(raw: str | None, replay: str | None) -> frozenset[str] | Literal["all"] | None`, raising `FrozenCopyHeaderError` when sent without `X-Replay-Frozen-Copy` or blank-listed.
- Rule in the connector: in a replay run, a call made while `current_grading_case()` is set and the scope names that Case (`str(case)` in the set, or `"all"`) goes through `_fetch_completion` (live); every other call, every Candidate call included, keeps `_fetch_replay`.
- Live judge calls are not captured (the Engine refuses capture with replay): a re-judged entry has no pinned cache of its own. Declared as a known limitation on the ticket.

- [ ] **Step 1: Write the failing tests**: `test_a_named_cases_judge_call_goes_live_during_a_replay`, `test_a_candidate_call_always_replays_even_when_its_case_is_named`, `test_all_sends_every_judge_call_live`, `test_live_judge_without_a_replay_is_refused`, `test_a_blank_live_judge_list_is_refused`. Assert on which fetch function the connector called (patch `_fetch_completion` / `_fetch_replay`).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** the parser, the scope field, the carrier through the job env exactly as `X-Replay-Frozen-Copy` travels, and the connector branch.
- [ ] **Step 4: Run, expect PASS**, plus `tests/unit/test_request_scope*.py` and the existing frozen-copy replay connector tests (`git grep -l _fetch_replay apps/screamingface-engine/tests`).
- [ ] **Step 5: Commit** `feat(screamingface-engine): let a replay send chosen Cases' judge calls live`.

### Task 3: Scoreboard — the re-grade route

**Files:**
- Create: `apps/scoreboard/src/scoreboard/scores/migrations/0024_score_regraded_from.py`
- Modify: `apps/scoreboard/src/scoreboard/scores/models/score.py` (two fields), `apps/scoreboard/src/scoreboard/config.py` (`regrade_identities: tuple[str, ...] = ()`), `apps/scoreboard/src/scoreboard/routes/scores.py` (new route beside `record_reproduction` `:764`), the score read schema (expose `regraded_from`)
- Test: `apps/scoreboard/tests/unit/scores/test_regrade_route.py` (new)

**Interfaces:**
- Produces: `POST /v1/scores/{source_id}/regrades`, body = the normal `ScoreSubmission`, identity via `VerifiedIdentity` (`routes/dependencies.py:58`), returns 201 + `ScoreSchema`. Columns: `regraded_from` (nullable UUID FK to scores, unique together with `benchmark_revision`), `regraded_by` (nullable `CharField(255)`).
- Refusals, in order: `auth_mode="disabled"` → 403 `regrade_unavailable`; identity not in `regrade_identities` → 403 `not_allowed`; unknown source → 404 `unknown_score`; body `benchmark_id` differs from the source's → 422 `different_benchmark`; body `total_questions` differs from the source's → 422 `different_case_count`; body `benchmark_revision` is not the board's registered revision, or equals the source's → 409 `not_current_revision`; second re-grade of one source at the same revision → 409 `already_regraded` (unique violation caught, not pre-read).
- The created row: `submitted_by`, `authors` from the source; `regraded_from`, `regraded_by` set; `frozen_copy_id`, `capture_status` NULL; `verified_by_screamingface` copied from the source.

- [ ] **Step 1: Write the failing tests**: one per refusal above, plus `test_a_regrade_is_credited_to_the_source_submitter_and_names_who_regraded_it` (asserts `submitted_by == source.submitted_by`, `regraded_by ==` the test's caller identity, `regraded_from == source.id`) and `test_the_regraded_entry_ranks_under_the_new_revision_and_the_source_does_not`.
- [ ] **Step 2: Run, expect FAIL** — `cd apps/scoreboard && uv run --isolated pytest -q tests/unit/scores/test_regrade_route.py`.
- [ ] **Step 3: Implement** the migration (two nullable columns, unique index on (`regraded_from`, `benchmark_revision`); passes `check_rollback_safety.py`), the fields, the setting, the route.
- [ ] **Step 4: Run, expect PASS**, plus the migration test the app already has (`git grep -l "0023_baseline_history" apps/scoreboard/tests`) and `tests/unit/scores/test_reproduction*.py`.
- [ ] **Step 5: Commit** `feat(scoreboard): accept a re-grade of a score, linked to it and credited to its submitter`.

### Task 4: SDK — `Client.regrade`

**Files:**
- Create: `packages/screamingface/src/screamingface/_regrade.py`
- Modify: `packages/screamingface/src/screamingface/client.py` (`Client.regrade`, `AsyncClient.regrade`), `_engine/catalog_contract.py` (`_BenchmarkEntry.regradable_from`), `_evaluation/benchmark.py` (resource decode), `_scoreboard/leaderboards.py` (`_submit_regrade` sync/async, path `f"{_SCORES_PATH}/{source}/regrades"`, payload from `_submission`), `_evaluation/url4.py` / transport only if `X-Replay-Live-Judge` needs a parameter beside `replay_frozen_copy`
- Test: `packages/screamingface/tests/unit/test_regrade.py` (new)

**Interfaces:**
- Consumes: Task 1's `regradable_from` on the catalogue entry; Task 2's header; Task 3's route.
- Produces: `Client.regrade(score_id: UUID | str, *, live_judge: Sequence[str] | Literal["all"] | None = None, on_event: Callable[[Event], None] | None = None, progress: bool | None = None) -> LeaderboardScore` and the async twin. Returns the new entry.
- Steps inside `_regrade.py`, in order: read the published score (`_published_score`); refuse via `_not_reproducible` (no or partial capture); load the current resource at `published.total_questions`; refuse `already_current` when its revision equals the source's, `not_regradable` when the source's revision is not in `regradable_from`; rebuild `_linked(resource.url4, _candidate_text(build(published.url4)))`; run `evaluate_url4_*` with `replay_frozen_copy=published.pinned_cache`, `answer_seed=published.answer_seed`, `capture=False`, the live-judge header; refuse `regrade_incomplete` if any Case carries `frozen_copy_miss`; post with `_submit_regrade`. Never calls `_reproduction._classify` or records a reproduction.

- [ ] **Step 1: Write the failing tests** (fake transport and board, as `tests/unit/test_replay*.py` do): `test_regrade_rebuilds_only_the_benchmark_part_of_a_fusion_url4`, `test_regrade_replays_with_the_published_seed_and_pinned_cache_and_never_captures`, `test_regrade_refuses_an_entry_already_on_the_current_revision`, `test_regrade_refuses_a_revision_the_benchmark_does_not_list`, `test_regrade_refuses_a_partial_capture_before_any_run`, `test_one_cache_miss_refuses_the_whole_regrade_and_submits_nothing`, `test_regrade_posts_to_the_regrades_route_of_the_source_score`, `test_live_judge_sends_the_header_only_when_asked`, `test_a_private_score_the_caller_cannot_read_is_refused`.
- [ ] **Step 2: Run, expect FAIL** — `cd packages/screamingface && uv run --isolated pytest -q tests/unit/test_regrade.py`.
- [ ] **Step 3: Implement** `_regrade.py` (sync and async share the checks; the two runners differ only in await), the decode of `regradable_from` (absent → `()`, so an older Engine reads as "nothing regradable"), the board calls, the two public methods.
- [ ] **Step 4: Run, expect PASS**, plus `tests/unit/test_replay*.py`, the catalogue-contract tests (`git grep -l _benchmark_entry packages/screamingface/tests`), ruff and pyright on touched files.
- [ ] **Step 5: Commit** `feat(screamingface): re-grade a published score from its pinned cache`.

### Task 5: Bump OME-1907's 47 revisions

**Files:**
- Modify: `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py` (47 `published_revision=` lines, 47 `regradable_from=` declarations), `tests/unit/inspect/test_published_revisions.py` (47 literals, each with a comment naming the old id and "OME-1907 grading change"), `apps/screamingface-engine/CHANGELOG.md` (one line listing the 47 rows, old and new id table pointer, why)
- Create: `.claude/test-change-approvals/OME-1909.json` (covers `test_published_revisions.py` and `test_benchmark_fingerprints.py`, byte-exact against the merge base)
- Keys: the 47 rows whose fingerprint literal #1783 moved (`agieval_aqua_rat` … `wmdp_cyber`, the list in #1783's `test_benchmark_fingerprints.py` diff).

- [ ] **Step 1:** for each key, `just engine benchmark-bump <key>`; new id = the printed fingerprint; `regradable_from=((<old id>, <row's current case digest>),)`.
- [ ] **Step 2:** apply the edits; the `test_published_revisions.py` literals turn the suite red first, then green.
- [ ] **Step 3: Run** `tests/unit/inspect/test_published_revisions.py`, `test_published_revision.py`, `test_benchmark_fingerprints.py`, `test_regradable_from.py`, `test_benchmark_bump.py` with the inspect extra; then `.claude/scripts/approved_test_changes.py` against the merge base.
- [ ] **Step 4:** close the docs in this PR: `docs/tasks/<date>-OME-1909-*.md` mirror (`status: done`), the ledger's Outcome filled, owner-verify note = the post-deploy batch below.
- [ ] **Step 5: Commit** `feat(screamingface-engine): move the 47 revisions OME-1907's grading change touches`.

### After the deploy (owner, not code)

1. Post to the team before merging (rule step 4): the 47 boards move; MMLU-Pro and LAB-Bench users are named in the revision rule's history.
2. Add the operators to `regrade_identities` in the Scoreboard's deployment values (the chart's `config.regradeIdentities`, set per environment in the infra repo).
3. Engine deployed and the Scoreboard seed re-run first; check https://leaderboard.screamingface.ai/v1/leaderboard/inspect-<id> shows the new revision before the batch.
4. Run the batch from a repo checkout, over the cached entries the live board lists at run time (138 entries on 30 boards on 2026-11-17: 130 with a pinned cache, 8 without): for each entry with `pinned_cache` set and the old revision (`https://leaderboard.screamingface.ai/v1/leaderboard/inspect-<id>`), `sf.Client().regrade(score_id)`; log each new id or refusal. About an hour.
5. The entries with no pinned cache (8 on 2026-11-17) need fresh paid runs (owner's call).
