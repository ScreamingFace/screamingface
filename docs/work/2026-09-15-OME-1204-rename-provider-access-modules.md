---
ticket: OME-1204
stack: aigateway
status: done
started: 2026-09-15
finished: 2026-09-15
---

# OME-1204 — Rename the provider-access modules and test helpers without leading underscores

## Intent

Follow-up to A1 (`OME-1200`) of `OME-1138`. Owner decision: no file introduced by the
provider-access unit may have a name beginning with `_`; `__init__.py` is the required Python
exception; underscores between words in ordinary `snake_case` names are allowed. This unit renames
the five package halves and the two test helpers accordingly. Rename-only: no behaviour, public
Python API, HTTP mapping, OpenAPI or runtime-flow change; the compatibility shims stay; A2 is not
started.

## Planned changes

- `apps/aigateway/src/aigateway/core/provider_access/` (history-preserving renames):
  `_auth_mode.py → auth_mode.py`, `_defaults.py → defaults.py`, `_ports.py → ports.py`,
  `_selector.py → selector.py`, `_types.py → types.py`. Relative imports updated in `__init__.py`,
  `ports.py`, `selector.py`, `auth_mode.py`, `defaults.py`, `profile_backed.py`,
  `profile_authorize.py`, `profile_defaults.py`. Every name in `__all__` unchanged.
- `apps/aigateway/tests/unit/core/provider_access/`: `_provider_access_fake.py →
  provider_access_fake.py`, `_provider_access_harness.py → provider_access_harness.py`; imports
  updated in the harness, `test_provider_access_port_shape.py`,
  `test_provider_access_authorize_contract.py`, `test_provider_access_resolve_contract.py`,
  `test_provider_access_shims.py`.
- New `tests/unit/core/provider_access/test_provider_access_file_naming.py` — the architecture
  test that inspects the filename policy directly.
- Docs: spec §3.1 layout paragraph (`docs/spec/2026-09-09-OME-1138-converge-connections.md`);
  plan A1 reference (`docs/plan/2026-09-09-OME-1138-converge-connections.md`); a short follow-up
  reference appended to the `OME-1200` ledger (its Outcome is history and is not rewritten); this
  sub-issue listed in the umbrella ledger.
- No change to routes, schemas, stores, OpenAPI, or any existing test body.

## Test plan

- RED: `test_provider_access_file_naming.py` lists `*.py` in both directories and asserts that no
  name starts with `_` except `__init__.py`; it must fail naming exactly the seven current files.
- GREEN after the renames; the whole provider-access suite (170 tests) and the full stack gate stay
  green with no other test edited.

## Acceptance

- Naming test green; no reference to the old module names in `apps/aigateway` code or the active
  spec/plan; every `aigateway.core.provider_access` export importable under the same name.
- Focused suite green; `run_gates.py aigateway --base 837ab5b6 --skip-append-only` ALL GREEN;
  the exact append-only check is red only for the accepted rename exception. OpenAPI export
  byte-identical to `837ab5b6`; `git diff --check` clean; staged index empty (commit is a
  separately authorised step).

## Outcome

- **Actual files (all `apps/aigateway/` unless noted):**
  - Renamed: `src/aigateway/core/provider_access/` `_auth_mode.py → auth_mode.py`, `_defaults.py →
    defaults.py`, `_ports.py → ports.py`, `_selector.py → selector.py`, `_types.py → types.py`;
    `tests/unit/core/provider_access/` `_provider_access_fake.py → provider_access_fake.py`,
    `_provider_access_harness.py → provider_access_harness.py`. `types.py` is byte-identical to its
    original; the other four halves change one or two `from ._x import` lines; the two helpers change
    one comment line each plus the fake import in the harness.
  - Modified (import statements only; 40 lines changed across eight files): `__init__.py` (five
    relative imports + isort reorder), `profile_backed.py` (four + isort reorder),
    `profile_authorize.py` (1), `profile_defaults.py` (2); tests `test_provider_access_port_shape.py`
    (2), `test_provider_access_authorize_contract.py` (1), `test_provider_access_resolve_contract.py`
    (1), `test_provider_access_shims.py` (1 — the in-function import at line 197).
  - New `tests/unit/core/provider_access/test_provider_access_file_naming.py` (51 lines, 3 tests).
  - Docs: spec §3.1 layout paragraph rewritten to the new names and §8 gains D19 (module naming,
    decided 2026-09-15); plan §1 A1 row and §2 row `U1n`; the OME-1200 ledger gains a "Follow-up
    (2026-09-15)" section (its Outcome untouched); umbrella ledger and mirror gain one entry each;
    this ledger and its mirror.
  - Untouched: routes, schemas, stores, `main.py`, the shims, OpenAPI; all 42 names in `__all__`;
    no A2 work.
