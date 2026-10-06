# Plan — Benchmark Provenance, saturation verdict, and the four-PR carve (OME-1455)

- Spec: `docs/spec/2026-10-05-OME-1455-benchmark-provenance.md`. Ticket: OME-1455 (epic OME-1299).
- Ledger for this PR: `docs/work/2026-10-05-ome-1455-benchmark-provenance-spec.md`. Each code PR
  gets its own ledger and worktree from `upstream/main`.
- Numbers ① to ⑨ are the ticket's Architecture boxes. Every step names its file and the test
  that proves it; RED before GREEN per `sdlc-python`.
- Paths: Engine `E = apps/screamingface-engine/src/screamingface_engine`, inspect plugin
  `I = apps/screamingface-engine/src/screamingface_engine_inspect`, Scoreboard
  `S = apps/scoreboard/src/scoreboard`, SDK `K = packages/screamingface/src/screamingface`.

## PR 1 — spec, plan, glossary (this PR, `OME-1455-benchmark-provenance-spec`)

1. `CONTEXT.md` → four entries after Inverted Grade. Verify: the `**Term**: / _Avoid_:` shape.
2. `docs/spec/…`, `docs/plan/…`, `docs/tasks/2026-10-05-OME-1455-benchmark-provenance.md`,
   the ledger. Verify: `run_gates.py repo` green (mirror-status gate reads the ledger).
3. Ticket Scope patched to the four-PR carve; §3.1 and §4.1 deviations named there.

## PR 2 — backend (Engine + Scoreboard + SDK), strict test with the allowlist

Order is contract first, then the producers, then the copies, then the tripwires. Companion
skill: `tortoise-dev` for step 8. Owner press: `--skip-append-only` for step 11.

1. **① Shapes** → `E/benchmarks/definition.py`: `NotPublished`, `HumanBaseline`,
   `FrontierScore`, `Saturation` + `SATURATION_HEADROOM`, `saturation_verdict()`, the
   thirteen fields on `Benchmark` (default `None`), their rules in `_validate_display_metadata`
   (http(s) via `_WEB_URL`; GitHub handle regex; pinned-harness regex; `[0, 1]` scores; ISO
   month; new `_DISPLAY_LIMITS` entries; `inspect_contributors` refused unless
   `origin == "inspect_evals"`). Verify: new `tests/unit/test_benchmark_provenance.py`:
   one refusal test per rule (table-parametrized), the three verdict fixtures, and
   `test_benchmark_display_metadata.py`'s "adding display fields leaves the revision
   unchanged" test extended with every new field.
2. **④ Served** → `_metadata()` emits the keys present-only, `saturation` always; nested
   objects for baseline and frontier; `NotPublished` omitted. Verify: catalogue-entry and
   resource tests in the same file; `test_the_catalog_keeps_the_field_names_the_leaderboard_seeds_from`
   gains the new keys in its optional set.
3. **Factories** → `draco/variant.py`, `healthbench/variant.py`, `gdpval/variant.py`,
   `I/single_shot.py::single_shot_benchmark`: keyword-only pass-through of every new field
   (like `focus=`/`dataset_url=`). `I/benchmarks.py::BenchmarkSpec`: the new fields plus
   `upstream_case_count`. Verify: an assembled inspect row round-trips a full provenance set.
4. **③ Importer, eval.yaml** → `I/importer.py`: `read_eval_metadata(package, task_name)` via
   `importlib.resources`; the Task-replay row renderer emits `paper_url`, `inspect_contributors`,
   `human_baseline`, `upstream_case_count`, `license=` (from the Hub facts, SPDX-normalised),
   `harness_url` at the pinned tag, `notebook`,
   `frontier_score=NotPublished(reason="TODO")`, and `content_warning="TODO"` for the
   `Safeguards` group. Verify: `tests/unit/inspect/test_importer_provenance.py` on a copied MMLU
   `eval.yaml` fixture and one `Safeguards` fixture; a missing `arxiv` key leaves the field
   TODO (F1).
5. **③ Importer, arXiv** → `I/importer.py`: `read_arxiv_entry(arxiv_url)` → `(authors, bibtex)`
   with the `et al.` rule; recorded reply fixtures under `tests/fixtures/arxiv/`; network
   failure → TODO (F8). Verify: same test file; a test asserts no socket is opened (the
   existing no-network idiom of the importer tests).
6. **⑨ Conformance, Engine** → `tests/unit/inspect/test_benchmark_provenance_conformance.py`
   (the inspect lane: the only CI lane where the imported Benchmarks register; the fixture
   probe and the two key-set twins stay extra-less in `tests/unit/test_benchmark_provenance_twins.py`):
   `GRANDFATHERED: frozenset[str]` written from the registry on the day (65 ids on 2026-10-05, listed
   explicitly, never computed); parametrized over `BUILTIN_BENCHMARKS`; for an id not on the
   list: every required field present or `NotPublished`; `harness_url` pinned and upstream;
   `notebook` stem exists under `packages/screamingface/examples/` (read by path from the repo
   root, never imported); `upstream_case_count == case_count` unless a Named Deviation on the
   row; `inspect_contributors` only on Imported. Verify: the test is green on the day's
   registry and red for a fixture Benchmark missing `paper_url`.
7. **⑨ Conformance, cross-app key set** → same file: parse
   `S/scores/schemas.py::ProvenanceSchema` with `ast` (the `test_catalogue_vocabulary_conformance.py` idiom) and assert every served
   provenance key is a field there (F4).
