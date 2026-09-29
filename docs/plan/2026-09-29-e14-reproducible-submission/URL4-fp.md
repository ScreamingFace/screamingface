# Plan — URL4-fp: the pure system fingerprint in `packages/url4` (E14, OME-1307)

- **Epic:** OME-1307 (E14, reproducible submissions). Wave 1 (D2).
- **Spec (the rubric):** `docs/spec/2026-09-29-e14-reproducible-submission/` —
  `erd.md` §2.3.2, `prd/system-registry.md` §3 and §7 (SR-2 to SR-5, SR-H3), `contracts.md` C11,
  `test-plan.md` §1 and §3.
- **Binding decisions:** D3 (the fingerprint formula with `exclude_bindings`; a seed that the
  Candidate declares stays in the hash; no candidate binding hashes the whole canonical url4),
  D7 X-18 (C11 is enforced by unit tests), D7 X-25 (the one-line engine `uv.lock` change rides
  with this unit).
- **Component:** `packages/url4` (one package). A lock-only refresh of
  `apps/screamingface-engine/uv.lock` is also necessary (D7 X-25). See step T0.
- **Branch / worktree (D1):** build in a temporary worktree on branch `unit/URL4-fp`, made from
  the HEAD of `e14-reproducible-submission-spec`:
  `git worktree add .claude/worktrees/unit-URL4-fp e14-reproducible-submission-spec` and then, in
  that worktree, `git checkout -B unit/URL4-fp e14-reproducible-submission-spec`.
  There is no PR, no Linear issue and no CI merge gate for this unit. After wave 1, the
  integrator merges `unit/URL4-fp` into `e14-reproducible-submission-spec` and runs the gates.
- **Plan:** this file, `docs/plan/2026-09-29-e14-reproducible-submission/URL4-fp.md`. Do not copy it.
- **Ledger:** `docs/work/2026-09-29-url4-system-fingerprint.md` (use the real start date),
  frontmatter `ticket: unfiled`.
- **Loop:** `sdlc-python`: ledger → RED → GREEN → gates → commit on `unit/URL4-fp`.
  Language of docs: ASD-STE100.

## 1. Scope

### 1.1 Test ids this unit owns

| Id | Test name (PRD §7) | Level |
|---|---|---|
| SR-2 | `fingerprint_equal_for_normalizable_spellings` (property, Hypothesis) | unit |
| SR-3 | `fingerprint_strips_answer_seed` | unit |
| SR-4 | `fingerprint_same_candidate_on_two_benchmarks` | unit |
| SR-5 | `fingerprint_parity_sdk_and_scoreboard` (the url4 half: 50 golden vectors) | integration |

Also: the C11 purity rule for `url4.fingerprint` (no PRD id; `contracts.md` C11 row 1), and the
url4 half of the SR-H3 precondition (two SDK candidates that differ only in the recipe display
name give one fingerprint; D3).

Supporting tests (no PRD id; they pin the edge cases in §7 and keep the 95 % coverage gate):
`test_fingerprint_is_lowercase_sha256_hex`, `test_fingerprint_without_binding_hashes_whole_canonical_url4`,
`test_fingerprint_unparseable_linked_url4_raises_url4_error`,
`test_fingerprint_unparseable_embedded_candidate_raises_url4_error`,
`test_fingerprint_first_candidate_binding_wins`, `test_fingerprint_custom_binding_name`,
`test_fingerprint_non_text_candidate_binding_is_no_binding`,
`test_fingerprint_iteration_root_hashes_whole_canonical_url4`,
`test_fingerprint_keeps_a_candidate_declared_seed`,
`test_fingerprint_sr_h3_recipe_name_is_excluded`,
`test_fingerprint_exclude_bindings_applies_to_direct_run`,
`test_fingerprint_exclude_bindings_is_root_level_of_the_system_only`,
`test_fingerprint_exclude_every_source_renders_an_empty_group`,
`test_canonical_system_url4_is_canonical`, `test_strategy_canonical_form_is_canonical`,
`test_vectors_file_has_fifty_unique_entries`, `test_vectors_match_their_independent_oracle`,
`test_vectors_hold_the_sr_h3_twin`.

### 1.2 Out of scope

- Every `SR-` id except SR-2 to SR-5: SR-1 and SR-6 to SR-20 belong to **SB-registry**.
- The scoreboard dependency on `url4` (`apps/scoreboard/pyproject.toml`, `Dockerfile`, CI path
  filters). This belongs to **SB-registry**.
- The choice of the exclude set for production calls. The url4 package does not name
  `_sf_recipe` in `src/`. The caller (SB-registry, and a later SDK call site) passes it.
- The scoreboard and SDK halves of SR-5 (the consumer tests). See §4.4.
- The url4 size cap and the `422 invalid_url4` mapping (SR-19, SR-E5 HTTP side). **SB-registry**.
  The cap is the existing 32,000-char cap with `422` (D7 X-22).
- The `fingerprint` NFR (64 KB in ≤ 50 ms). No timing test here: a wall-clock test is a flake
  source (test-plan §1 rule 7).
- A change to `.claude/scripts/check_layering.py`. That script is engine-scoped by its own
  docstring (`.claude/scripts/check_layering.py:1-47`). Decided: D7 X-18 — the unit tests of T7
  enforce C11 row 1.
- A refactor of the SDK `_candidate_text` helper
  (`packages/screamingface/src/screamingface/_evaluation/url4.py:207-218`) to call the new module.
- Any edit of `CHANGELOG.md` or the version: release-please owns them.
- Name rules, registry tables, migrations, JWS. None of them is in `packages/url4`.

## 2. Depends on

- **Units:** none. Wave 1. Start from the HEAD of `e14-reproducible-submission-spec` (D1).
- **Contracts:**
  - Implements C11 row 1: "`url4.fingerprint` is pure: no I/O and no imports from the SDK, the
    engine or the scoreboard."
  - Provides the function that C4 (submit) uses on the scoreboard side through SB-registry:
    `url4.fingerprint.system_fingerprint(linked, binding="candidate", *, exclude_bindings=frozenset())`.
    The production call is
    `system_fingerprint(linked, binding="candidate", exclude_bindings=frozenset({"_sf_recipe"}))` (D3).
- **Consumers after the wave-1 integration:** SB-registry (wave 2: SR-1, SR-5-SB, SR-H3 through
  SR-8, `backfill-systems`), and the SDK if an SDK unit calls it (spec gap G2, X-9).

