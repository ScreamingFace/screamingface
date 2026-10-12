# url4 hygiene audit, lane H4: dependencies, packaging, consumers, tests, examples

Mode: assessment only. Repo untouched. Scratch copy of the package used for the 3.14 and lowest-bound runs ($SP/copy).

## 1. Census

| Item | Value |
|---|---|
| url4 runtime deps | 1 (httpx>=0.27; locked 0.28.1, latest 0.28.1) |
| Extras | server (uvicorn>=0.30), streaming (pydantic>=2.13.4) |
| Dev group | pyright, pytest, pytest-asyncio<2, pytest-cov, ruff, url4[streaming]; `notebook` group: graphviz |
| Majors behind in uv.lock | 0 (minors: pydantic 2.13.5 vs 2.14.0, ruff 0.16.9 vs 0.17.0, anyio 4.14.2 vs 4.15.1, coverage 7.15.0 vs 7.16.2) |
| pip-audit on locked set | 0 known vulnerabilities (25 pinned pkgs, no-deps mode) |
| deptry (self-import noise removed) | 5 hits: 1 false positive (uvicorn DEP002: lazy importlib), 4 real but all in examples/ (IPython undeclared, graphviz dev-only, `utils` local module x2) |
| Lowest-bound run (httpx 0.27.0, pydantic 2.13.4, uvicorn 0.30.0, py3.12) | 1360 pass |
| Python 3.14 run (locked versions) | 1360 pass; 3.14 is in neither CI matrix nor classifiers |
| Python | requires-python >=3.12 (no upper bound); classifiers 3.12, 3.13; CI matrix 3.12, 3.13; local .venv is 3.13.15; pyright pythonVersion 3.12 |
| In-repo consumers | 4 (engine 269 files import url4: 83 src + 186 tests; screamingface 20: 8 src + 12 tests; studio/runtime 0 direct; playground 1) |
| Consumer imports of private url4 modules | engine src 3 sites (world/config.py:65,68 `url4.cli._config` + 3 private fns; world/factory.py:48 `url4.cli._serve`); engine tests 6 sites in 5 files (`url4.dag.nodes._shared._error_payload` x3, `url4.streaming.lifecycle._error_info` x1, `url4.peer._owned` x1, `url4.cli._config.ProviderSpec` x2 in test_world_read_side.py) = 9 total |
| Consumer imports of names outside `url4.__all__` (top-level) | 0 (`__all__` has 54 names; consumers use 21+19 deep submodules, e.g. url4.streaming.protocol 113 imports, url4.peer.server 91) |
| Skipped/xfail tests | 0 skips, 0 xfail; 1 `importorskip("pydantic")` (test_lifecycle_terminal_frame.py:25) |
| Sleeps in tests | 11 lines with "sleep" (not 23; orchestrator figure not reproduced): 4 `sleep(0)` yields, 3 long cancel-bound (30, 10, 5 s), 2 injected-delay fixtures, 1 real 0.1 s wait, 1 subprocess `time.sleep(5)` killed at 0.1 s timeout |
| Suppressions (census) | noqa/type-ignore present, ratcheted by scripts/check_suppressions.py in CI; TODO count 0 |
| Test run | 1360 passed, 0 failed, 3.25 s (pytest-reported), 98% line coverage (streaming omitted) |
| Slowest test | 0.24 s (test_generated_parity_corpus_text_path_matches_ast_path); next 0.15 s |
| Release | pyproject 1.5.1 = manifest 1.5.1 = CHANGELOG top 1.5.1 (2026-08-27) = tag url4-v1.5.1; PyPI latest 1.4.1; 13 commits to packages/url4 since the tag |

## 2. Findings

### F1. [stale-publish] PyPI is two releases behind the tags (1.5.0, 1.5.1 never published)
- Evidence: `https://pypi.org/pypi/url4/json` lists 0.1..1.4.1; tags url4-v1.5.0 and url4-v1.5.1 exist; release-url4.yml header (AIDEV-NOTE OME-910) warns the Trusted Publisher entry still names `OpenMined/screamingface` and OIDC does not follow the org rename.
- Cannot rule out: the publish job may be failing for another reason, or PyPI publish for 1.5.x was intentionally paused. I did not read the Actions run history.
- Interest: every external user of `pip install url4` gets 1.4.1. 13 unreleased commits include `feat(url4)` (09-09 Log emission, 09-23 iteration index) and a `refactor(engine)!` (09-27). The release train is silent for 6 weeks.
- Action: read the last `Release url4` run; fix the PyPI trusted-publisher owner string; confirm no open release-please PR is stalled. Reversibility: tier 1 (config only; a PyPI release itself is irreversible, yank only).

