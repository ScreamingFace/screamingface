# url4 hygiene audit, lane H1: measurement (ASSESSMENT ONLY)

Repo state: main @ da88b135a. Package v1.5.1. Raw tool output is in this folder (hot*.json, census.txt, trend.txt, c_*.json, ratchet.json, sizes.txt).

## 0. Reading guide (what the numbers can and cannot say)
- The package is 3 months old. First commit 2026-07-15, 62 commits, median line age 2 months. Any "12 months" window is the whole life.
- Churn is inflated by one event. Commit cba47c0f (2026-09-22, #1015) restructured many files at once. Most "churn 2" files are "created" plus "restructured".
- After the split, the hot files have 0 commits since 2026-09-23. Only two commits touched src (#1085, #1231, both engine refactors). The hotspot list shows the build-up phase, not the current pain.
- `hotspots` "lines" is non-blank code. It is not `wc -l` (render.py is 563 vs 694).

## 1. Census (package scope, `packages/url4`)
| Item | Count | Note |
|---|---|---|
| Source / test lines | 13,026 / 14,130 (66 src files, 1,038 test functions) | |
| TODO / FIXME | 0 | histogram empty |
| Skipped tests (`skip`/`skipif`/`xfail`) | 0 | |
| `pytest.importorskip` | 1 | tests/unit/test_lifecycle_terminal_frame.py:25 (pydantic) |
| Suppression comments, broad census | 55 (src 7, tests 38, scripts 2 self-references, plus 8 `pragma: no cover`) | all younger than 90 days |
| Ratchet-counted suppressions (src only) | 7 (5 `type: ignore`, 2 `noqa`) | matches BASELINE=7, count verified by grep |
| `noqa` for rules NOT selected in ruff config | 17 (6 ARG001, 2 ARG002, 5 ARG005, SLF001, S603, BLE001, FBT001) | inert, see F2 |
| `pragma: no cover` | 8 (cli/_serve 2, cli/app 3, streaming/testing/stream_contract 3) | |
| `assert` as runtime invariant in src (excl. streaming/testing) | 21 | 14 in dag/_lowering.py |
| Cross-package private imports (`from url4.<pkgA>._x` inside pkg B) | 6 src; 9 in engine/apps; 16 private imports in tests | see F3 |
| `asyncio.sleep`/`time.sleep` in tests | 11 | 8 are `sleep(0)` yields or cancel-hang points; 1 real timing wait (test_serve_app.py:111) |
| `# type: ignore` in tests | 23 | |
| Env vars `URL4_*` read in url4 | 8 (HOST, PORT, DEFAULT_ROUTE, EVAL_PATH, CONCURRENCY, MAX_INFLIGHT, TIMEOUT via dynamic `URL4_{NAME}`; CONFIG literal) | `hygiene.py env` sees only CONFIG, see F5 |
| Zero-active-author files | 0 | everything has an author active in the last 18 months |
| CI workflows for url4 | 2 (url4-tests last touched 2026-09-22, release-url4 2026-08-20), neither stale | |
| Module-size entries | 17 capped, 0 over cap, 2 with unused slack to lower | see section 4 |

Authors, last 90 days on the package: about 9 humans plus bots (13 + 9 commits under two Ionesio identities, Kevin M. 8, keelan/Keelan 8, Sergey 4, dependabot 11). Bus factor: `src/url4` 9 authors, `tests/unit` 7. Single-author files are the examples, scripts, the spec tests and the cli config. All are active. No ownership rot.
Counting note: the "fix" subjects are 8 of 62 commits in 90d. `git log --grep` also matches commit bodies, so I used subjects.

## 2. Hotspot quadrants
Tool run: `hotspots packages/url4 --authors --defects`, thresholds p90 churn>=4, p90 complexity>=496 (71 files).

| Quadrant | Files (score, churn, cmplx, density, maxdepth, authors, fixes) |
|---|---|
| REFACTOR (with tests) | `dag/executor.py` (4464, 9, 496, 1.84, d5, 4 authors, 2 fixes). It is the only one. |
| REFACTOR (`--no-tests`, thresholds shift to churn>=8, cmplx>=781) | none |
| ACTIVE (high churn, low complexity) | `observe.py` (3400, 8, 425), `dag/node.py` (1960, 10, 196, maxd 8), `__init__.py` (1644, 12, 137), `tests/unit/test_iteration.py`, `streaming/protocol/signals.py` (1280, 5) |
| DOCUMENT (complex, static) | `core/render.py` (cmplx 1500, density 2.66, maxd 8, churn 2), `peer/client.py` (1160, density 3.05, maxd 8, churn 2), `core/grammar.py` (952), `core/builders.py` (781, density 2.07), `dag/_lowering.py` (777), tests test_dag.py and test_render.py |

Trend (`trend`, renames not followed):
- `dag/executor.py`: complexity 436 -> 677 (07-29) -> 496 (09-22, after the split). Lines 306 -> 270. It is lower than its peak but 14% above its first point. It is the only REFACTOR file, and it was split on 09-22. 0 commits since.
- `dag/node.py`: complexity 1238 -> 196 (-61% on 09-22 when `dag/nodes/` was extracted). This is a verified refactor. Regrowth watch is the `dag/nodes/*` caps.
- `observe.py`: 59 -> 425 (+620% in 7 weeks; 99 -> 393 lines). It is still rising and is the file to watch. It is capped at 483 lines, and it is at baseline (0 slack used). Complexity is 3.4k-score "ACTIVE" because density is low (1.08).
- `core/render.py`: 1488 -> 1500 (+1%), flat. `core/parser.py`: 415 -> 437 (+5%). `peer/client.py`: 1066 -> 1160 (+9%, one data point before the split).
- Single-author concentration in the DOCUMENT quadrant: render.py, peer/client.py, grammar.py and builders.py each have 1 author. They are stable, so this is low risk now. It becomes a risk if any enters the REFACTOR set.

Not worth touching (DOCUMENT and leave): `core/render.py`, `peer/client.py`, `core/grammar.py`, `core/builders.py`, `dag/_lowering.py` (+ test_dag/test_render). They are complex and have had 0 changes since 09-23. Payback test: I is about 0 hours per month, so C/I is unbounded. Write a one-paragraph "why this is dense" header comment at most. Exception: `peer/client.py`, see F4.

Interest on the candidate (executor.py): 9 commits, 7 touching "fix" subjects including bodies, 2 by subject; 4 distinct authors in 90 days. I cannot compute lead time per module from git alone (see blind spots).

## 3. Findings

F1. [static] Module-size baselines are stale and drifting, in both directions. Evidence: `scripts/check_module_size.py` BASELINE vs `wc -l`:
- Should be lowered: `io/layer.py` 197 -> 194 (13 slack), `cli/_serve.py` 340 -> 339 (11 slack).
- Grew inside the headroom (the cap is soft by 10): `core/render.py` +7 (694/697, 3 left), `dag/nodes/iteration.py` +6 (4 left), `peer/_dispatch.py` +6 (4 left), `dag/nodes/_shared.py` +3, `peer/server.py` +2, `dag/_lowering.py` +1 (738/747).
- Intent says "never raise a cap". The effective cap is baseline+10 and the baselines were not tracked: the real drift is +25 lines across six files, silently. Effective ratchet slack at the time of the split was 17 x 10 = 170 lines of free regrowth.
- Cannot rule out: the +7/+6 growth is intentional review-approved edits; the script has no way to say so.
Interest: the next edit of render.py (3 lines left) or iteration.py/_dispatch.py (4 left) will fail CI with no refactor reason, and the temptation is to bump the baseline, which the policy forbids. That is the failure mode the docstring describes.
Action: lower `io/layer.py` to 194 and `cli/_serve.py` to 339; for the six grown files, re-baseline to the current size at the next review, deliberately, with the commit message saying why (documented exception to "never raise"). Better: make the gate print "slack used" and fail on baseline > current+HEADROOM (stale-high detection). Reversibility tier: 1 (script constants, revert in one commit).

F2. [static] 17 `# noqa: ARG*/SLF001/S603/BLE001/FBT001` comments suppress rules that ruff does not run, so they are dead. Evidence: pyproject `[tool.ruff.lint] select = ["E","F","I","UP","C901","PLR0911","PLR0912","PLR0915","PLR1702"]` (no ARG, SLF, S, BLE, FBT, no RUF100). The comments were probably copied from the engine, where those families may be on. I could not run ruff here (not installed, `uv` would install into the repo; I did not run it). Cannot rule out: they are intended as forward-compat for rule families the team plans to enable. Not counted by the suppression ratchet (it counts src only: 2 of the 17 are in src, 15 are in tests).
Interest: every one is a false claim ("this is reviewed") plus noise in the census (55 vs 7). Action: enable `RUF100` (it reports them, and any future dead ones) and delete the 17; or enable those rule families with the existing comments as the baseline. Tier 1.

F3. [static] Private modules are the de facto shared API across subpackages. Evidence (6 src imports): `wire/subrequest.py` imports `core._annotations` (EXPRESSION_BEARING_KEYS, validate_param) and `core._scan`; `dag/nodes/fetch.py` and `dag/semantics/ensemble.py` import `core._scan`; `cli/_serve.py` imports `peer._asgi` (lifespan, send_error). Plus 9 private imports from engine/apps and 16 in tests. `tests/unit/test_layering.py` and `test_import_isolation.py` exist, so layering is gated but the underscore rule is not. Cannot rule out: the underscore convention here only means "not exported from the top-level package" and `_scan` is intended as an internal shared kernel.
Interest: moving or renaming `core/_scan.py` (264 lines, 5 consumers) breaks three subpackages at once. Action: either promote `_scan`/`_annotations` to public-in-package names (`core/scan.py`) or add the ratchet in section 5. Tier 1-2.

F4. [static] The module-size ratchet misses the second most complex file. Evidence: `peer/client.py` is 444 lines (the 7th largest in src; `wc -l`), complexity 1160, density 3.05, maxdepth 8, and it is uncapped. Also uncapped and above 300 lines: `dag/_context.py` (383), `core/nodes.py` (336), `dag/semantics/ensemble.py` (315). Cannot rule out: it is stable (churn 2) and deliberately left uncapped. Cap list covers the reviewed split targets only.
Interest: low today (stable). It becomes the next place a "one more import" regrowth lands. Action: add entries for the four files at current size (+10) when the gate is next touched. Tier 1.

F5. [static] Documentation of `URL4_*` env vars is partial, and the tool cannot verify it. Evidence: `hygiene.py env` reports only `URL4_CONFIG` (read, "undeclared") and `N` (README.md:8, a false positive). The real names are built dynamically (`_config.py:226` `env.get(f"URL4_{name.upper()}")`) for 7 fields: HOST, PORT, DEFAULT_ROUTE, EVAL_PATH, CONCURRENCY, MAX_INFLIGHT, TIMEOUT. README.md:184-185 names HOST, PORT, DEFAULT_ROUTE, EVAL_PATH, CONFIG and then "..." (CONCURRENCY, MAX_INFLIGHT, TIMEOUT are undocumented). No README table. ARCHITECTURE.md has no env mention. The `URL4_CLOUD_*` names in docs/ belong to the engine, not this package (distinct prefix, rename plan docs/plan/2026-08-18). Cannot rule out: `url4 serve --help` lists them (not checked).
Interest: small. An operator must read `_config.py` to find three knobs. Action: add an env table to README (one row per ServeConfig field); the existing config tests could assert docs and code agree. Tier 1.

F6. [static] CI: release is not gated on tests, and the third-party actions are tag-pinned. Evidence from the two workflows:
- `release-url4.yml` has no `needs:` on url4-tests. A `url4-v*` tag (release-please) builds and publishes whatever commit is tagged, and `workflow_dispatch` takes any tag string. `verify` checks only that the tag version matches pyproject. Cannot rule out: release-please only tags a commit that already went through the PR CI on main (likely), and the `pypi` environment may have required reviewers (unknown, see header comment).
- Actions use mutable tags: `checkout@v7`, `setup-uv@v7`, `setup-python@v7`, `upload/download-artifact@v7/@v8`, `dorny/test-reporter@v3`, `orgoro/coverage@v3.3`, `pypa/gh-action-pypi-publish@release/v1` (branch, upstream-recommended), and `HupBaHa/cost-diff@v0.1.2` (a personal-account action with `issues: write`). No SHA pins. Dependabot has a `github-actions` ecosystem (dependabot.yml:324), which mitigates drift but not tag-moving. The PyPI publish job holds `id-token: write`; that is the highest-value pin target.
- No `concurrency:` group in url4-tests (the engine workflow has one with cancel-in-progress). Duplicate matrix runs on rapid pushes.
- The `serve` job reruns the whole unit suite (`pytest -q --no-cov`) a second time with uvicorn installed, py3.12 only. That is intentional (hang regression), about 1000 tests duplicated.
- Python matrix 3.12/3.13 equals the pyproject classifiers (3.12, 3.13) and `requires-python >=3.12`; pyright `pythonVersion` 3.12. Consistent. No 3.14 (dependabot.yml:233 says deliberately excluded).
- Path filters: url4-tests triggers on `packages/url4/**` and itself. Docs/spec changes do not trigger it, and should not: `tests/spec/*.py` do not read `docs/` (grep found no path reference). Consumers: engine (`screamingface-engine-tests.yml`), `screamingface-tests.yml` and `screamingface-e2e-replay.yml` all trigger on `packages/url4/**`, so a url4 change runs the consumers. Reverse (a consumer change triggering url4 tests) is not needed. The root-level lock, `release-please-config.json` and `.release-please-manifest.json` also do not trigger url4-tests; acceptable.
- Never-run or stale: none found. Both url4 workflows were touched in the last 2 months. I could not run `gh run list` (not attempted for last-run dates; see blind spots).
Action: add `needs`/a green-commit check to publish (or a job that asserts the tagged SHA has a passing url4-tests run); SHA-pin the publish-path actions; add `concurrency`. Tier 1 for workflow edits, but a failed release gate is externally observable, so test it via `workflow_dispatch` on a dry tag first (tier 2).

F7. [static] The streaming coverage omit is real, but the replacement gate is weaker than the comment says. Evidence: `pyproject.toml:82-87` omits `src/url4/streaming/*` from the 95% gate and says the engine suite "gates it via `--cov=url4.streaming`". The engine workflow (`screamingface-engine-tests.yml:68-75`) does run `--cov=screamingface_engine --cov=url4.streaming --cov-fail-under=80`. That is one aggregate 80% across engine + streaming, not a per-package gate. Streaming is 4+ files (signals 273, lifecycle 240, interfaces, testing/stream_contract with 3 `pragma: no cover`) and the engine has thousands of lines, so streaming can fall to near 0 without tripping 80%. 100 engine test files import `url4.streaming` (grep), so it is exercised, but not gated by itself. Cannot rule out: the aggregate currently sits well above 80 and streaming is fully covered; I did not run coverage.
Interest: an unguarded contract that ships to PyPI (the wire contract). Action: add a per-package floor in the engine (a second `coverage report --include='*/url4/streaming/*' --fail-under=95`). Tier 1.

F8. [static] The suppression ratchet's 7 is correct but its scope is narrow. Evidence: `scripts/check_suppressions.py` scans `src/url4` only and counts `type: ignore` + `noqa` (5 + 2 = 7; grep gives the same 7 lines). It ignores `pragma: no cover` (8 in src), tests (38 suppressions), and counts the pattern anywhere, including inside strings or docstrings (the script's own file is outside the scan root, so it does not count itself). It also cannot see inert noqa (F2). Cannot rule out: tests are intentionally out of scope.
Action: keep BASELINE=7, add the hygiene ratchet entries below rather than rewriting the script. Tier 1.

## 4. Module-size table (current vs baseline, cap = baseline + 10)
| Module | baseline | now | delta | slack left |
|---|---|---|---|---|
| core/grammar.py | 944 | 944 | 0 | 10 |
| dag/_lowering.py | 737 | 738 | +1 | 9 |
| core/render.py | 687 | 694 | +7 | 3 |
| peer/server.py | 312 | 314 | +2 | 8 |
| dag/nodes/_shared.py | 257 | 260 | +3 | 7 |
| dag/nodes/iteration.py | 218 | 224 | +6 | 4 |
| peer/_dispatch.py | 204 | 210 | +6 | 4 |
| io/layer.py | 197 | 194 | -3 | 13 (lower) |
| cli/_serve.py | 340 | 339 | -1 | 11 (lower) |
| other 8 entries | at baseline | | 0 | 10 |
Note: the scout's quoted baselines (render 697 cap, _lowering 747 cap) match baseline+10. The list in the brief ("render.py 694 vs cap 697") is the same data.

## 5. Ratchet proposals (hygiene.py ratchet, config at ratchet.json in this folder; baselines are today's numbers, never zero)
| Name | Regex scope | Baseline | Why |
|---|---|---|---|
| url4-inert-noqa | `# noqa: (ARG\|SLF\|S\d\|BLE\|FBT)` in package | 17 -> go to 0 after F2 | dead suppressions; or switch on RUF100 instead (better, self-cleaning) |
| url4-pragma-no-cover | `pragma: no cover` in src | 8 | coverage escape hatch the current ratchet misses |
| url4-assert-src | `^\s*assert\s` in src, excluding streaming/testing | 21 | assert is stripped under `python -O`; 14 are narrowing asserts in `_lowering.py`. Check intent before ratcheting to a lower number. |
| url4-sleep-tests | `asyncio.sleep\|time.sleep` in tests | 11 | low value: 8 are yields or intentional hangs; keep only if flakiness appears |
| url4-tyignore-tests | `type: ignore` in tests | 23 | outside the existing gate |
| url4-importorskip | `importorskip` in package | 1 | silent skip; the engine repo already hit this (its workflow comment, PR 1009) |
| Cross-package private import | Not expressible as a plain regex, since "private" depends on which package imports. Use the AST check `tests/unit/test_layering.py` pattern: fail on `from url4.A._x` inside subpackage B != A. | 6 in src | F3 |
Dry run: `hygiene.py ratchet --config ratchet.json --update` produced the counts above (17, 8, 21, 11, 23, 1). Not wired into CI (read-only audit).
Also recommended: enable ruff `RUF100`, and add `# TODO(owner, date)` format only if TODOs appear (there are none today).

## 6. Recommended sequence (3 items)
1. Ratchet hygiene first (30 min). Lower io/layer.py (194) and cli/_serve.py (339); enable `RUF100` and delete the 17 inert noqa; add `peer/client.py`, `dag/_context.py`, `core/nodes.py` and `dag/semantics/ensemble.py` to the size gate; add `url4-pragma-no-cover` and `url4-tyignore-tests` ratchets.
2. Close the CI gaps. A tag-gated release (publish needs a green url4-tests on the tagged SHA), SHA-pin the three publish-path actions, add `concurrency`, and add a per-package coverage floor for `url4.streaming` in the engine job.
3. Watch `observe.py` (+620% complexity in 7 weeks, at its cap exactly) and decide whether it gets the next split. Do nothing to render/client/grammar/builders/_lowering. Re-run `hotspots --since "30 days"` in a month, when there is post-split history.

## 7. Blind spots
- No ruff/pyright/pytest run (nothing installed, and I did not install into the repo). F2 is derived from the config, not from a RUF100 run.
- No `gh run list` or workflow run history: last-run dates, flake rate, CI wall time and cost per job are unknown. A never-run job cannot be ruled out.
- Coverage numbers: I did not run the engine job, so the F7 headroom is unknown.
- Lead time, review latency and incident attribution cannot come from this repo. The 3-month history gives no baseline to trend, and "interest" above is commit counts only.
- Whether the PyPI Trusted Publisher and the `pypi` environment reviewers are configured is not visible from the repo (the workflow header comment says it must be verified by an owner).
- `hygiene.py env` cannot see dynamically built names. `--help` output for `url4 serve` was not compared to the README.
- `hygiene.py trend` does not follow renames: pre-split file histories (e.g. `dag/node.py` before `dag/nodes/`) are truncated, and complexity moved into new files looks like growth there.
- Engine/consumer private-import counts (9) were gathered with a regex over `apps` and `packages/screamingface`; not individually verified.