### 2.1 Integration notes (for the integrator, D2)

- Wave 1 also holds SB-schema and GW-capture. No shared file with them:
  this unit changes only `packages/url4/**` and `apps/screamingface-engine/uv.lock`.
- `apps/screamingface-engine/uv.lock`: ENG-freeze (wave 2) and ENG-replay (wave 3) may also
  change it. This unit merges first. A later unit that touches the lock runs `uv lock` again
  after the merge; it does not hand-merge the lock.

## 3. Files

| Path | Action | Exemplar to imitate |
|---|---|---|
| `packages/url4/src/url4/fingerprint.py` | create | module docstring and style: `packages/url4/src/url4/core/__init__.py:1-21`; binding scan: `packages/screamingface/src/screamingface/_evaluation/url4.py:207-218` |
| `packages/url4/tests/unit/test_fingerprint.py` | create | `packages/url4/tests/unit/test_public_api.py:1-60` (plain pytest functions, STORY docstring) |
| `packages/url4/tests/unit/test_fingerprint_properties.py` | create | first Hypothesis test in the repo; test style as above |
| `packages/url4/tests/unit/test_fingerprint_parity.py` | create | `packages/url4/tests/unit/test_public_api.py:1-60` |
| `packages/url4/tests/fixtures/fingerprint_vectors.json` | create | generated once (§6, T5). The `tests/fixtures/` directory is new. |
| `packages/url4/tests/unit/test_fingerprint_purity.py` | create | `packages/url4/tests/unit/test_import_isolation.py:31-47` (subprocess probe `_loaded_after_import`), `:64-67` (teeth check) and `:99-116` (AST import scan) |
| `packages/url4/pyproject.toml` | change | add `hypothesis` to `[dependency-groups].dev` with `uv add --dev hypothesis` (it writes the specifier) |
| `packages/url4/uv.lock` | change | written by `uv add` / `uv lock` |
| `apps/screamingface-engine/uv.lock` | change (lock only; D7 X-25) | `uv lock` in `apps/screamingface-engine`. Reason: that lock records url4's `requires-dev` (`apps/screamingface-engine/uv.lock`, the `url4` package block, `[package.metadata.requires-dev]`), and its CI runs `uv lock --check` on `packages/url4/**` (`.github/workflows/screamingface-engine-tests.yml:7,15,54`) |
| `packages/url4/ARCHITECTURE.md` | change | add one row to "The layer map" table: `leaf` · `url4.fingerprint` · "The system identity of a linked url4. Pure." · `core` + standard library. Add one bullet under "The direction rule": "`url4.fingerprint` imports `url4.core` and the standard library only." |
| `packages/url4/README.md` | change | add a short "System fingerprint" section: the call, the `exclude_bindings` parameter (the caller names the metadata bindings to drop), the return value, and that the value is the identity the leaderboard uses |

Do **not** change `packages/url4/src/url4/__init__.py`. The spec path is
`url4.fingerprint.system_fingerprint`. Keep the root namespace unchanged
(`packages/url4/tests/unit/test_public_api.py:37-40` keeps internals off the front page).

Do **not** change `packages/url4/tests/unit/test_layering.py`. Its
`test_the_walk_actually_sees_every_layer` asserts an exact layer set, and a prior test must not
change (`test_layering.py:123-128`). A top-level `fingerprint.py` maps to no layer there
(`_importer_layer`, `test_layering.py:67-75`), so the file is skipped. The new purity test owns the rule.

Do **not** add `fingerprint.py` to `scripts/check_module_size.py` `BASELINE`. It is small.

## 4. Signatures and data shapes

### 4.1 `packages/url4/src/url4/fingerprint.py`

Exact content shape (the implementer writes the docstrings in the repo style; the logic is fixed):

```python
"""url4.fingerprint — the system identity of a linked url4 (E14, OME-1307).

A *system* is "the url4 minus the benchmark". The ScreamingFace linker embeds the
Candidate as the text value of a zero-weight ``candidate`` binding in the linked url4
(packages/screamingface/src/screamingface/_evaluation/linking.py:34-40). The fingerprint
is the sha256 of that Candidate's canonical text, after the caller's metadata bindings are
removed from the Candidate's root: ``render(drop(build(candidate), exclude_bindings))``.

INVARIANT: pure. No I/O, no clock, no randomness, no environment. It imports the
standard library and ``url4.core`` only (contracts.md C11).
INVARIANT: the answer seed has no channel into this value. The seed travels out of band
(the ``X-Answer-Seed`` header), never in the url4 text. A seed that the Candidate itself
declares (a ``seed`` query parameter) is part of the system and stays in the hash.
INVARIANT: this module names no SDK binding. The caller passes ``exclude_bindings``.
"""

from __future__ import annotations

import dataclasses
import hashlib

from url4.core.nodes import Expression, Node, Source, Text
from url4.core.parser import build
from url4.core.render import render

CANDIDATE_BINDING = "candidate"


def canonical_system_url4(
    linked: str,
    binding: str = CANDIDATE_BINDING,
    *,
    exclude_bindings: frozenset[str] = frozenset(),
) -> str:
    """The canonical text of the system inside ``linked``.

    - ``linked`` has a root-level source named ``binding`` whose value is text →
      the system is ``build(that text)``.
    - no such source (a direct run, SR-E5) → the system is ``build(linked)``.
    Then every root-level ``Source`` of the system whose name is in ``exclude_bindings``
    is removed, and the result is ``render``-ed.
    Raises the url4 errors unchanged (``url4.Url4Error``: ``ParseError``, ``RenderError``).
    """
    root = build(linked)
    embedded = _binding_text(root, binding)
    system = root if embedded is None else build(embedded)
    return render(_without_bindings(system, exclude_bindings))


def system_fingerprint(
    linked: str,
    binding: str = CANDIDATE_BINDING,
    *,
    exclude_bindings: frozenset[str] = frozenset(),
) -> str:
    """Lowercase hex sha256 (64 chars) of ``canonical_system_url4(...)``, UTF-8."""
    canonical = canonical_system_url4(linked, binding, exclude_bindings=exclude_bindings)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _binding_text(root: Node, binding: str) -> str | None:
    """The text value of the FIRST root-level source named ``binding``, else None."""
    if not isinstance(root, Expression):
        return None
    for node in root.sources:
        if isinstance(node, Source) and node.name == binding and isinstance(node.value, Text):
            return node.value.value
    return None


def _without_bindings(system: Node, exclude_bindings: frozenset[str]) -> Node:
    """``system`` with its root-level sources named in ``exclude_bindings`` removed."""
    if not exclude_bindings or not isinstance(system, Expression):
        return system
    kept = tuple(
        s for s in system.sources if not (isinstance(s, Source) and s.name in exclude_bindings)
    )
    return dataclasses.replace(system, sources=kept)


__all__ = ["CANDIDATE_BINDING", "canonical_system_url4", "system_fingerprint"]
```