8. **⑤ Scoreboard copy** → `S/scores/schemas.py`: `ProvenanceSchema.from_stored` (the one
   key-by-key reader, `extra="ignore"`); `S/seed.py`: `_block_of` calling it,
   `_CatalogEntry.provenance`, `_CatalogEntry.saturation`, `SeedBenchmark` twins, `as_seed()`;
   `S/scores/models/benchmark.py`: `provenance = JSONField(null=True)`,
   `saturation = CharField(16, null=True)`; migration
   `S/scores/migrations/0018_benchmark_provenance.py` (nullable, no backfill, rolling-safe
   note like `0011`); `S/scores/store.py::register_benchmark` defaults. Verify:
   `tests/unit/test_seed_engine_catalog.py` with a regenerated `tests/fixtures/engine_catalog.json`
   (one row carrying the full block, one carrying none); migration applies on an empty and a
   seeded database.
9. **⑥ Scoreboard API** → `S/scores/schemas.py`: `ProvenanceSchema` (`extra="forbid"`) and
   the two fields on `BenchmarkSchema`; `S/scores/store.py::benchmark_to_schema`. Verify:
   `tests/unit/test_leaderboard_routes.py`: `GET /v1/benchmarks` and
   `GET /v1/leaderboard/{id}` serve the block; `None` rows serve no block and `saturation`
   absent-or-`unknown` consistently with the Engine (pick absent → `unknown` at seed).
10. **⑧ SDK discovery** → `K/_catalogue_vocabulary.py`: `SATURATION_VERDICTS` twin;
    `K/_engine/catalog_contract.py`: `_provenance(item)` decoder (absent → `None`; shape-checked
    present); `K/discovery.py`: `BenchmarkProvenance`, `HumanBaseline`, `FrontierScore` public
    models, `Benchmark.provenance`, `Benchmark.saturation`; `K/_runtime/bootstrap.py::scoreboard_seed_json`
    emits both. Verify: `tests/test_benchmark_two_axis_wire.py` idiom for the new keys; the
    Engine/SDK vocabulary conformance twins pick up the new tuple; a bootstrap test asserts
    the seed JSON carries the block.
11. **Public surface** → regenerate the SDK snapshot + CHANGELOG line; gates:
    `run_gates.py screamingface-engine`, `run_gates.py scoreboard`,
    `run_gates.py screamingface --skip-append-only` (owner press).
12. **Ledger + mirror** → ledger outcome; mirror notes PR 2; Linear comment with the allowlist
    count.

## PR 3 — sourced values, allowlist emptied

1. **② Imported rows** → `I/benchmarks.py`: re-run the importer's provenance emitters on all
   57 rows (a one-off script in the PR's ledger, not committed) to fill `paper_url`,
   `inspect_contributors`, `human_baseline`, `upstream_case_count`, `license`, `harness_url`,
   `notebook`, `authors`, `citation`; then by hand: `frontier_score` with a cited source per
   row, `content_warning` for the
   Safeguards rows, `license_note` where the owner licence decision on OME-1273 names one,
   `NotPublished` with the real reason elsewhere. Verify: the conformance test with
   `GRANDFATHERED` shrunk to the eight built-ins.
2. **② Hand-built declarations** → `ifeval`, `medxpert`, `contracteval` definition modules;
   `draco`, `healthbench`, `gdpval` definition modules passing the values into their
   factories; harness links at the commits the docstrings already cite. Verify:
   `GRANDFATHERED = frozenset()`; every revision golden byte-identical
   (`test_published_revisions.py` and the six literal pins).
3. **Sources** → every `frontier_score.source_url` and `human_baseline.source_url` resolves
   (checked once by hand in the PR, listed in the ledger; no network in tests).
4. **Ledger + mirror** → PR 3 noted; Linear comment with the per-Benchmark source table.

## PR 4 — pages (after product sign-off of the mockup)

1. **⑦ Leaderboard page** → `apps/scoreboard/portal/benchmark.html` + `benchmark.js`: the strip
   under the title (authors · PAPER · HARNESS · DATASET · LICENCE ·
   CASES · HUMANS · FRONTIER with as-of · verdict badge · Cite copies `citation` · Run it opens
   the notebook on main); `content_warning` above the strip; links through `main.js::httpUrlOrNull`
   (its first caller); missing fields omitted, never a dash. Verify: `node --test` cases for the
   strip builder (every field present / none present / Inverted Grade frontier).
2. **⑦ Catalogue rows** → `portal/index.html` + `main.js::benchmarkRow`: verdict badge and
   Case count columns. Verify: `tests/portal/leaderboard-logic.test.js` additions.
3. **⑧ SDK views** → `K/_ui/cards.py`: per-Benchmark links replace `_ORIGIN_SOURCES`; authors,
   notebook name on the card; `Cases` and `Saturation` columns in
   `benchmarks_rows_html`; `K/_ui/leaderboard_view.py::_catalog_row`: the same strip from
   `LeaderboardInfo` once `K/leaderboard.py::LeaderboardInfo` carries the block. Verify:
   `tests/test_benchmark_catalogue_grouping.py` idiom; a generated-notebook check stays
   deterministic.
4. **Design law** → the `screamingface-design` skill for the strip and badge; screenshots in
   the PR body against the mockup.
5. **Ledger + mirror closed** → mirror `status: done`, ticket close comment.
