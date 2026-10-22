---
ticket: OME-1716
stack: scoreboard
status: in_progress
started: 2026-10-22
finished:
---

# Recognize verified open-weight releases

## Intent
Correct GLM-5.3 and all-open ensemble labels. The user authorized implementation
after the registry audit and versioning explanation.

## Planned changes
Exact owner/model registry entry, new classification and frontier/trend tests,
spec, plan, and existing issue mirror.

## Test plan
Reproduce solo/ensemble and frontier failures first. Test routing normalization,
owner boundaries, unverified suffixes, mixed ensembles, and overrides.
Run scoreboard quality gates including Python coverage and Node portal tests.

## Acceptance
Verified GLM-5.3 routes classify open without broadening the vendor or family.
Closed/unknown members and operator overrides retain precedence. Frontier and
history use the corrected registry without benchmark or score changes.

## Initial single-model pass
- **Actual files:** registry, new `test_glm_openness.py`, spec, plan, issue mirror, ledger.
- **Commits:** planned `fix(scoreboard): recognize verified GLM-5.3 open weights`.
- **RED:** 15 failures and 2 passes before the registry change; failures reproduced unknown
  GLM diagnostics, closed ensemble, and a 40% rather than 60% frontier share.
- **Gates:** `uv run .claude/scripts/run_gates.py scoreboard --base origin/main`:
  ALL GATES GREEN (append-only tests, lint, format, pyright, full Python suite with
  80% coverage floor, all configured Node portal tests). Focused suite: 98 passed.
- **Audit replay:** applying the new classifier to all 63 public ranked rows from the
  2026-10-22 snapshot changed exactly six: solo GLM and `sota_open_only` on ContractEval,
  GDPval, and FrontierScience. Other entries retained their verdicts.
- **Review:** exact normalized owner/model membership avoids unverified suffixes and owners;
  shares and history already use this classifier. No schema, API, dependency, evaluation,
  or benchmark revision changes. Existing tests remain unmodified.
- **Deviations:** existing bug was filed before implementation; reused it. Worktree is in
  `/private/tmp` to keep the shared checkout untouched. Full gates ran with local socket
  access. Prime and Qwen findings remain outside the confirmed bug's scope.
- **Delivery:** implementation validated; PR review and deployment pending.

## Expanded audit (owner requested 2026-10-22)

The user requested verification and fixes for as many models as possible, explicitly
expanding the single-model scope. Audit the full current OpenRouter catalog and official
weight repositories; investigate accelerated GLM aliases and questionable live routes.
Add exact verified release entries and evidence, retaining unknowns when no weight release
is established. Update the original Prime/Flash test expectations if primary evidence
establishes those releases, as part of this owner-requested expansion. Re-run full gates,
replay live leaderboard labels, and update the existing PR and issue with final scope.

## Expanded implementation outcome

- Audited 468 catalog routes; accepted 99 exact routes across 32 owners with weight
  repository evidence. Recorded pinned revisions, license metadata, file counts, and
  primary route links in the evidence CSV. Accelerated aliases are explicitly documented.
- Replaced the original one-entry set with a static release registry. Two observed
  hosted Qwen routes now return unknown before the owner heuristic. No vendor-wide
  additions; all existing overrides and mixed-model rules remain intact.
- Expanded RED: 102 failures / 112 passes before production changes. GREEN focused:
  289 passed. The original PR's Prime/Flash negative cases now use future versions,
  with current releases covered in the expanded audit tests (user-authorized scope).
- Snapshot replay: 63 rows, nine label changes (seven closed to open, two open to closed).
  ContractEval frontier 2/5 → 3/5; Draco 4/11 → 3/11; other frontier shares unchanged.
- Final gates: ALL GATES GREEN via `uv run .claude/scripts/run_gates.py scoreboard
  --base origin/main`: append-only check, Ruff lint/format, Pyright, full pytest with
  the 80% coverage floor, and all configured portal Node tests. Fixed two overlong
  registry lines before the successful run; no gate configuration changed.
- Self-review: audited evidence has 99 unique routes / 85 weight repositories, all with
  observed revisions and weight files. Exact lookup preserves route boundaries; hosted
  Qwen exclusions preserve unknown diagnostics. No runtime network dependency added.
- Delivery: expanded draft PR #1534; Siddhant (`siddhant230`) remains requested reviewer.
  Linear stays In Progress pending review; deployment has not occurred.
