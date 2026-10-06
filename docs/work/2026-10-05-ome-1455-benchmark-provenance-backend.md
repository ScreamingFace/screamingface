---
ticket: OME-1455
stack: screamingface-engine
status: done
started: 2026-10-05
finished: 2026-10-05
---

# ome-1455-benchmark-provenance-backend — the provenance fields, importer reads, Scoreboard and SDK copies (PR 2 of 4)

## Intent

Every Benchmark can now declare its Benchmark Provenance, a content warning, its notebook, a
Human Baseline and a Frontier Score; the Engine derives the Benchmark Saturation verdict and
serves it; the importer fills what inspect's `eval.yaml` and arXiv know; the Scoreboard and the
SDK carry the block. A conformance test is strict from this PR behind a grandfather allowlist of
the Benchmarks registered today, so a Benchmark onboarded before the values PR must already
carry the fields. No page renders anything yet (PR 4) and no value is sourced yet (PR 3).
Spec: `docs/spec/2026-10-05-OME-1455-benchmark-provenance.md`; plan:
`docs/plan/2026-10-05-OME-1455-benchmark-provenance.md`, section "PR 2".

## Planned changes

Plan steps 1 to 12, in order. Files:

- Engine `benchmarks/definition.py` (shapes, fields, validation, `_metadata`), the three
  variant factories, `screamingface_engine_inspect/single_shot.py`, `benchmarks.py`
  (`BenchmarkSpec`), `importer.py` (`eval.yaml` + arXiv readers, generated lines).
- Engine tests: `tests/unit/test_benchmark_provenance.py` (shapes + rules + verdict),
  `tests/unit/inspect/test_benchmark_provenance_conformance.py` (allowlist, inspect lane) +
  `tests/unit/test_benchmark_provenance_twins.py` (fixture probe + key-set twins),
  `tests/unit/inspect/test_importer_provenance.py` + fixtures; extension of
  `test_benchmark_display_metadata.py`'s revision-unchanged and seeds-from tests.
- Scoreboard `seed.py`, `scores/models/benchmark.py`, migration `0018_benchmark_provenance.py`,
  `scores/schemas.py`, `scores/store.py`; tests `test_seed_engine_catalog.py` (+ regenerated
  `tests/fixtures/engine_catalog.json`), `test_leaderboard_routes.py`.
- SDK `_catalogue_vocabulary.py`, `_engine/catalog_contract.py`, `discovery.py`,
  `_runtime/bootstrap.py`; tests per the plan; public-surface snapshot + CHANGELOG.

## Test plan

- RED first per step, per the plan's "Verify" lines. Invariants defended: no new field enters any
  revision (revision-unchanged test); a key served is a key seeded (ast twin); a silent gap on a
  non-grandfathered Benchmark fails by name; `NotPublished` passes and is omitted on the wire;
  the verdict is `saturated` / `open` / `unknown` on the three fixtures and ignores the baseline;
  no test opens a socket.

## Acceptance

- Spec §7, "After PR 2".
- Gates: `run_gates.py screamingface-engine`, `run_gates.py scoreboard`,
  `run_gates.py screamingface --skip-append-only` (owner press for the snapshot).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus a new Engine module `benchmarks/provenance.py` (shapes,
  rules, verdict, served block; keeps `definition.py` under the 450-line ceiling) and a new
  plugin module `screamingface_engine_inspect/provenance_facts.py` (eval.yaml + arXiv readers,
  generated lines); the Task-replay row renderer writes them (the Hugging Face path, which
  also wrote them until the OME-1460 fold deleted it on main, is gone).
  Scoreboard: `ProvenanceSchema.from_stored` (the one key-by-key reader, used by the seed's
  `_block_of` and by `benchmark_to_schema`), migration
  `0018_benchmark_provenance.py` (two nullable AddFields, no backfill), `ProvenanceSchema` +
  `PublishedScoreSchema`, the `register_benchmark` sentinel for both columns, regenerated
  `tests/fixtures/engine_catalog.json`, a 0018 migration test on a populated database. SDK:
  `BenchmarkProvenance` + `PublishedScore` models on `screamingface.discovery` (not re-exported
  from the top-level package), decoder split into three helpers, seed twin reads
  `catalog_entry()` and emits the board's seed-row shape, snapshot + CHANGELOG, verdict
  vocabulary twins on all three sides (Engine, SDK, Scoreboard seed).