Rules for the implementer:

- Both public functions have exactly three parameters: `linked`, `binding`, and the
  keyword-only `exclude_bindings` (default `frozenset()`). There is **no** fingerprint
  parameter and **no** seed parameter (SR-1, SR-3).
- The match rule for `binding` is the same as the SDK rule: root `Expression`, a `Source` with
  `name == binding` and a `Text` value (`packages/screamingface/src/screamingface/_evaluation/url4.py:207-218`).
  Do not check the weight.
- The exclude rule applies to the root of the **system** only (the embedded Candidate, or the
  whole url4 when there is no candidate binding). It does not walk into nested expressions and
  it does not touch the linked root. Match on `Source.name` only (any value type). The SDK puts
  `_sf_recipe` at the Candidate root (`packages/screamingface/src/screamingface/_evaluation/topology.py:14`).
- An empty `exclude_bindings` returns the system unchanged, so the default call gives the ERD
  value `sha256(render(build(candidate)))`.
- `Expression` is a frozen dataclass with the fields `sources`, `intent`, `broadcast`, `params`
  (checked on 2026-09-29). `dataclasses.replace` keeps the other three fields.
- Do not catch or wrap url4 errors. The consumer maps `url4.Url4Error` to `422 invalid_url4`.
  Checked facts: an unbalanced text raises `ParseError`; an empty string parses and then
  `render` raises `RenderError` (both are `Url4Error`).
- Put `__all__` at the end of `fingerprint.py`, as shown. No `__all__` change elsewhere.
- Complexity limits hold (`packages/url4/pyproject.toml`: max-complexity 8, max-returns 3,
  max-branches 7).

### 4.2 Contract for consumers (SB-registry and the SDK)

```python
from url4.fingerprint import canonical_system_url4, system_fingerprint

SDK_METADATA_BINDINGS = frozenset({"_sf_recipe"})   # the consumer owns this constant (D3)

fingerprint: str = system_fingerprint(
    score_submission.url4_expression, exclude_bindings=SDK_METADATA_BINDINGS
)                                                    # CHAR(64) value
candidate_url4: str = canonical_system_url4(
    score_submission.url4_expression, exclude_bindings=SDK_METADATA_BINDINGS
)                                                    # SystemRevision.candidate_url4
# except url4.Url4Error -> 422 invalid_url4
```

For equal arguments, `sha256(candidate_url4.encode("utf-8")).hexdigest() == fingerprint`
always holds. Consumers must pass the same `exclude_bindings` to both calls. The golden vectors
file records the set (§4.3), so a consumer that passes another set fails its SR-5 half.

### 4.3 Golden vectors file `packages/url4/tests/fixtures/fingerprint_vectors.json`

```json
{"schema": "url4.fingerprint.vectors.v1",
 "binding": "candidate",
 "exclude_bindings": ["_sf_recipe"],
 "vectors": [{"id": "c01-b1", "linked_url4": "…", "candidate_url4": "…", "fingerprint": "64-hex"}]}
```

- `binding` and `exclude_bindings` are the call arguments for every vector (the production call, D3).
- `candidate_url4` is the canonical system text **after** the exclude (so for `c08` and `c09` it
  has no `_sf_recipe` source).
- 50 entries: 10 candidates × 5 benchmark wrappers (T5 gives the exact inputs). Sort by `id`.
  `c08` and `c09` are the SR-H3 twin: they differ only in the `_sf_recipe` `name`/`named` keys,
  so their 10 vectors have one `fingerprint` (9 unique fingerprints in the file; checked on 2026-09-29).
- Write with `json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n"`.
- The file names `_sf_recipe` as test data. This is the caller's value, not a name in `src/`.

### 4.4 SR-5 parity: where each half lives (the scoreboard never imports the SDK)

- **url4 half (this unit):** `packages/url4/tests/unit/test_fingerprint_parity.py` proves that
  `url4.fingerprint`, called with the file's `binding` and `exclude_bindings`, gives the recorded
  value for all 50 vectors.
- **Scoreboard half (SB-registry, wave 2, id SR-5-SB):** a scoreboard test reads the same JSON by
  repository path (`<repo>/packages/url4/tests/fixtures/fingerprint_vectors.json`), asserts that
  the file's `exclude_bindings` equals the adapter's `SDK_METADATA_BINDINGS`, and runs each
  `linked_url4` through the scoreboard's fingerprint adapter (the code behind its
  `SystemFingerprinter` port). It imports only `url4` and `scoreboard`. It needs
  `packages/url4/tests/fixtures/**` in the scoreboard CI path filter. Exemplar for a
  cross-component fixture read by path: `docs/plan/2026-09-28-aigateway-cache-hit-metadata.md` Tasks 4-6.
- **SDK half:** the same read, through the SDK call site. No SDK unit owns it now (spec gap G2, X-9).
- Why this gives parity: all three halves compare to one frozen oracle. The SDK vendors url4
  into its wheel at build time (`packages/screamingface/scripts/runtime_build_hook.py:32-64`), and
  the scoreboard uses the path package, so a url4 change that moves a fingerprint fails the url4
  half first.

### 4.5 Ports and adapters

The fingerprint is a pure domain function. It needs no port and no adapter in `packages/url4`.
The scoreboard wraps it behind its own port (SB-registry). This unit adds no I/O.

### 4.6 Ed25519 JWS

None in this unit. `packages/url4` does not sign or verify anything.

## 5. Migrations

None. `packages/url4` has no database.

## 6. TDD order (RED first, risk order)

Rule for every RED: the test fails on an assertion or on the stub's `NotImplementedError`,
never on an import error or a `TypeError` from a missing parameter. So T1 creates the stub
with the full signatures (including `exclude_bindings`) first.

