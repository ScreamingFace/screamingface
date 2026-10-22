---
ticket: OME-1716
stack: scoreboard
status: in_progress
started: 2026-10-22
finished:
---

# Recognize verified GLM-5.3 weights

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

## Outcome
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
