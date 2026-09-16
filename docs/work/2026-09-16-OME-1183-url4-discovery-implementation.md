---
ticket: OME-1183
stack: url4
status: in_progress   # implementation complete and green; NOT committed, NOT merged
started: 2026-09-15
finished:
---

# OME-1183 — the node's discovery surface, scope enforcement, and the url4.json migration

## Intent

Make OME-1183's configuration catalog real in code: serve the three `.well-known`
documents from a url4 node, enforce `x-scope` both at rest (a node file) and in flight (a
request), lint the catalogs that define it all, and migrate the node config file from TOML
to JSON as the parent spec locks.

Product link: a client hardcodes ONE url4 URL and discovers everything else — what a node
mounts, what each endpoint's schema is, and which items are the caller's to set. Without
enforcement that discovery is decoration; without the linter the schemas it rests on
cannot be trusted, because no JSON Schema validator will ever report a missing `x-scope`.

## Planned changes

Scope grew across the unit as facts came in. Recorded honestly rather than back-fitted:

1. `url4.toml` → `url4.json` across 4 packages (the parent spec locks this).
2. The three `.well-known` documents served by `url4 serve`, plus `MountResolver`.
3. D1 — a carrier for user-scope values (blocked, then decided mid-unit).
4. Request-time enforcement.
5. A catalog linter and its CI gate.

## Test plan

- migration: every ported test module diffed by COLLECTED TEST NAME against its original,
  not by count; any name that disappears must be a justified rename or split
- the CI serve smoke, ported to JSON and run over real HTTP against the real binary
- carriers: both must produce an identical payload for the same values, and identical
  refusals for the same bad ones
- enforcement: a smuggled `credentials.api_key` must not get a `200`
- linter: a self-contained corpus, every negative case a MUTATION of the good catalog, and
  a guard that every `LintCode` is reachable by some mutation
- the gate: prove it goes RED on a real defect and returns `2` when sabotaged

## Acceptance

- `tomllib` gone from both config modules; `url4.toml` deleted
- all four package suites green, ruff + pyright clean
- a config-bearing request can no longer receive a silent `200`
- the catalog gate fails on a scopeless leaf and on its own breakage

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** 47 tracked changes + 16 untracked, across `packages/url4`,
  `apps/screamingface-engine`, `packages/screamingface`, `apps/aigateway`, `.github/`.
  New: `packages/url4/src/url4/discovery/` (8 modules, ~1.9k lines), 6 test modules,
  `.github/workflows/catalogs.yml`, `.github/scripts/lint_catalogs.py` (+ its tests),
  this ledger, and `docs/spec/2026-09-16-OME-1183-config-carriers-and-enforcement.md`.
  Deleted: `apps/screamingface-engine/url4.toml`.

- **Commits:** none — the owner has not authorised a commit. Work sits on the branch.

- **Gates:**
  | gate | result |
  |---|---|
  | `packages/url4` | 1411 passed |
  | `apps/screamingface-engine` | 2879 passed, 8 skipped |
  | `packages/screamingface` | 1467 passed, 23 skipped |
  | wheel distribution check | pass — ships `_runtime/resources/url4.json` |
  | `verify_chart_wiring.py` | 112/112 |
  | `preview_contract.py classify` | a `url4.json` change triggers the engine preview |
  | `url4 serve` over real HTTP (the CI heredoc) | 8/8 |
  | catalog gate | red on a scopeless leaf; `2` when the linter is sabotaged |
  | ruff + pyright | clean, all four packages |

- **Deviations:**
  1. **Scope grew well past the original ask.** It began as "evaluate OME-1183" and became
     a migration plus an implementation. Each step was authorised, but the unit is large
     and would have been better as the sub-issues the parent spec already names.
  2. **Valid config returns `501`.** See spec §3.4. Owner-confirmed 2026-09-16.
  3. **`examples/` is deliberately uncommitted.** It is the corpus the work was built
     against. The parent spec's home for it is
     `docs/spec/2026-09-11-OME-1183-config-schemas/`.
  4. **No SDLC artifacts until now.** The owner waived the process for an exploratory
     phase and lifted the waiver at the end; this ledger is therefore written after the
     work, not at its start, which is the opposite of the rule.
  5. **A scratchpad loss cost ~212 tests.** The first walker lived outside the repo and
     was deleted between sessions. It was rebuilt INSIDE `packages/url4` with a
     self-contained corpus — the reason the tests no longer reference `examples/`.

## Errors worth keeping

Recorded because each was a wrong belief that testing corrected, not merely a typo.

1. **"The spec contradicts itself."** It did not — I had critiqued the digest's paraphrase.
   `new_README.md:135-138` carries the clause the digest dropped. Retracted before it
   reached anyone.
2. **"Header names cannot carry a dotted path."** Wrong: RFC 9110 `token` admits `.` and
   `_`. This objection was the main argument against the header carrier and it was false.
3. **"The bulk of the migration is `_serve.py`."** Wrong: ~110 of its 663 lines know the
   format. The real weight was a shipped-artifact chain across four packages, two of whose
   failure modes are silent.
4. **`is_group` keyed on `properties`.** `x-scope` is the discriminator. One occurrence in
   the whole corpus; a fixture without it passes a broken implementation.
5. **Route collection keyed on `path` only.** `RelUrl` uses `value`, so the source form
   `(/mount)!'x'` slipped through — the exact silent-drop this layer exists to stop.
6. **The refusal-reasons tuple indexed an empty list.** Built eagerly, so the guard that
   would have protected it was never consulted.
7. **`world_config` defined its own `WorldConfigError`.** `catalog/__init__.py` catches the
   production class, so `except` stopped matching and a config error would have escaped as
   a 500 instead of degrading to an unavailable catalog.

## Open, and owned elsewhere

- **Mount forwarding** — the `501`. Belongs to OME-1187 (the composer).
- **`docs/spec/2026-09-11-OME-1183-config-schema-scopes.md`** — the parent spec, still on
  an unpushed branch. Everything here was built from the Linear issue body plus
  `new_README.md`; a contradiction in that file would land on this work.
- **Sub-issues** — the parent spec names `url4-sdk`, `screamingface-engine`, `aigateway`,
  `py-screamingface`. This unit spans the first three; it was not decomposed.
- **`/v1/models` retirement** — needs the client repo.
