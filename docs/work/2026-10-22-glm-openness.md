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

## Source-by-source recheck

Owner requested a second source review. Re-fetched pinned metadata for all 85 primary
weight repositories (all resolve, all list nonempty weight blobs), all 99 cited route
pages (all HTTP 200), and the current catalog (all 99 routes still present). Checked
model cards/configurations and route mappings, including modality alignment, redirected
publisher namespaces, and three accelerated aliases. Inspected public cards for five
gated repositories whose raw README endpoints require acceptance. Verified the additional
MiniMax Text-01 release and Qwen's official release catalog.

No label changes needed under the existing definition. Corrected evidence weaknesses:
full Aion commit hash instead of abbreviation; explicit missing license metadata; access
gates, manifest byte counts, inference sources and mapping basis; first-party Z.ai
FlashX documentation; both MiniMax-01 component releases. Documented alias and license
qualifications rather than implying independently attested API weights or unrestricted
licensing. No weights downloaded, no gate acceptance, and no inference runs performed.

Validation after evidence changes: 289 focused tests passed; `git diff --check` passed.
Classifier code and audited route membership are unchanged.

## Review round — Dmitry, 2026-10-27 (CHANGES_REQUESTED at 01a36f888)

Status: DONE (2026-10-28).

Intent: address three verified findings.

1. URL4 selector spelling. Submitted routes use the Engine's `~` escape for a gateway `:`
   (`world/models/registry.py` `encode_route_id`); the submission schema accepts `~` and
   rejects `:`. The registry stores gateway ids, so all 16 `:free`/`:batch` entries were
   unreachable from a real submission.
2. Hosted-Qwen deny bypass. `openrouter/qwen/qwen3.6-plus~free` (and `~batch`, and
   `qwen3.8-max-prime~free`) missed the exact-tuple deny and fell through to the `qwen`
   owner rule, classifying open.
3. Evidence CSV weight totals omitted `.pt` artifacts (e.g. `moondream3-preview`
   `model_fp8.pt`, 10,505,451,019 bytes).

Planned changes:
- `classification/openness.py`: decode `~` to `:` when splitting a route (mirrors the
  Engine's `decode_route_id`; `~` is reserved for that escape), and check the hosted-edition
  deny list against the model base before any `:` selector, ahead of the owner rule.
- Tests (new only): URL4-spelled routes for all 16 selector registry keys resolve open via
  `classify_model` and `classify_entry`; hosted-Qwen `~free`/`~batch` variants return
  unknown and close the entry with the route reported.
- Evidence CSV: recompute `weight_file_count`/`weight_bytes` from the pinned Hugging Face
  manifests with `.pt`/`.pth` included; state the counted suffix set in the spec.

Acceptance: reviewer's two route probes pass; scoreboard gates green; CSV totals
reproducible from the stated suffix set.

Outcome:
- Verified all three findings against the code before changing anything: the schema
  accepts `~` and rejects `:`; the Engine encodes `:` as `~`; `_split_route` did not decode;
  the hosted deny compared the whole model segment; the CSV totals matched exactly
  safetensors+bin+GGUF for all 99 rows.
- `classification/openness.py`: `_split_route` decodes `~` to `:`; new
  `_is_unverified_hosted` compares the model before its selector, ahead of the owner rule.
  Registry lookup stays exact.
- New test file `tests/unit/classification/test_route_selectors.py` (no prior test changed).
  RED: 26 failed (16 selector releases + 10 hosted-Qwen variants). GREEN: 45 passed.
- Evidence CSV recomputed from pinned manifests with `pt`/`pth` added: 5 rows changed
  (Ling-3.0-flash-VL, moondream3-preview, MiMo-V2.6 Flash/Pro/Pro-UltraSpeed; four distinct
  `.pt` files). Spec states the counted suffix set.
- Gates: ALL GATES GREEN via `run_gates.py scoreboard --base ae12925` (the PR merge base).
  Against current `origin/main` the append-only check flags two tests the branch never
  touched (main moved ahead); not a change of this PR.
- Deviation: ruff PLR0911 required splitting the hosted check into a helper.
