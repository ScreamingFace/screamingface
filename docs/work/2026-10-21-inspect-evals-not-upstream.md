---
ticket: OME-1698
stack: screamingface-engine
status: done
started: 2026-10-21
finished: 2026-10-21
---

# inspect-evals-not-upstream — name inspect_evals and the authors' code instead of "upstream"

## Intent

In the engine's inspect plugin, the word "upstream" means four different things: the inspect_evals
package, the benchmark authors' own code or data, a gateway provider, and our fetch source. On top
of that, this repo's git remote is also named `upstream`. A newcomer reading `upstream_scorer` or
"as upstream grades" can't tell which one is meant. The owner asked for each mention to name what
it refers to (2026-10-21):
- "inspect_evals" where the mention means the inspect_evals package;
- "the authors' code", "the dataset" or "the original harness", with a link where possible, where
  it means the benchmark authors' material.

No Benchmark revision may move.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/**`, except the `.py` files under
  `local_tasks/<name>/` that the revision hashes: prose plus the `upstream_case_count` field,
  which becomes `inspect_evals_case_count`. The field is engine-only and never served.
- `apps/screamingface-engine/tests/unit/inspect/**`: prose, import aliases, local names, and test
  function names. Test files are edited, never renamed, and the edits are recorded in
  `.claude/test-change-approvals/OME-N.json`.
- `apps/screamingface-engine/docs/**` (engine docs) and `local_tasks/*/README.md`, which the
  revision does not hash.
- `CONTEXT.md`: the Imported Benchmark, Named Deviation and Inverted Grade entries say inspect_evals
  outright, and the Benchmark Provenance harness line says the authors' original code.
- Out of scope:
  - mentions that mean a gateway provider, the git remote, or our fetch source;
  - root `docs/` (history);
  - every `.py` file under `local_tasks/<name>/` (`source_digest` hashes their bytes into the
    revision): 28 inspect_evals-sense lines and 23 authors-sense lines, deferred until published
    IDs are hand-set (OME-1610).

## Test plan

- This is a pure rename with no new behaviour, so no failing test drives it (see Deviations).
- Proof that nothing observable moved: a fingerprint of every registered Benchmark, covering its
  revision, served catalog fields and description, diffed against a clean `upstream/main`.
  - Revisions must be identical.
  - Only description text may differ.
- Run the edited test files plus the tests that import the renamed field, and ruff plus pyright on
  the touched files.

## Acceptance

- `git grep -i -w upstream` over the touched paths returns only the allowlisted lines:
  - the provider, git and fetch-source senses;
  - the lines inside revision-hashed local Task files.
- Zero Benchmark revisions move compared with `upstream/main`.
- The edited test files, ruff and pyright are green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** 44 as planned: 13 engine src (`benchmarks.py`, `case_source_prefetch.py`, `prepare.py`,
  `importer.py`, `import_replay.py`, `case_sources.py`, `provenance_facts.py`, `revision_inputs.py`,
  `scorer_adapter.py`, `single_shot.py`, `task_replay_rows.py`), 4 `local_tasks/*/README.md`, 2 engine
  docs, `CONTEXT.md`, 26 test files under `tests/unit/inspect/` (edited, none renamed). No `.py` under
  `local_tasks/<name>/` touched.
- **Left on purpose:** 21 lines outside hashed files (the gateway provider sense: `upstream_error`,
  "upstream 502", "upstream URL returned 404"; git: "upstream main"; our own pipeline:
  `scorer_adapter.py:96`; `CONTEXT.md:243` Case Source "pinned upstream place"; a FrontierScience test
  about the provider request) and 46 lines inside revision-hashed local Task files, deferred to after
  OME-1610.
- **Fingerprint:** all 83 Benchmarks, revision identical to `upstream/main`. Outside descriptions, one
  difference: the `cyse4_mitre_frr` NotPublished reason text (display only).
- **Commits:** see git log on the branch.
- **Gates:** 1228 passed (26 test files: every edited test plus every test importing `importer`,
  `prepare`, `case_sources`, `task_replay_rows`, `case_source_prefetch`, `provenance_facts`,
  `import_replay`); ruff check + format clean on 37 touched `.py`; pyright on them: one error, which
  predates this branch (`threat_intelligence.time`, visible only with the inspect extra, which CI's
  type check doesn't install).
- **Deviations:** no RED test: the change is a rename that a revision fingerprint guards, not new
  behaviour. The full gate runner is left to the pre-push hook and CI, per the owner's
  relevant-tests-only rule.