- **Commits:** `a762e7eb` `refactor(aigateway): drop leading underscores from provider-access
  modules` (body `Refs: OME-1204`). Staged by explicit path after the owner's authorisation of
  2026-09-15; git records seven renames with 97–100 % similarity (R097–R100).
- **RED → GREEN:** the naming test at `837ab5b6` fails twice, listing exactly `_auth_mode.py,
  _defaults.py, _ports.py, _selector.py, _types.py` and `_provider_access_fake.py,
  _provider_access_harness.py` (the exemption pin passes); green after the renames.
- **Gates:**
  - Focused `pytest tests/unit/core/provider_access`: **164 passed** — per-file collection identical
    to `837ab5b6` (161) plus the 3 new tests; the "170" in the OME-1200 ledger came from a wider
    invocation, no test was lost.
  - `run_gates.py aigateway --base 837ab5b6` (the exact command): **red at the append-only check**,
    offenders exactly `D _provider_access_fake.py`, `D _provider_access_harness.py`,
    `M test_provider_access_shims.py (line 197)` — the rename itself; the runner stops there.
  - `run_gates.py aigateway --base 837ab5b6 --skip-append-only`: ruff check ✓, ruff format --check ✓,
    pyright ✓, check_no_enterprise ✓, pytest --cov ≥80 % ✓ — **ALL GATES GREEN**, exit 0.
  - OpenAPI: `create_app().openapi()` as sorted JSON from the committed `837ab5b6` sources and from
    the renamed tree, same method and environment: **byte-identical** (55 563 bytes both).
  - `git diff --check` clean. No residual reference to the old names in the provider-access code,
    the active spec/plan or the umbrella docs; the OME-1200 ledger keeps 15 historical mentions by
    design; `core/plugin_base/_ports.py` and `core/chat_parameters/_types.py` are other packages,
    out of scope.
- **Deviations:**
  - The append-only check flags a rename under `tests/**` and an edit inside an existing test body
    as violations by design; here both ARE the owner-decided rename. The check was not weakened: the
    exact command ran for the record and the five remaining gates ran with the runner's own
    `--skip-append-only` flag. The owner explicitly accepted these three prior-test
    changes on 2026-09-15 (review verdict; rule 5 confidence gate satisfied).
  - `tortoise-dev` companion not invoked: no model, queryset, migration, transaction or lifespan
    change.
  - The OME-1200 ledger's test count (170) is left as written; this ledger records the per-file
    count (161 → 164).
- **Wisdom review:** pure rename — no behaviour, signature, exception, HTTP mapping or wiring
  changed (diff = import statements + two comment lines; `types.py` and OpenAPI byte-identical);
  the shim suite's size and hexagonal tests glob the package and still cover the renamed files; no
  secret, no fail-open path; the isort reorder in `__init__.py` / `profile_backed.py` is safe (no
  module imports the facade or `profile_backed` internally; no cycles).

## Review (2026-09-15, owner findings 1–2) — DONE

- **F1 P2 — unapproved topology rule.** The naming test also asserted that the test directory never
  has an `__init__.py`; the owner decision only exempts `__init__.py`, it does not forbid one. The
  assertion is removed; the test keeps the exact allowlist pin and the package-initialiser check
  (`test_provider_access_file_naming.py` 54 → 51 lines).
- **F2 P3 — dependency graph.** Plan §2: `U2` and `U3` now depend on `U1, U1n`, so the rename
  precedes A2 and A3 (D19 binds A3's `profile_admin.py`).
- **Re-run:** focused suite 164 passed; ruff check and ruff format --check clean; pyright 0 errors;
  `run_gates.py aigateway --base 837ab5b6 --skip-append-only` ALL GATES GREEN (exit 0). The exact
  command stays red at the append-only check for the three rename-caused entries, which the owner
  accepted.
- **Owner-verify:** none.
- **Corrections (post-commit owner review, 2026-09-15):** facade export count stated as 43,
  actual 42 at both `837ab5b6` and `a762e7eb`; the rename record now states only the verifiable
  git result (seven renames, 97–100 % similarity) instead of the command used. The commit holds
  23 paths: 16 code/test entries and 7 Markdown files.