- **Commits:** one squashed commit after the rebase onto main past the OME-1460 fold
  (2026-10-06; the twelve originals are kept on `backup/OME-1455-pr2-pre-rebase`, local) ·
  PR [#1236](https://github.com/ScreamingFace/screamingface/pull/1236).
- **Gates (after the review round, 2026-10-06):** `run_gates.py screamingface-engine --base
  upstream/main --skip-append-only` ALL GREEN · `run_gates.py scoreboard --base upstream/main
  --skip-append-only` ALL GREEN · `run_gates.py screamingface --skip-append-only` ALL GREEN. CI lane 1 reproduced in
  an extra-less throwaway venv: the registry-wide file skips whole, the twins run. The append-only check flags two things by design,
  both owner presses: the regenerated SDK `public_surface_snapshot.json` (two new public
  models, two new `Benchmark` fields) and one line added to the Engine catalogue golden
  `test_benchmark_foundation.py` for the always-served `saturation` key, the same edit
  OME-1112 (`origin`) and OME-1257 (`difficulty`) made to that golden when they added an
  always-served key.
- **Deviations:** (1) the registry held **65** Benchmarks on 2026-10-05 after the rebase onto #1225 (8
  built-in + 57 imported), not the 57 the spec quoted from the recon; spec, plan and allowlist say 65.
  (2) A literal `TODO` in any provenance string, handle or `NotPublished` reason is refused at
  registration (not in the spec; needed because "TODO" is a valid GitHub handle and a non-blank
  reason). (3) Factories take one `**provenance: Unpack[ProvenanceFields]` block rather than
  thirteen parameters each. (4) The `tortoise-dev` companion skill the card names is not
  installed in this session; the migration copies `0011_benchmark_case_count.py`'s shape
  verbatim and is proven on a populated database by `test_migration_0018_provenance.py`.
  (5) The SDK seed twin reads the keys off `catalog_entry()` when a definition offers one,
  so it never re-derives a verdict; a bare definition seeds exactly as before.
  **Review round (PR 1236, 2026-10-06):** (6) the registry-wide conformance test moved to
  `tests/unit/inspect/` — the imported Benchmarks register only under the inspect extra, and
  only that CI lane installs it, so the strict rule was enforced on no CI lane; a guard test
  there fails if no `inspect-*` id registered, so the lane cannot green by skipping. (7) The SDK
  seed twin emitted the Engine's FLAT provenance keys, but a local stack hands that JSON to the
  Scoreboard's seed-row parser (`extra="forbid"`, block as one `provenance` field), not to its
  catalogue reader — the first declared value would have refused every local boot. It now emits
  the seed-row shape, reads the key list from the SDK decoder (`PROVENANCE_KEYS`; its own copy
  deleted and an Engine ast twin forbids it coming back), and the Scoreboard pins the shape
  against the real parser. (8) `ProvenanceSchema` reads the stored block with `extra="ignore"`
  (one stale key after a Helm rollback was a 500 on the whole listing); the seed stores only a
  verdict on the closed vocabulary (`SATURATION_VERDICTS` twin on the Scoreboard, parsed by the
  Engine's vocabulary test). (10) Second review round (Scoreboard, 2026-10-06): the nested
  `PublishedScoreSchema` kept `extra="forbid"` under the block's `ignore` (pydantic applies each
  model's own rule, so one stray nested key was the same whole-listing 500), and
  `benchmark_to_schema` validated whole-block and raised on any stored mismatch. Fixed
  structurally: `ProvenanceSchema.from_stored` reads key by key and is the ONE reader on both
  sides; the seed's duplicate `_CatalogProvenance`/`_CatalogScore` deleted (their name-only
  twin test with them — it had nothing left to compare); `SATURATION_VERDICTS` moved to
  `scores/schemas.py` so `register_benchmark` can refuse a word outside it (a code boundary
  refuses; the catalogue reader still nulls); the Engine's two ast twins repointed from
  `seed.py` to `scores/schemas.py`; the seed-shape test asserts pydantic's `extra_forbidden`
  code via `__cause__` instead of its English; the visibility exit guard records the new
  write-side raise. Pinned by four new Scoreboard tests (nested stray key, wrong-typed key,
  block with nothing readable → null, out-of-vocabulary word refused). (11) `contributors`
  (who typed the row) dropped on the owner's decision, 2026-10-06: one handle on 57 of 65
  rows, git holds it, and a syft-space data owner is a different field; `inspect_contributors`
  stays. Twelve fields now, on all three sides; the importer writes no TODO for it; spec,
  plan, glossary and the SDK CHANGELOG say so.
  (9) `human_baseline` / `frontier_score` are checked against their own class; the Hub-path
  importer applies the cleared-licence rule (OME-1273 D13) like the Task-replay path; the arXiv
  reader catches `http.client.HTTPException`; migration renumbered to `0018` on top of main's
  `0017_score_cache_saved_cost_archive`. Deferred to PR 3: baseline-without-source as a TODO
  line, the F2 cross-check fixture rows, a catalogue fixture row carrying provenance.
- **Deviation (12), 2026-10-06:** main merged the OME-1460 fold (#1254), which deleted the
  Hugging Face preparation path this branch had also edited (`render_generated_rows`,
  `_benchmark_lines`, the HF branch of `main()`). Resolved toward main: those functions stay
  deleted; the provenance hook lives only on the Task-replay path (`arxiv_fetch` →
  `read_provenance_facts` → `write_task_replay_rows`); the seven row tests moved from the
  deleted renderer to `render_task_replay_rows`. The branch was squashed to one commit so
  the conflict was resolved once, not per commit.
- **Owner-verify:** the `--skip-append-only` press for the SDK snapshot, the Engine catalogue golden
  and the regenerated Scoreboard `tests/fixtures/engine_catalog.json` (flagged only against
  upstream/main), plus the deletion of the seed's name-only twin test in the second review
  round (its subject class is gone); the three spec
  decisions already on the ticket; the spec's "57" became "65" (counted, not typed).
