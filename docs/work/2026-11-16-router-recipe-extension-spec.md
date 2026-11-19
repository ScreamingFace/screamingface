---
ticket: OME-1976
stack: repo
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-16
finished:
---

# router-recipe-extension-spec — implementation spec and plan for the Router Recipe extension

## Intent

Write the extension-level implementation spec, then its plan, for the Router Recipe / Fusion / BERT
extension (epic OME-1306) designed in screamingface-design PR #35. The spec pins the cross-Unit
contracts that later Units 5-9 implement: how the preserved named-profile routing pilot
(OME-1822/1823) reconciles with current main, the public `sf.Router` value and its versioned IR,
the structured-choice classifier input, capability and pre-spend refusal, answer and report
evolution, classify capture/replay, prepared inputs, and the exact test and public-surface
transitions each Unit needs. The spec and plan stay normative for every Unit; each Unit later gets
its own ledger and pins its open items by amending the spec. Documentation only: no source, test,
approval-manifest or dependency change in this unit.

## Planned changes

- `docs/spec/2026-11-16-router-recipe-extension/` (new): extension-level implementation spec in
  six files, subordinate to the PR #35 design (it translates the design into exact contracts and
  re-decides nothing): `00-overview.md` (base, scope, Units, pilot reconciliation, contract index,
  relation to the governing design, issue coverage), `contracts.md` (C1-C6, C10-C12, C14-C16),
  `contracts-replay.md` (C7-C9: classification input, physical attempts, replay),
  `contracts-entry.md` (C13 inline entry and result, C17 Engine classifier catalog),
  `contracts-placement.md` (C18 Router outcome inside compositions, C19 url4 at-most-one source)
  and `test-plan.md` (first failing tests, Unit 5.1 fake-HTTP acceptance, contract tests, expected
  prior-test transitions).
- `docs/plan/2026-11-16-router-recipe-extension.md` (new, after the spec is approved): Unit order,
  PR slicing, dependencies and per-Unit acceptance.
- This ledger.

## Test plan

- Documentation only; no executable tests. Every code fact the spec states is checked against the
  recorded base SHA (file:line), and the pilot facts against the preserved pilot worktree.
- `git diff --check` on the new files.

## Acceptance

- The spec records the exact base SHA and the actual pilot/main overlap.
- Every contract the design leaves to the implementation spec is pinned or explicitly marked as a
  per-Unit decision with its owner.
- No statement contradicts the PR #35 design at its current head; any contradiction is listed with a
  minimal resolution.
- The owner approves the spec before the plan is written, and approves the plan before any code.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** six files under `docs/spec/2026-11-16-router-recipe-extension/`,
  `docs/plan/2026-11-16-router-recipe-extension.md`, this ledger and the
  `docs/tasks/2026-11-19-OME-1976-router-recipe-extension-spec.md` mirror.
- **Commits:** one documentation commit on `OME-1976-router-recipe-extension-spec`, on top of
  `e5bb820b2`. Code references stay checked at `31c1158e8`: the two later main commits are
  docs-only and change no cited file.
- **Gates:** fresh-base fast-forward through `9dc57358e` to `31c1158e8`; 149 code-reference
  occurrences checked (134 uniquely resolved plus 15 path-convention/pilot references); pilot/main
  overlap and three-way merge simulation; V1-V5 recomputation with real `resolved_params`; Markdown
  tables/relative links/whitespace/conflict-marker checks; `git diff --check`; independent spec rounds
  and independent plan review. A later focused review found the OME-1809 scoring-order gap,
  capability fallback/rollout-order corrections and approval-provenance wording. The architecture
  alignment pass then pinned C19 to the existing extensible url4 key grammar, restored one shared
  Engine application boundary, routed prepared-question failures through JOIN and reused existing
  replay cost/ambiguity mechanisms. A dependency audit checked all four lockfiles, installed/locked
  Pydantic, Tortoise ORM and HTTPX behavior, and versioned official documentation; it moved attempt
  counting below hidden transport retries and added clean-artifact/dependency-isolation gates. A
  follow-up probe added mounted-root path handling, cross-task mutable counting, exact lock export,
  post-parse finite-number vectors and qualified outer request-parser ceilings. Those corrections are
  reflected in the current documents.
- **2026-11-19 follow-up:** pinned `--python <v>` for every workflow-matrix sync and version receipt,
  added the Python 3.13 runtime compatibility lane, qualified h11 against the full request head and
  real headers, confirmed the HuggingFace/Ollama client seam in both LiteLLM locks, and restored the
  unrelated-key and Unit 3 capability-floor rollback invariants.
- **Deviations:** source base moved from `455166b0d` through `9dc57358e` to `31c1158e8`; the former remains only the
  intentional C19 old-reader fixture. Fresh main adds OME-1809 run-file admission, now assigned across
  Units 5.2/6. Pilot integration predicts five conflicts rather than four because `error_text.py` now
  conflicts. The plan draft was written before explicit approval of the reconciled spec; the owner
  approved both on 2026-11-19 after a final check against the design, then dropped per-Unit specs
  and plans: each Unit gets a ledger, worktree, RED-first tests and gates; open items are pinned by
  amending the spec, with re-approval of the changed fragment only; a separate addendum is written
  only for a new implementation-changing decision. The current Engine and SDK local venvs are not
  lock-synchronized and are not accepted as implementation evidence; every Unit must sync its fresh
  worktree first. No executable
  test, approval manifest, dependency, source code, GitHub or Linear state changed in this documentation unit.