Shared test data (put it at the top of `tests/unit/test_fingerprint.py`; T3 and T4 reuse it):

- `C = "(model_1:0.0:/openrouter/model($input)!'Be brief')!'$model_1'"` (canonical).
- `B1 = build("(answer:0.0:/candidate(question)!'$candidate')!'$answer'")`.
- `def link(c: str) -> str: return render(expr(src(text(c), name="candidate", weight=0.0), B1, intent=text("")))`
  (the SDK linker shape, `packages/screamingface/src/screamingface/_evaluation/linking.py:37-38`).
- `def recipe(name: str, named: str) -> str:` returns
  `"_sf_recipe:0.0:'{\"recipe\":{\"binding\":\"model_1\",\"kind\":\"model\",\"name\":\"" + name + "\",\"named\":" + named + ",\"role\":\"model\"},\"schema\":\"screamingface.recipe.v1\"}'"`
  (the SDK recipe source shape; `sf.Model("openrouter/model", name="kevins-best")` gives
  `"name":"kevins-best","named":true`, checked on 2026-09-29).
- `S8 = "(model_1:0.0:/openrouter/model($input)!'Answer the request.')!'$model_1'"`.
- `A8 = "(model_1:0.0:/openrouter/model($input)!'Answer the request.', " + recipe("model", "false") + ")!'$model_1'"`.
- `A9 = "(model_1:0.0:/openrouter/model($input)!'Answer the request.', " + recipe("kevins-best", "true") + ")!'$model_1'"`.
- `SF = frozenset({"_sf_recipe"})`.
- Checked on 2026-09-29: `A8` and `A9` are canonical, and dropping `_sf_recipe` from either
  root renders exactly `S8`.

### T0 — dependency (no test; D7 X-25)

1. `cd packages/url4 && uv add --dev hypothesis`. Keep the specifier that `uv` writes.
2. `cd apps/screamingface-engine && uv lock`. Do not pass `--upgrade`. Check with `git diff`
   that the only change in `apps/screamingface-engine/uv.lock` is the new `hypothesis` line in
   the `url4` block `[package.metadata.requires-dev]`. If any other package version moves, stop
   and ask. This lock change rides with this unit (D7 X-25); record it in the ledger.
3. `uv lock --check` in both directories exits 0.

### T1 — stub

Create `src/url4/fingerprint.py` with the §4.1 signatures (all three parameters), docstrings,
`CANDIDATE_BINDING` and `__all__`. Each public body is `raise NotImplementedError`. Do not
write `_binding_text` or `_without_bindings` yet.

### T2 — SR-4 (H×M) and SR-5 (H×L): RED on the stub

Order inside T2: write T5 (the vectors data) and all T2 test files first, run them on the T1
stub (RED), then write the T2 GREEN.

**T2a — SR-4** `tests/unit/test_fingerprint.py::test_fingerprint_same_candidate_on_two_benchmarks`

- `linked_1 = link(C)`.
- `linked_2 = render(expr(src(text(C), name="candidate", weight=0.0), src("/benchmarks/draco/revision-1/cases", name="rows", weight=0.0), intent=text("$rows")))`
  (the shape of `packages/screamingface/tests/test_leaderboards.py:31-45`).
- Oracle: `expected = hashlib.sha256(C.encode("utf-8")).hexdigest()`.
- Assert `system_fingerprint(linked_1) == system_fingerprint(linked_2) == expected`, and the
  same with `exclude_bindings=SF` (C has no `_sf_recipe`, so the value does not move).
- Assert a different candidate `C2 = "(model_1:0.0:/openrouter/other($input)!'Be brief')!'$model_1'"`
  in `B1` gives a value `!= expected`.

**T2b — supporting tests** in the same file (each has its own oracle, computed with `hashlib`
from a literal, never from the code under test):

- `test_fingerprint_is_lowercase_sha256_hex`: `re.fullmatch(r"[0-9a-f]{64}", system_fingerprint(linked_1))`.
- `test_fingerprint_without_binding_hashes_whole_canonical_url4` (D3, OD-5 confirmed): input `C`
  itself (no binding) → `sha256(C)`. Also input `"(model_1:0:/openrouter/model?q=($input)!'Be brief')!'$model_1'"`
  → `sha256(C)` (the fallback canonicalizes with `render(root)`; checked on 2026-09-29).
- `test_fingerprint_iteration_root_hashes_whole_canonical_url4`: input
  `"/rows*(/m($item)!'a')!'b'"` (`build` returns an `Iteration`, not an `Expression`; checked)
  → `sha256` of that same literal, with the default and with `exclude_bindings=SF`. This covers
  the `not isinstance(..., Expression)` branch of both helpers.
- `test_fingerprint_non_text_candidate_binding_is_no_binding`:
  `L = render(expr(src("/benchmarks/x/cases", name="candidate", weight=0.0), src(text(C), name="system", weight=0.0), intent=text("")))`.
  The `candidate` value is a `RelUrl`, not a `Text`, so it is "no binding" (the SDK rule).
  `L` is canonical (`render` output; checked on 2026-09-29). Assert
  `system_fingerprint(L) == hashlib.sha256(L.encode("utf-8")).hexdigest()`.
- `test_fingerprint_unparseable_linked_url4_raises_url4_error`: `"((("` (`ParseError`) and `""`
  (`RenderError`) each raise `url4.Url4Error` (`pytest.raises(Url4Error)`).
- `test_fingerprint_first_candidate_binding_wins`: a root with two `candidate` text sources
  `C` then `C2`, built with `render(expr(src(text(C), name="candidate", weight=0.0), src(text(C2), name="candidate", weight=0.0), intent=text("")))`
  → `sha256(C)`. (Checked on 2026-09-29: url4 accepts the duplicate name, and the parsed
  first source holds `C`.)
- `test_fingerprint_custom_binding_name`: `C` under `name="system"` with intent `text("")`,
  called with `binding="system"` → `sha256(C)`; the same linked text with the default binding
  → `sha256(linked_text)` (the linked text is canonical because it is `render` output).
- `test_fingerprint_keeps_a_candidate_declared_seed` (D3, OD-2 default): `link("(model_1:0.0:/openrouter/model?seed=7&q=($input)!'Be brief')!'$model_1'")`
  and the same with `seed=8`, both with `exclude_bindings=SF` → two different values, each
  equal to `sha256` of its own candidate literal (both literals are canonical; checked on 2026-09-29).