### F2. [broken-example] url4_examples.ipynb cell 0 imports a name that does not exist
- Evidence: `from url4 import run` -> `ImportError` (verified with the package .venv). `run` is not in `url4.__all__`; it lives in `url4.dag` (examples/utils.py:30 itself imports it from `url4.dag`). Cells 1, 3, 10, 17 call `run(...)`. Saved outputs show it ran once (execution_count 1) so it broke after that. examples/ last touched 2026-07-15 (the v1 import commit) while 38 src commits followed.
- Cannot rule out: the notebook may have been run against an older install; git -S did not pinpoint when `run` left the top-level namespace.
- Cells 1-2 also call live `https://syfthub.openmined.org`, an external host (a third-party site whose availability the repo does not control). The saved output is an HTML page, not a url4 result, so the demo shows nothing useful offline. url4_client and url4_server notebooks import only `__all__` names and use `*.example.com` hosts.
- Interest: the first thing a new reader runs fails.
- Action: change line to `from url4.dag import run` (or re-export), drop or stub the syfthub cells, then add a nbclient smoke job. Reversibility: tier 1.

### F3. [no-gate] examples/ has no CI at all
- Evidence: url4-tests.yml never mentions examples or notebooks; ruff/pyright config covers `src` and `tests` only (pyrightconfig include); `ruff check examples` passes when run by hand, so utils.py (452 lines, imports graphviz and IPython) is lint-clean today but nothing enforces it. deptry: IPython and graphviz are not runtime deps (graphviz only in `notebook` group; IPython nowhere).
- Cannot rule out: another repo workflow executes the notebooks (grep found none).
- Interest: F2 went unnoticed for this reason.
- Action: add `examples` to pyright include and a CI step that executes the notebooks with the `notebook` group and `IPython`/`ipykernel` declared. Reversibility: tier 1.

### F4. [hidden-coupling] consumers import 9 private url4 symbols; engine src depends on `url4.cli._config` and `url4.cli._serve`
- Evidence: see census. Engine src: world/config.py:65-68 imports `_toml_data_map`, `_toml_identity_map`, `_toml_shelf_map`; factory.py:48 imports `url4.cli._serve` (public-looking names in a private module). Tests: `_error_payload` (3), `_error_info`, `peer._owned`, `cli._config.ProviderSpec`.
- Cannot rule out: the engine and url4 are pinned together by editable path (apps/screamingface-engine/pyproject.toml:111), so a break is caught by engine CI, not shipped. External consumers via PyPI do not exist yet for these.
- Interest: the 2026-09-22 layer restructure (cba47c0fd) already moved modules; any minor release can break the engine silently if CI path filters miss it (they include `packages/url4/**`, so they do not).
- Action: promote the three engine-needed items to a public `url4.cli`/`url4.serve` surface (or `__all__`), leave test-only reaches to private names; then add a ratchet counting `from url4.*\._` in apps/. Reversibility: tier 1.

