---
ticket: OME-1223
stack: repo
status: done
started: 2026-09-17
finished: 2026-09-17
---

# OME-1223 — Improve the code-review agent's design assessment and review presentation

## Intent

OME-1216 moved the code-review agent guide into `.claude/agents/sf-code-review.md`
unchanged, so whatever was wrong in the personal copy became the shared copy. Two
classes of problem were left: the guide had no instruction to judge whether a change
solves the right problem (it went straight from context-gathering to defect lanes),
and four of its technical claims were wrong in ways that would produce false findings.
A third, softer problem: reviews written to the four-beat format read as dense
lane-labelled lists, which buries the merge decision the author actually needs.

This unit fixes all three on the OME-1216 branch, because the guide had not merged yet
and a second PR against an unmerged file would have stacked two reviews of the same
text.

## Planned changes

- `.claude/agents/sf-code-review.md` — the only file. Five groups of edit:
  - **Approach assessment** (new section before the lanes): is this a sound way to
    solve the problem, judged separately from spec compliance and from repo standards;
    plus when to ask for a recorded design decision.
  - **Evidence discipline** (new subsection): pin the reviewed head/base revision;
    separate checks you ran from conclusions you read from results the author reported;
    match evidence to the exact claim — a mutation that fails the *new* test does not
    show existing CI would have missed it.
  - **Output format**: replace the four-beat block with plain-language rules and a
    Verdict / Findings / Approach / Minor / Checks-and-limits structure, with evidence
    summarised inline and full reproduction detail in expandable sections.
  - **Technical corrections** (four):
    1. `asyncio.CancelledError` inherits `BaseException`, so `except Exception` does
       not catch it — the old bullet told reviewers to flag the opposite. Every
       `pyproject.toml` here pins `requires-python = ">=3.12"`, so the modern
       behaviour is the only behaviour in this repo.
    2. `ast.parse` is a syntax check, not a safety control — it accepts syntactically
       valid malicious statements. The old bullet offered it as an *alternative* to
       safe encoding on a code-injection sink.
    3. Restored the missing `## Lane 5 · Money & resources` heading; the money prose
       had been hanging off Lane 4's last bullet since the guide was first written.
    4. Two identical seeded responses do not prove a provider honoured the seed —
       the response cache or ordinary repeatability explains them equally well.
  - **Evaluation protocol** replaces the eval stub: held-out PRs, pinned guide and
    model settings, fresh context per trial, precision/recall/calibration recorded per
    revision. States that the historical examples taught in the guide are development
    cases, not evidence of generalisation.
- This ledger + mirror `docs/tasks/2026-09-17-improve-review-agent-assessment.md`.

## Test plan

Docs-only; no code paths, no runtime behaviour. Verification was:

- `git diff --check` and the repository's applicable pre-commit checks.
- Markdown/section checks and full-content preservation between revisions (no lane
  body lost while rewording the surrounding scaffolding).
- Three fresh-context smoke trials on real PRs: #969 (no actionable findings), #971
  (found a broken onboarding command and an overstated write guarantee), #972 (kept
  the CI execution gap and limited its mutation claims to checks actually run). The
  #971 probes were rerun independently.
- Light/dark browser QA on the local side-by-side comparison of old vs new review
  output.

## Acceptance

- All seven lane bodies survive the rewrite.
- The four technical corrections are present and each is checkable against the
  language/tooling version this repo actually pins.
- No personal names or personal directory paths in the shared doc.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `.claude/agents/sf-code-review.md` as planned, plus this ledger and
  its mirror (added after the fact — see Deviations).
- **Commits:** `d20b8a97` docs(repo): improve review agent clarity and evidence
  standards · `ab255233` docs(repo): reconcile review severity and evidence guidance.
  Both reached PR #979 through PR #982, which merged into the OME-1216 branch.
- **Gates:** docs-only. `git diff --check` and pre-commit passed; CI on #979 shows
  CodeQL green with the code lanes skipped (no code paths touched).
- **Deviations:** three, all worth knowing about later:
  1. **The PR grew.** This work opened as PR #982 against the OME-1216 branch, then
     merged into it, so PR #979 now carries two tickets. OME-1216's own ledger was
     already closed at that point and says "deviations: none"; a pointer to this file
     has been added there.
  2. **OME-1216 declared the four-beat format a deliverable; this unit deleted it.**
     The reason is that the format optimised for comparability between reviewers at
     the cost of the reader finding the merge decision. That trade was made
     deliberately, but it does mean the PR removes a criterion it also added.
  3. **The severity tiers were recalibrated, not just reworded.** Tier names changed
     (`Review recommended` → `Nonblocking`, `Auto-fixable` → `Minor`) and the
     calibration note changed from "blocks by lane membership" to "blocks by
     consequence, reachability and the applicable requirement".

## Open questions raised in review (not blocking the merge)

Two of the recalibrations invert a burden of proof, and the lanes they touch are the
two whose defects are defined by the absence of a signal. Recorded here so a future
reader can see the trade was noticed rather than slipped through:

- **Lane 2 (grading integrity)** went from "findings default to blocking" to "block
  when they *demonstrate* a grading-integrity violation", and the calibration note
  "Lane 2 findings default to Action required unless proven benign" was deleted.
- **Lane 7 (test honesty)** went from "vacuous-green findings are blocking — they forge
  the evidence everything else relies on" to blocking only when a gap "leaves a
  material defect unprotected"; "any load-bearing claim without a test pinning it is a
  finding" became "lack of a new test alone is not a finding".

The concern: the guide's own thesis is that absence of observation is not proof of
absence. The two worked examples it still teaches — a glob matching no files and
reporting `pass 0, fail 0` (OME-798), and a lane skipped forever on runners missing a
tool (OME-1189) — are cases where no reviewer can name the material defect, because
not knowing what is unprotected *is* the defect. Under the new wording both downgrade
to Nonblocking.

A possible resolution, if these misfire in practice: keep a fail-closed carve-out for
these two lanes only (an unresolved candidate/judge boundary question, or a test that
cannot fail, blocks until resolved) and let consequence-based calibration govern the
other five. The evaluation protocol added by this unit is the right place to settle
it — both cases belong in the held-out set as labelled recall checks.

## Follow-up outside this PR

The review hook that actually loads this guide still points at the untracked personal
copy, so the shared file is inert until it is repointed at
`.claude/agents/sf-code-review.md` and the personal copy is deleted. That hook lives in
a git-ignored local settings file and cannot be changed from inside this repo.