- `test_canonical_system_url4_is_canonical`: `canonical_system_url4(linked_1) == C`, and for
  `x` in `(linked_1, linked_2, C)`:
  `hashlib.sha256(canonical_system_url4(x).encode("utf-8")).hexdigest() == system_fingerprint(x)`.

**T2c — SR-5** (do T5 first: it makes the vectors file this test reads):
`tests/unit/test_fingerprint_parity.py`

- Load `Path(__file__).parents[1] / "fixtures" / "fingerprint_vectors.json"`. Let
  `EXCLUDE = frozenset(data["exclude_bindings"])` and `BINDING = data["binding"]`.
- `test_vectors_file_has_fifty_unique_entries`: 50 entries, unique `id`, unique `linked_url4`,
  schema `url4.fingerprint.vectors.v1`, `binding == "candidate"`,
  `exclude_bindings == ["_sf_recipe"]`.
- `test_vectors_match_their_independent_oracle`: for each vector,
  `render(build(v["candidate_url4"])) == v["candidate_url4"]`,
  `"_sf_recipe" not in v["candidate_url4"]`, and
  `hashlib.sha256(v["candidate_url4"].encode("utf-8")).hexdigest() == v["fingerprint"]`.
  This check does not call the code under test. It passes on the stub by design (it is the
  fixture guard; say so in the ledger).
- `test_vectors_hold_the_sr_h3_twin`: for each `j` in 1..5, the vectors `c08-b{j}` and
  `c09-b{j}` have different `linked_url4` and the same `fingerprint`. Fixture guard, like the
  one above (it does not call the code under test).
- `test_fingerprint_parity_sdk_and_scoreboard`: for each vector (use `pytest.mark.parametrize`
  with `ids=` from `id`),
  `system_fingerprint(v["linked_url4"], BINDING, exclude_bindings=EXCLUDE) == v["fingerprint"]` and
  `canonical_system_url4(v["linked_url4"], BINDING, exclude_bindings=EXCLUDE) == v["candidate_url4"]`.
- Module docstring: say that the scoreboard half and the SDK half read this same file, with the
  same `exclude_bindings` (§4.4).

**RED reason (T2a, T2b, T2c):** run the three files on the T1 stub. Every test that calls
`system_fingerprint` or `canonical_system_url4` fails with the stub's `NotImplementedError`
(the stub imports cleanly and has every parameter, so this is not an import error or a
`TypeError`). The two `pytest.raises(Url4Error)` tests also fail, because
`NotImplementedError` is not a `Url4Error`. Write the counts in the ledger.

**GREEN (minimal):** write `_binding_text` and `system_fingerprint` exactly as in §4.1. Write
`canonical_system_url4` with two differences from §4.1: (1) when `embedded` is not None,
return `embedded` as it is (no `build`/`render`); (2) ignore `exclude_bindings` (no
`_without_bindings` yet). T3 and T4 make the final changes.

Expected after the T2 GREEN: all T2a and T2b tests are green. In T2c, the two fixture guards
are green, and `test_fingerprint_parity_sdk_and_scoreboard` is green for 40 vectors and **RED
for the 10 vectors `c08-*` and `c09-*`** (assertion: the recipe blob is still in the hashed
text). They stay RED until T4. Write this in the ledger. Do not change the vectors to make
them green.

### T3 — SR-2 (H×L) `tests/unit/test_fingerprint_properties.py::test_fingerprint_equal_for_normalizable_spellings`

Hypothesis property. Settings: `@settings(max_examples=200, deadline=None, derandomize=True, database=None)`
(no flake: fixed examples in CI; `database=None` so no `.hypothesis/` directory is written).

Strategy (all values from `st.sampled_from` or small `st.text`, so every draw is valid url4):

- `members`: `st.lists(member, min_size=1, max_size=3)`, where `member` is a tuple of
  - `path`: `st.sampled_from(["/openrouter/model", "/provider/a", "/provider/b", "/openai/gpt-5", "/anthropic/claude-opus"])`
  - `prompt`: `st.text(alphabet=st.sampled_from(list("abcXYZ 019.,?-'")), min_size=1, max_size=40)`
  - `params`: `st.lists(st.sampled_from([("temperature", "0.2"), ("max_tokens", "64"), ("top_p", "0.9")]), unique_by=lambda p: p[0], max_size=2)`
- `final`: `st.integers(min_value=1, max_value=len(members))` (use `st.data()` or `flatmap`).
- `spelling`: three booleans `weight_int`, `sugar`, `trailing_params`, and a separator from
  `st.sampled_from([",", ", ", ",   "])`.

Spell one member `i` (1-based) with `q = render(text(prompt))`:

- canonical form: `f"model_{i}:0.0:{path}" + (f"?{'&'.join(f'{k}={v}' for k, v in params)}&q=($input)!{q}" if params else f"($input)!{q}")`
- variant form, applied per flag:
  - `weight_int`: write `:0:` for `:0.0:`.
  - `sugar` and no params: write `{path}?q=($input)!{q}` for `{path}($input)!{q}`.
  - `trailing_params` and params: write `{path}($input)!{q};k1=v1;k2=v2` for `{path}?k1=v1&k2=v2&q=($input)!{q}`.
- join members with `", "` (canonical) or the drawn separator (variant); wrap as
  `f"({joined})!'$model_{final}'"`.

All four rewrites are checked equivalent under `render(build())` on 2026-09-29 (spec §3.1.1.1
and §8.1.2 pairs, `packages/url4/tests/spec/test_canonical_form.py:10-17`).

Property:

1. Assert `render(build(canonical_text)) == canonical_text` inside the property. Do not use
   `assume()` for it: a failure here is a strategy defect, and it must be loud. Also add one
   plain test `test_strategy_canonical_form_is_canonical` with a fixed 2-member example with
   params, so the spelling helper is proven without Hypothesis.
2. Link both spellings with `link()` (T2 shared data).
3. Call with the production set `exclude_bindings=SF` (the strategy has no `_sf_recipe`, so the
   set has no effect here). Assert
   `system_fingerprint(linked_variant, exclude_bindings=SF) == system_fingerprint(linked_canonical, exclude_bindings=SF) == sha256(canonical_text)`.