### F5. [packaging-duplication] screamingface wheel vendors url4 as a top-level `url4/` package with no dist-info and no declared dependency
- Evidence (this refutes the orchestrator's "broken wheel" claim): packages/screamingface/scripts/runtime_build_hook.py `_vendor_runtime` force-includes `packages/url4/src/url4` as `url4`, aigateway, scoreboard and screamingface_engine into every wheel (not only the `runtime` extra). Editable dev installs use a live `.pth` (`_point_at_live_sources`), which is how its tests and CI get url4. `uv.lock` has 0 url4 entries because nothing is declared. scripts/check_distribution.py asserts `url4/__init__.py` is in the wheel. The vendoring arrived with #590 (2026-08-18); the `from url4 import` in screamingface source dates from the first commits, so no dependency was removed. `import screamingface` works in a clean install.
- Cannot rule out: (a) `pip install screamingface url4` (the PyPI one, 1.4.1) writes into the same `site-packages/url4/` directory; whichever installs last wins and `pip uninstall` of either deletes shared files. I did not test this. (b) `pip list` shows no url4 version for the vendored copy. (c) the vendored url4 declares httpx via screamingface's own dependency; url4[streaming] pydantic is not declared in the base install (screamingface imports only core.nodes and top-level names, so fine today).
- Interest: a user who installs both packages gets undefined behavior; the studio sidecar lock has no url4 entry (apps/screamingface-studio/runtime/pyproject.toml:12 `[tool.uv.sources] url4 = ...` is dead because url4 is not a dependency there).
- Action: record the decision in the screamingface README; add a `Conflicts`/`Provides` note or a test that fails if `url4` is installed beside the wheel; remove the dead source line in studio runtime. Reversibility: tier 1 for the doc and dead line; tier 3 for changing the vendoring model.

### F6. [consumer-declaration] engine and studio extras
- Evidence: engine declares `url4[streaming]` (pyproject.toml:38) with path source, editable. It does not declare `[server]`; engine has its own `uvicorn[standard]>=0.52.1`, so the `url4 serve` path is covered. Studio runtime has no direct url4 dependency (via screamingface[runtime], `uvicorn[standard]` already there), so `[server]` is not needed. Verdict: declarations are correct today.
- Cannot rule out: the engine imports `url4.cli._serve` (F4) which may import uvicorn lazily; if it ever imports eagerly the declared set still holds because of the engine's own uvicorn.
- Action: none. Reversibility: n/a.

### F7. [lower-bound] `pydantic>=2.13.4` is a latest-minor pin, not a needed floor
- Evidence: streaming code uses only BaseModel, ConfigDict, Field, model_validator, TypeAdapter and discriminated unions (all pydantic 2.0+); the floor was copied from the engine's pin on 2026-07-29 (ac888c5c5). Suite passes on pydantic 2.13.4 (the declared floor) but I did not test older.
- Cannot rule out: a pydantic 2.1x bug the wire contract depends on.
- Interest: embedders of the PyPI package are forced to a recent pydantic for no stated reason.
- Action: test `pydantic==2.9` in a scratch env; if green, loosen or add a comment. Reversibility: tier 1. Low priority.

### F8. [python-support] 3.14 works but is not declared or gated; upper bound unbounded without a guard
- Evidence: full suite passes on Python 3.14.7 with locked versions. Classifiers and CI matrix stop at 3.13. Studio runtime caps `<3.14` (sidecar reason, separate). Dependabot and uv.lock are fresh (locked 2026-09-29).
- Cannot rule out: 3.14-only warnings under `-W error` (only url4 DeprecationWarnings are errors).
- Action: add 3.14 to the matrix and classifiers, or state in pyproject why it is omitted. Reversibility: tier 1.

### F9. [test-hygiene] `importorskip("pydantic")` can hide the whole lifecycle terminal-frame test file
- Evidence: test_lifecycle_terminal_frame.py:25. CI runs plain `uv sync` which installs the dev group, and dev contains `url4[streaming]` (pyproject.toml), so pydantic is present and the file runs in CI. A failing install (or someone removing the dev line) would skip it with only an "s" in the output; `-rs` is not set in CI.
- Cannot rule out: other test files import pydantic-dependent code without the guard (they would fail loudly, which is fine).
- Action: replace by a plain import (fail, not skip) because the dev group guarantees it; keep test_import_isolation for the absence case. Reversibility: tier 0.

### F10. [flake-risk] one real-time wait in the serve-app suite
- Evidence: tests/unit/test_serve_app.py:111 `await asyncio.sleep(0.1)` to let the first request "enter and hold the only slot", then asserts the second gets 503. On a loaded runner the first may not yet hold the slot; then the second request takes it and blocks on the gate until the 5 s timeout, so the test fails or hangs 5 s. Other sleeps are safe: four `sleep(0)` yields (test_dag.py:75,101,189,212), 30/10/5 s sleeps are cancel/timeouts targets (test_dag.py:251,655; test_serve_app.py:124 expects 504), injected delays in sink fakes, subprocess killed at 0.1 s timeout (test_serve_backends.py:43).
- Cannot rule out: flake history in CI (not checked). 1360 tests passed locally 2 times with 0 failures.
- Action: wait on an event set by the handler on entry instead of sleeping. Reversibility: tier 0.

### F11. [verified-ok] guards and formal-model stand-in
- `_no_real_listen` autouse (tests/conftest.py:42) plus `hide_uvicorn` fixture plus a 10-minute job timeout: sound; the local .venv has uvicorn while CI base job does not, and the suite still passes both ways (hide_uvicorn is what makes it so). Note local .venv differs from CI (3.13 + uvicorn + extras).
- The formal-model stand-in BFS (tests/unit/test_formal_models.py) is a 40-line checker that keeps the buggy model producing its violation and the fixed model clean; state bound 10,000. No drift found; the real `fm.py` driver is a local skill, so the stand-in is the only CI check. Interest: low. Action: none.

### F12. [unverifiable-citations] 566 spec-section citations (69 files) point at a document that is not in the repo
- Evidence: tests/spec/*.py cite "Spec §3.3 / §7", "§5.3" (iteration), "§4.5", etc.; src docstrings cite §5.3.11.3. docs/spec/2026-07-11-url4-package-v1-spec.md section 0 says such decimals reference "the url4 *language* spec", the normative authority, which is external. In the in-repo spec §3.3 does not exist and §5.3 is "Hybrid laziness", so the in-repo document cannot validate the tests. I sampled test_wire_spec (§3.3/§7), test_iteration_spec (§5.3), test_mandatory_intent (OME-508): internal consistency looks fine (test names match their cited topics) but I could not check the numbers against the language spec.
- Cannot rule out: citation drift after the language spec was renumbered.
- Interest: a reviewer cannot confirm a conformance test tests the clause it cites.
- Action: vendor or link the language spec version (with a pinned revision) in packages/url4/docs, and add a one-line header test that checks the revision tag. Reversibility: tier 1.

### F13. [coverage-scope] streaming is gated only in the engine lane, at an aggregate threshold
- Evidence: pyproject coverage omit `src/url4/streaming/*`; engine CI (screamingface-engine-tests.yml:73-76) uses `--cov=url4.streaming --cov=screamingface_engine --cov-fail-under=80` aggregate, so streaming can fall below 80% while the engine compensates. url4's own suite also has 7 test files that import url4.streaming. Engine job triggers on `packages/url4/**`, so streaming changes are tested.
- Cannot rule out: the actual streaming coverage number (not measured; needs the engine suite and its deps).
- Action: add a per-package floor for `url4.streaming` in the engine job (second `--cov-fail-under` via coverage report `--include`). Reversibility: tier 1.

### F14. [cosmetic] CHANGELOG compare links mix `OpenMined/screamingface` (<= 1.5.0) and `ScreamingFace/screamingface` (1.5.1)
- Evidence: CHANGELOG.md lines 3 vs 21+. Redirects work. Release tag naming `url4-v<semver>` is consistent with release-please config (`component: url4`, `tag-separator: -`) and with the release workflow trigger. Version trinity matches (see census). No action.

## 3. Recommended sequence

1. Release lane first: inspect the failing/absent PyPI publish for 1.5.0 and 1.5.1 and fix the Trusted Publisher owner (F1). Everything else in the package is blocked from reaching users until this works.
2. Fix the examples and put a gate on them: `from url4.dag import run`, remove the syfthub live calls, execute notebooks in CI (F2, F3). Add a ratchet for private-url4 imports in apps/ and plan the public surface for the 3 engine src imports (F4).
3. Small test cleanups: turn `importorskip` into a plain import (F9), replace the 0.1 s sleep with an event (F10), add Python 3.14 to the matrix (F8), document the vendoring decision for screamingface (F5).

## 4. Blind spots

- GitHub Actions run history and PyPI publisher settings (needed for F1 and flake rates).
- Whether `pip install screamingface url4` actually collides (F5); needs a clean venv install test.
- The external language spec (F12); cannot check section numbers.
- Streaming coverage number and the engine suite (F13); engine tests not run (lane scope).
- Old pydantic/httpx versions below the declared floors; only floors tested.
- uv.lock freshness checked against PyPI latest, not against a `uv lock --check` (would risk writing; skipped). `uv.lock` pins match pyproject by eye only.
- Notebook execution not attempted (the first cell fails on import; the live host cells call a third-party site).
- Orchestrator's "23 sleep hits" not reproduced (11 lines in tests/); possibly counted src or `sleep(0)` variants elsewhere.