- In the same step, add `test_fingerprint_unparseable_embedded_candidate_raises_url4_error`
  to `tests/unit/test_fingerprint.py`: `"(candidate:0.0:'(((')!''"` raises `Url4Error`
  (checked: `build("(((")` raises `ParseError`).
- **RED reason (behavioral, deterministic):** the T2 GREEN code hashes the embedded text as it
  is. The property fails on the first draw where the variant text differs from the canonical text:
  `system_fingerprint(linked_variant)` is `sha256(variant_text)`, not `sha256(canonical_text)`
  (with `derandomize=True` such a draw always occurs within 200 examples; checked with a
  5 000-draw stdlib fuzz of this strategy on 2026-09-29: 0 invalid spellings). The embedded-unparseable test fails
  with `DID NOT RAISE`. `test_strategy_canonical_form_is_canonical` passes at once: it is a
  guard on the test helper, not on the code under test. Write the three results in the ledger.
- **GREEN:** in `canonical_system_url4`, let `system = root if embedded is None else build(embedded)`
  and `return render(system)`. Still no `_without_bindings`. No other change.

### T4 — SR-H3 precondition (H×H): the exclude set (D3)

Tests in `tests/unit/test_fingerprint.py`:

- `test_fingerprint_sr_h3_recipe_name_is_excluded`:
  assert `system_fingerprint(link(A8), exclude_bindings=SF) == system_fingerprint(link(A9), exclude_bindings=SF) == sha256(S8)`,
  and `canonical_system_url4(link(A9), exclude_bindings=SF) == S8`.
  Also assert the default call keeps the blob: `system_fingerprint(link(A8)) == sha256(A8)`
  and `!= system_fingerprint(link(A9))` (the ERD value with an empty set).
- `test_fingerprint_exclude_bindings_applies_to_direct_run` (no candidate binding): input `A9`
  itself → `system_fingerprint(A9, exclude_bindings=SF) == sha256(S8)`. So a direct run of a
  Candidate and a linked run of the same Candidate give one value.
- `test_fingerprint_exclude_bindings_is_root_level_of_the_system_only`: the linked root itself
  has a `_sf_recipe` source and the candidate has none:
  `L = render(expr(src(text(C), name="candidate", weight=0.0), src(text("x"), name="_sf_recipe", weight=0.0), B1, intent=text("")))`
  → `system_fingerprint(L, exclude_bindings=SF) == sha256(C)` (the linked root is not the
  system; the candidate is). And a Candidate whose `_sf_recipe` is nested one level down stays
  as it is: `N = "(model_1:0.0:(inner:0.0:/p($input)!'a', " + recipe("model", "false") + ")!'$inner')!'$model_1'"`
  (`N` and `L` are canonical; checked on 2026-09-29) →
  `system_fingerprint(link(N), exclude_bindings=SF) == sha256(N)`.
- `test_fingerprint_exclude_every_source_renders_an_empty_group`: input
  `"(_sf_recipe:0.0:'x')!'y'"` with `exclude_bindings=SF` → `canonical_system_url4(...) == "()!'y'"`
  and the fingerprint is `sha256("()!'y'")` (checked on 2026-09-29: `render` accepts it and
  does not raise).
- **RED reason:** on the T3 GREEN code `exclude_bindings` is ignored. The SR-H3 twin test fails
  on its first assert: `link(A8)` and `link(A9)` give `sha256(A8)` and `sha256(A9)`, not
  `sha256(S8)`. The direct-run and empty-group tests fail on the value too. The nested and
  linked-root cases pass (nothing is removed there yet); they are guards against a walk that
  goes too far. The 10 `c08-*`/`c09-*` parity cases of T2c are still RED. Write the results in
  the ledger.
- **GREEN:** add `_without_bindings` exactly as in §4.1, and change the last line of
  `canonical_system_url4` to `return render(_without_bindings(system, exclude_bindings))`.
  This is the final §4.1 body. All tests, including the 50 parity cases, are green.

### T5 — the 50 vectors (data; run it before T2c)

Run this one time from `packages/url4` (`uv run python -c` or a scratch file outside the repo;
do not commit the script). It computes the oracle with `hashlib` only, not with the new module.
The `system` text of `c08` and `c09` is a hand-written literal (`S8`), not a computed strip:

```python
import hashlib, json
from url4 import build, render, src, text, expr

def R(name, named):
    return ("_sf_recipe:0.0:'{\"recipe\":{\"binding\":\"model_1\",\"kind\":\"model\",\"name\":\""
            + name + "\",\"named\":" + named + ",\"role\":\"model\"},\"schema\":\"screamingface.recipe.v1\"}'")
S8 = "(model_1:0.0:/openrouter/model($input)!'Answer the request.')!'$model_1'"
CANDS = [  # (embedded candidate, system text after the exclude; None = the same text)
 ("(model_1:0.0:/openrouter/model($input)!'Be brief')!'$model_1'", None),
 ("(model_1:0.0:/openrouter/model?temperature=0.2&q=($input)!'Be brief')!'$model_1'", None),
 ("(model_1:0.0:/provider/a($input)!'Answer.', model_2:0.0:/provider/b($input)!'Answer.')!'$model_2'", None),
 ("(model_1:0.0:/provider/a($input)!'Answer.', model_2:0.0:/provider/b($input)!'Answer.', synthesis_1:0.0:/provider/synth({input: '$input', outputs: {member_1: '$model_1', member_2: '$model_2'}})!'Synthesize.')!'$synthesis_1'", None),
 ("(model_1:0.0:/openai/gpt-5($input)!'It\\'s a test')!'$model_1'", None),
 ("(model_1:0.0:/openai/gpt-5?max_tokens=64&top_p=0.9&q=($input)!'Short answer')!'$model_1'", None),
 ("(model_1:0.0:/anthropic/claude-opus($input)!'Think step by step.')!'$model_1'", None),
 ("(model_1:0.0:/openrouter/model($input)!'Answer the request.', " + R("model", "false") + ")!'$model_1'", S8),
 ("(model_1:0.0:/openrouter/model($input)!'Answer the request.', " + R("kevins-best", "true") + ")!'$model_1'", S8),
 ("(model_1:0.0:/provider/a($input)!'x', model_2:0.0:/provider/a($input)!'y', model_3:0.0:/provider/c($input)!'z')!'$model_3'", None),
]
def cand(c): return src(text(c), name="candidate", weight=0.0)
BENCH = [
 lambda c: expr(cand(c), build("(answer:0.0:/candidate(question)!'$candidate')!'$answer'"), intent=text("")),
 lambda c: expr(cand(c), build("(answer:0.0:($candidate)!'go')!'$answer'"), intent=text("")),
 lambda c: expr(cand(c), src("/benchmarks/draco/revision-1/cases", name="rows", weight=0.0), intent=text("$rows")),
 lambda c: expr(cand(c), src("/benchmarks/gsm8k/revision-3/cases", name="rows", weight=0.0), intent=text("$rows")),
 lambda c: expr(cand(c), build("(answer:0.0:/candidate(question)!'$candidate', grade:0.0:/judge($answer)!'Grade it')!'$grade'"), intent=text("")),
]
vectors = []
for i, (c, stripped) in enumerate(CANDS, 1):
    assert render(build(c)) == c
    system = stripped if stripped is not None else c
    assert render(build(system)) == system
    for j, b in enumerate(BENCH, 1):
        linked = render(b(c)); assert render(build(linked)) == linked
        vectors.append({"id": f"c{i:02d}-b{j}", "linked_url4": linked, "candidate_url4": system,
                        "fingerprint": hashlib.sha256(system.encode("utf-8")).hexdigest()})
obj = {"schema": "url4.fingerprint.vectors.v1", "binding": "candidate",
       "exclude_bindings": ["_sf_recipe"], "vectors": sorted(vectors, key=lambda v: v["id"])}
```

Then write the §4.3 file from `obj`. Checked on 2026-09-29: all 50 inputs are valid and
canonical, the 50 `linked_url4` values are unique, and there are 9 unique fingerprints (`c08`
and `c09` share one). Read the file by eye before the commit. Put the command in the ledger.

### T6 — SR-3 (M×M) `tests/unit/test_fingerprint.py::test_fingerprint_strips_answer_seed`

Fact (checked): the answer seed is not in the url4 text. The SDK sends it as the
`X-Answer-Seed` header (`packages/screamingface/src/screamingface/_engine/transport.py:1197-1206`),
the compiled Candidate carries it as a separate attribute and copies `url4` unchanged
(`packages/screamingface/src/screamingface/_evaluation/model.py:171-185`),
the report keeps it in its own field (`packages/screamingface/src/screamingface/_evaluation/results.py:137-140`),
and the engine stamps it on each model call at egress only
(`apps/screamingface-engine/src/screamingface_engine/world/request_parameters.py:81-102`). The
submitted `url4_expression` is the linked url4 (`packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:454`,
`packages/screamingface/src/screamingface/_evaluation/compilation.py:33-43`), which is the same text
for every seed. So "strip the seed" means: the fingerprint has no seed input. A seed that the
Candidate declares is a different thing: it is in the text and stays in the hash (D3; T2b
`test_fingerprint_keeps_a_candidate_declared_seed`).

Test:

- Assert `list(inspect.signature(system_fingerprint).parameters) == ["linked", "binding", "exclude_bindings"]`
  and the same for `canonical_system_url4`. Assert that `exclude_bindings` has
  `kind == inspect.Parameter.KEYWORD_ONLY` and default `frozenset()`.
- Assert `system_fingerprint(linked_1, exclude_bindings=SF)` (T2 input, the text the SDK submits
  for `answer_seed=1` and for `answer_seed=2`) `== sha256(C)`.
- Docstring: cite the file:line facts above.
- **RED reason:** none possible; this is a guard test (like a CHAR test). T2 is green when
  T6 starts, and the spec has no seed in the url4 text to strip (spec gap G4). Record in the
  ledger: "SR-3 is a guard: the signature assert fails the moment a seed parameter is added".
  Do not invent a seed-strip behavior to make a RED.

### T7 — C11 purity `tests/unit/test_fingerprint_purity.py` (D7 X-18: unit tests enforce C11)

- `test_fingerprint_module_imports_only_core_and_stdlib`: AST-walk `src/url4/fingerprint.py`
  (all `ast.Import` and `ast.ImportFrom`, level 0). Allowed set:
  `{"__future__", "dataclasses", "hashlib", "url4.core.nodes", "url4.core.parser", "url4.core.render"}`.
  Assert the found set is a subset. Put the scan in a helper `_imports_of(source: str) -> set[str]`.
- `test_the_import_scan_sees_a_forbidden_import`: `_imports_of("import screamingface\nfrom scoreboard.x import y\n")`
  returns both names (teeth check, like `test_import_isolation.py:64-67`).
- `test_importing_url4_fingerprint_loads_no_sdk_engine_or_scoreboard`: subprocess probe (copy the
  `_loaded_after_import` shape of `test_import_isolation.py:31-47`, with its `# noqa: S603` comment) for `url4.fingerprint` with
  watch `("screamingface", "screamingface_engine", "scoreboard", "httpx")` → empty set. (Checked:
  a clean `import url4` loads no `httpx`.)
- `test_fingerprint_module_has_no_io_calls`: AST-walk the module (not a text search: the
  module docstring says "no randomness" and "no clock", so a substring check for `random` or
  `time` would fail on correct code). Assert that no `ast.Call` has a `func` that is an
  `ast.Name` with `id` in `{"open", "print", "input", "exec", "eval", "compile", "__import__"}`.
  The import-set test above already bans `os`, `sys`, `time`, `random`, `socket`, `logging`.
  Put the scan in a helper `_bare_calls_of(source: str) -> set[str]`, and add the teeth check
  `test_the_call_scan_sees_open`: `_bare_calls_of("open('x')\n") == {"open"}`.
- `test_fingerprint_module_names_no_sdk_binding`: parse the module with `ast` and assert that no
  `ast.Constant` string value is `"_sf_recipe"` (the caller owns that name; D3). The docstring
  is an `ast.Constant` too, so the docstring must not contain the exact string `_sf_recipe`
  as its whole value; compare equality, not a substring.
- **RED reason:** these are guards (like CHAR tests: they pass on correct code by design). The
  teeth checks are the proof that the scans work. Record this in the ledger.

### T8 — docs, gates, commit on `unit/URL4-fp`

1. `ARCHITECTURE.md` and `README.md` edits of §3.
2. Gates (§8). All green.
3. Commits on `unit/URL4-fp` (conventional, no `Co-Authored-By`):
   - `docs(url4): start the E14 system fingerprint ledger` (the ledger start);
   - `build(url4): add hypothesis to the dev group` (pyproject, both locks);
   - `feat(url4): add the pure system_fingerprint for the E14 system registry` (module, tests,
     vectors, docs).
4. Fill the ledger outcome. Do not open a PR. Do not file a Linear issue. Do not push to or
   merge into `e14-reproducible-submission-spec`: the integrator does that after wave 1 (D1).

## 7. Edge cases and what not to do

Edge cases (each has a test in §6):

- No `candidate` binding (a direct run) → the hash of the whole canonical url4, after the exclude
  (SR-E5; D3, OD-5 confirmed).
- The binding value is not text (for example a URL or an expression) → treated as "no binding"
  → the whole canonical url4. This is the SDK rule (`url4.py:207-214`).
- The root is an `Iteration` (`src*(body)!intent`), not an `Expression` → "no binding" → the
  whole canonical url4. The exclude does nothing on a non-`Expression` system.
- A url4 with no intent (for example the bare text `/openrouter/model`) → `render` raises
  `RenderError` → it propagates (the same path as `""`).
- Two `candidate` bindings → the first one wins (the SDK rule).
- Invalid linked url4 or invalid embedded candidate → `url4.Url4Error` propagates.
- Equivalent spellings: `:0:` and `:0.0:`; `(ctx)` and `?q=(ctx)`; `;k=v` and `?k=v&q=`; the
  separator after `,` → one fingerprint (SR-2).
- A quote `'` in a prompt → escaped by `render`; the fingerprint is stable (SR-2 alphabet).
- The recipe display name is inside the candidate text (`_sf_recipe` JSON). With the production
  set `exclude_bindings={"_sf_recipe"}`, two names of one system give one fingerprint (SR-H3; D3).
  With the default empty set the blob stays in the hash (the ERD value).
- The exclude is root-level on the system only: a `_sf_recipe` on the linked root or nested
  inside the Candidate is not removed.
- Every root source excluded → `()!intent` renders and is hashed; no error.
- A seed that the Candidate declares (`?seed=7`) stays in the hash; two seeds give two
  fingerprints (D3, OD-2 default). The answer seed is not in the text (SR-3).

What not to do:

- Do not import `screamingface`, `screamingface_engine` or `scoreboard` anywhere in `packages/url4`.
  Never import across apps (C11).
- Do not import `url4.dag`, `url4.io`, `url4.peer`, `url4.wire`, `url4.cli`, `url4.observe` or
  `url4.streaming` from `fingerprint.py`. Only `url4.core`, `dataclasses` and `hashlib`.
- No I/O, no logging, no metrics, no env vars, no caching (`functools.cache` is state; the
  caller can cache).
- Do not take a fingerprint argument from the caller. The scoreboard always recomputes (SR-D1).
- Do not add `_sf_recipe` or any other SDK name to `packages/url4/src`. Do not give
  `exclude_bindings` a non-empty default. The test data may name it (it is the caller's value).
- Do not strip a `seed` parameter or any query parameter.
- Do not change a prior test, `__init__.py`, `test_layering.py`, or the module-size baseline.
- Do not upgrade other packages when you refresh a lock (`uv lock`, never `uv lock --upgrade`).
- This unit has no credentials. AIGateway credentials live only in `credential_blobs`; never use
  the OS keychain; never store or log `AIGATEWAY_SECRET_KEY`. None of these is in scope here.
- Do not edit in the shared checkout. Do not commit to `main` or to
  `e14-reproducible-submission-spec`. Commit only on `unit/URL4-fp`.

## 8. Verification

Run from the `unit/URL4-fp` worktree root:

```bash
uv run .claude/scripts/run_gates.py url4 --base e14-reproducible-submission-spec
(cd packages/url4 && uv lock --check \
  && uv run ruff check && uv run ruff format --check && uv run pyright \
  && uv run pytest --cov=url4 --cov-fail-under=95 -q \
  && uv run pytest -q tests/unit/test_fingerprint.py tests/unit/test_fingerprint_properties.py \
       tests/unit/test_fingerprint_parity.py tests/unit/test_fingerprint_purity.py \
  && uv run python scripts/check_suppressions.py \
  && uv run python scripts/check_module_size.py)
(cd apps/screamingface-engine && uv lock --check)
uv run .claude/scripts/run_gates.py screamingface-engine --base e14-reproducible-submission-spec
uv run .claude/scripts/run_gates.py screamingface --base e14-reproducible-submission-spec
```

The last two lanes run because their CI triggers on `packages/url4/**`
(`.github/workflows/screamingface-engine-tests.yml:7,15`, `.github/workflows/screamingface-tests.yml:8,17`).
No change in them is expected; if one fails, stop and classify the failure (test-plan §1 rule 7).

**Done means:**

- SR-2, SR-3, SR-4, SR-5, the SR-H3 exclude tests and the C11 purity tests are green, with the
  RED evidence (or the guard note) in the ledger for each.
- `fingerprint_vectors.json` has 50 entries with `exclude_bindings == ["_sf_recipe"]`, and its
  oracle and twin guards are green.
- All gates above are green. Coverage of `url4` stays ≥ 95 %. `fingerprint.py` has 100 % line
  coverage.
- `git diff e14-reproducible-submission-spec --stat` shows only the files in §3 and the ledger,
  and `git status --porcelain` lists no `packages/url4/.hypothesis/` path (it is not gitignored;
  if it appears, delete it, do not commit it, and note it in the ledger).
- The work is committed on `unit/URL4-fp`. The integrator merges it after wave 1 (D1).

## 9. Open decisions

None open. Decided:

- **OD-1 — Decided: D3.** Option A. The caller passes `exclude_bindings=frozenset({"_sf_recipe"})`.
  It is now the base design of §4.1, §4.2, §4.3 and T4.
- **OD-2 — Decided: D3.** A seed that the Candidate declares stays in the hash (T2b).
- **OD-3 — Decided: D7 X-18.** The T7 unit tests enforce C11 row 1. This unit does not edit
  `.claude/scripts/check_layering.py`.
- **OD-4 — Decided: D7 X-25.** Hypothesis stays. The one-line `apps/screamingface-engine/uv.lock`
  change rides with this unit (T0). There is no Linear sub-issue (D1).
- **OD-5 — Decided: D3.** No candidate binding hashes the whole canonical url4 (after the exclude).
