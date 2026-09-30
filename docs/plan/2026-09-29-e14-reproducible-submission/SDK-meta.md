# Plan — SDK-meta: edit submission metadata from the SDK (E14a, OME-1307)

Status: draft for approval. Spec: `docs/spec/2026-09-29-e14-reproducible-submission/`
(`prd/edit-metadata.md` §3.1 MD-H1, MD-H6, §7 MD-19; `contracts.md` C5, C4 `paper_url`).
Language: ASD-STE100. Stack: `screamingface` (`packages/screamingface`). Skill: `sdlc-python`.
Wave: 2. Size: 1–1.5 d.

Delivery (D1): this unit lands on the one branch `e14-reproducible-submission-spec`. There is
no unit PR, no Linear sub-issue and no unit CI merge gate. Build it in a temporary worktree on
the branch `unit/SDK-meta`, made from the e14 branch HEAD
(`git checkout -B unit/SDK-meta e14-reproducible-submission-spec`). After wave 2, the integrator
merges `unit/SDK-meta` into the e14 branch and runs the gates. Plan: this file
(`docs/plan/2026-09-29-e14-reproducible-submission/SDK-meta.md`). Ledger:
`docs/work/2026-09-29-e14-sdk-meta.md` (start it before RED).

## 1. Scope

### 1.1 Test ids this unit owns

| Id | PRD name | What this unit proves |
|---|---|---|
| MD-19 | `sdk_update_submission_sends_if_match_and_parses` | `update_submission` (sync and async) sends `PATCH /v1/scores/{id}` with `If-Match: "<n>"` and only the given fields, and decodes the updated `LeaderboardScore` (`paper_url`, `metadata_revision`). Also the SDK half of MD-H1: `submit(..., paper_url=...)` sends the field. |

MD-19 is one PRD row. This plan splits it into the sub-tests in §6. Each sub-test name starts
with `test_md19_`.

### 1.2 Out of scope

- MD-1 to MD-18, MD-20, MD-21 (scoreboard, portal and E2E). They belong to SB-meta and E2E.
- An SDK method for `GET /v1/scores/{id}/metadata-history`. The PRD names no SDK method for it.
- Client-side validation of the `paper_url` rules (MD-E5). The scoreboard is the one validator.
  The SDK checks only the type (`str` or `None`).
- `revision_of`, `cache_version_receipt`, the `reported_result` block and `notices` (SDK-submit).
- `replay` (SDK-replay).

## 2. Depends on

- Code dependencies: none (the SDK tests use `httpx.MockTransport` fakes, D7 X-20).
- Wave (D2): 2, with SB-meta, SB-registry, GW-freeze and ENG-freeze.
- Board compatibility (not a build block): the scoreboard `ScoreSubmission` is `extra="forbid"`
  (`apps/scoreboard/src/scoreboard/scores/schemas.py:369`). A board without SB-meta gives `422`
  for `paper_url`, and `405` for `PATCH`. The SDK sends `paper_url` only when the caller gives
  it, so a normal submit does not change. With D1, SB-meta and this unit land on the same
  branch, so they ship together. Deploy the board before, or with, the SDK.
- Contracts: implements the client side of **C5** (`PATCH /v1/scores/{score_id}`) and the
  `paper_url` field of **C4**. Consumes nothing else. The coded error body is
  `{"detail": {"code", "message", ...}}` (D7 X-8).

### 2.1 Integration notes

- Same-wave shared files: none. SB-meta, SB-registry, GW-freeze and ENG-freeze change no file
  under `packages/screamingface/`.
- Later-wave files that build on this unit: SDK-submit (wave 3) appends to the same
  `LeaderboardScore`, `_scoreboard/leaderboards.py`, `client.py`, `leaderboards.py`,
  `CHANGELOG.md`, `README.md` and `public_surface_snapshot.json`. It starts from the e14 HEAD
  after this unit is merged, so there is no conflict. Keep the new `LeaderboardScore` fields
  last in the class, and keep the `CHANGELOG.md` entry as one bullet, so the SDK-submit append
  is additive.

## 3. Files

| Path | Change | Exemplar to imitate |
|---|---|---|
| `packages/screamingface/src/screamingface/leaderboard.py` | change: two new optional fields on `LeaderboardScore` | `ranking_notice` field and its `__post_init__` check, `leaderboard.py:142-143` and `:196-200` |
| `packages/screamingface/src/screamingface/_scoreboard/leaderboards.py` | change: `update_submission` (sync + async), `paper_url` on `submit`, decode of the two fields, coded errors, one transport retry, per-call timeout | `submit` / `get_score` twins, `_scoreboard/leaderboards.py:90-126` and `:166-202`; `_submission_authors` `:523-538`; `_response_json` `:259-294` |
| `packages/screamingface/src/screamingface/client.py` | change: `_scoreboard_request` gets an optional `timeout` keyword (both twins) | `Client._scoreboard_request`, `client.py:354-372`; `AsyncClient._scoreboard_request`, `client.py:677-695` |
| `packages/screamingface/src/screamingface/leaderboards.py` | change: facade `update_submission`, and `paper_url` on `submit` | `submit` facade, `leaderboards.py:25-32` |
| `packages/screamingface/tests/test_leaderboard_metadata_edit.py` | create | `_sync_client` / `_async_client` with `httpx.MockTransport`, `tests/test_leaderboards.py:180-192`; score JSON builder `tests/test_leaderboards.py:92` (`_score_response`) |
| `packages/screamingface/tests/public_surface_snapshot.json` | regenerate (not hand-edited) | `UPDATE_SURFACE_SNAPSHOT=1 uv run pytest tests/test_public_surface.py` (`tests/test_public_surface.py:31`) |
| `packages/screamingface/CHANGELOG.md` | change: one entry under `## Unreleased` / `### Features` | the existing entries there |
| `packages/screamingface/README.md` | change: one short "Edit a submission" example in the Leaderboards section | the existing `submit` example |

Do not copy test helpers from `tests/test_leaderboards.py` by import. Copy the small builders
into the new file (test files do not import each other in this package).

## 4. Signatures and data shapes

### 4.1 `LeaderboardScore` (public, `leaderboard.py`)

Append two fields **after** `ranking_notice`, so the positional order of the old fields does
not change:

```python
paper_url: str | None = None
# None means the Scoreboard did not send it (a board before E14a).
metadata_revision: int | None = None
```

`__post_init__`: `paper_url` goes through `_optional_text` (the same as `scoreboard_url`).
`metadata_revision`: when not `None`, it must pass `_positive_int` (the same rule as `version`).

### 4.2 Sentinel for "not given"

In `_scoreboard/leaderboards.py`:

```python
class _Unset(enum.Enum):
    UNSET = "UNSET"

UNSET: Final = _Unset.UNSET
```

Narrow with `value is _Unset.UNSET` (not `== UNSET`), so pyright removes `_Unset` from the
type on the other branch.

WHY an enum: `None` is a real value in C5 (it clears the field, MD-E7), so "not given" needs a
second value. An enum member has a stable `repr`, so the public surface snapshot stays stable.
Export nothing new from `screamingface` for it.

### 4.3 `update_submission` (sync; the async twin is the same with `async def` and `await`)

```python
def update_submission(
    self,
    score_id: UUID | str,
    *,
    expected_revision: int,
    authors: Sequence[str] | None | _Unset = UNSET,
    paper_url: str | None | _Unset = UNSET,
) -> LeaderboardScore:
```

Steps, in this order. Every check before step 5 sends no request.

1. `selected = _score_id(score_id)` (existing, `:727-735`).
2. `revision = _expected_revision(expected_revision)`: `bool` or not `int` → `TypeError("expected_revision must be an integer")`; `< 1` → `ValueError("expected_revision must be positive")`.
3. `body = _metadata_patch(authors, paper_url)`:
   - Both `UNSET` → `ValueError("update_submission needs authors or paper_url")`.
   - `authors` is `UNSET` → no `"authors"` key. `None` → `"authors": None`. A sequence →
     `selected = _submission_authors(authors)` (the submit validator, `:523-538`, so the
     messages are the same as on submit), then `"authors": list(selected)`. `selected` is never
     `None` here (the input is not `None`); write `assert selected is not None` before the
     `list(...)` so pyright accepts it.
   - `paper_url` is `UNSET` → no key. `None` → `"paper_url": None`. A `str` → the stripped
     text; blank → `ValueError("paper_url must be non-blank text or None")`. Any other type →
     `TypeError("paper_url must be a string or None")`.
4. `headers = {"If-Match": f'"{revision}"'}` (a quoted entity tag, as C5 shows).
5. Send `PATCH f"{_SCORES_PATH}/{selected}"` with `json=body`, `headers=headers`,
   `replay_safe=True`, `timeout=15.0`, `operation="edit the submission metadata on"`,
   `missing=("unknown_score", f"Score {str(selected)!r} was not found")`,
   and **one** re-send after an `httpx.TransportError` (C5: "One retry on a connection error").
   The re-send uses the same body and the same `If-Match`. It is safe by MD-D4.
6. Decode with `_decode_score(payload, scoreboard_url=self._scoreboard_url)`.

Decode the two new fields in `_decode_score` (`_scoreboard/leaderboards.py:351-399`), next to
`authors=`:
`paper_url=_optional_text(root.get("paper_url"), "Leaderboard score paper_url")` and
`metadata_revision=_optional_integer(root.get("metadata_revision"), "Leaderboard score metadata_revision")`
(`:672-686`; `_optional_integer` refuses a `bool`). A `0` then fails `_positive_int` in
`LeaderboardScore.__post_init__`, and the existing `except (TypeError, ValueError)` turns it into
`invalid_leaderboard`.

The ETag header is not read. The body `metadata_revision` is the source of truth (C5 returns
the new `ScoreSchema`, which holds it).

### 4.4 `submit` gets `paper_url`

```python
def submit(self, candidate_result, *, authors=None, paper_url: str | None = None) -> LeaderboardScore
```

`_submission(candidate_result, authors=authors, paper_url=paper_url)`: when `paper_url` is not
`None`, validate it with the same text rule as §4.3 step 3 and set `payload["paper_url"]`.
When it is `None`, send **no** key (the same rule as `authors`, `leaderboards.py:477-480`, so a
board before E14a still accepts a normal submit).

### 4.5 Transport helpers

- `_sync_json` / `_async_json` get two keyword arguments: `timeout: float | None = None` (passed
  on to the request callable only when not `None`) and `transport_retries: int = 0`. On
  `httpx.TransportError`, when retries remain, send again at once (no sleep: C5 names no
  backoff). When no retries remain, call `_unreachable` as today.
- `Client._scoreboard_request(..., timeout: float | None = None)` passes
  `**({"timeout": timeout} if timeout is not None else {})` to `httpx.Client.request`. Same in
  `AsyncClient`. The default call shape does not change.

### 4.6 Coded errors

C5 names codes. The body shape is `{"detail": {"code": "<code>", "message": "...", ...}}`
(Decided: D7 X-8). The SDK reads the code in this order:

1. `detail` is a mapping with a non-blank `code` string → use that code.
2. Else, for `operation == "edit the submission metadata on"`, map the status:
   `401 → identity_not_verified`, `403 → not_submission_owner`, `404 → unknown_score` (the
   existing `missing` branch), `412 → metadata_revision_conflict`,
   `422 → invalid_submission_metadata`, `428 → precondition_required`, other → the existing
   `scoreboard_contract_error`. WHY a fallback when X-8 fixes the shape: a proxy or an old
   board can send a status with no coded body. The SDK must still give a typed code.

Do not change `_error_details` (`_scoreboard/leaderboards.py:297-304`). So `exc.details` is
the `detail` string when `detail` is a string, and else the **whole** decoded JSON body (for a
`412` it then holds `{"detail": {..., current revision and values, MD-E3}}`). Tests read
`exc.details["detail"]`. `permanent` keeps today's rule (`status < 500` and not `429`).
Put the table in a module constant `_METADATA_EDIT_CODES`. Change `_status_code` to take the
table by operation. Do not change the codes of the existing operations.

### 4.7 Facade (`leaderboards.py`)

```python
def update_submission(score_id, *, expected_revision, authors=UNSET, paper_url=UNSET) -> LeaderboardScore:
    """Edit the authors or the paper URL of one submission you own."""
    return default_client().leaderboards.update_submission(
        score_id, expected_revision=expected_revision, authors=authors, paper_url=paper_url)
```

Add `"update_submission"` to `__all__`. Import `UNSET` from `screamingface._scoreboard.leaderboards`.

### 4.8 Ports and adapters

The SDK has no core port for the Scoreboard. `Leaderboards` is the adapter at the Scoreboard
HTTP seam (`_scoreboard/leaderboards.py:1`), and it gets its HTTP callable by injection
(`client.py:99-102`). Keep that shape. Do not add a new port.

### 4.9 Ed25519 JWS

Not used in this unit.

## 5. Migrations

None. The SDK has no database.

## 6. TDD order (RED first, risk order)

Step 0 (before RED): add the stub `update_submission` (sync + async) that sends `PATCH` with an
empty JSON body and no `If-Match`, and returns `_decode_score(...)`. Add the two fields to
`LeaderboardScore` with defaults but do not decode them yet. Then each RED fails on an
assertion, not on an `AttributeError`.

All tests are in `packages/screamingface/tests/test_leaderboard_metadata_edit.py`. Each
transport test has a sync and an async version (`@pytest.mark.asyncio`).

| Order | Test name | RED reason (the assertion that fails before GREEN) |
|---|---|---|
| 1 | `test_md19_update_submission_sends_if_match_and_parses` (+ `_async`) | `request.headers["If-Match"] == '"1"'` fails (stub sends none); body is `{}`, not `{"authors": [...], "paper_url": ...}`; `score.metadata_revision == 2` and `score.paper_url == "https://arxiv.org/abs/2609.01234"` fail (not decoded). |
| 2 | `test_md19_partial_update_sends_only_the_given_field` | with only `paper_url`, `json.loads(body) == {"paper_url": ...}` fails. |
| 3 | `test_md19_none_sends_json_null_to_clear_a_field` (params: `authors=None`, `paper_url=None`) | body is `{}`, not `{"authors": null}` / `{"paper_url": null}`. |
| 4 | `test_md19_no_field_raises_before_any_request` | `pytest.raises(ValueError)` fails and one request is seen. |
| 5 | `test_md19_expected_revision_is_validated_before_any_request` (params: `0`, `-1`, `True`, `"1"`) | no error; a request is seen. |
| 6 | `test_md19_authors_use_the_submit_validator` (11 addresses; a bad email; `[]`) | no `ValueError` with the submit message; a request is seen. |
| 7 | `test_md19_error_codes_are_typed` (params: 401, 403, 404, 412 with a `detail` body, 422, 428; plus one case where `detail.code` wins over the status map) | `exc.code` is `scoreboard_contract_error`, not the C5 code (the RED). Also assert `exc.details == <the whole JSON body>` for the 412 case (this half passes today; it guards §4.6) and `exc.permanent is True` for every row. |
| 8 | `test_md19_connection_error_is_retried_once` | the handler raises `httpx.ConnectError` once then returns 200; today the call raises `scoreboard_unreachable`; assert 2 requests with the same `If-Match` and body. |
| 9 | `test_md19_two_connection_errors_raise_unreachable` | assert exactly 2 requests (stub sends 1), then `exc.code == "scoreboard_unreachable"`. |
| 10 | `test_md19_patch_uses_a_15_second_timeout` | `request.extensions["timeout"]["read"] == 15.0` fails (client default 30). |
| 11 | `test_md19_submit_sends_paper_url_only_when_given` | with `paper_url=...` the POST body has no `paper_url`; with no `paper_url` assert the key is absent (this half passes, it guards the old shape). |
| 12 | `test_md19_score_decode_reads_paper_url_and_revision_and_tolerates_absence` | `get_score` of a body with `paper_url` and `metadata_revision: 3` must give those values, but the stub decode gives `None` / `None`; a body without them must give `None` / `None` (this half passes). A body with `metadata_revision: 0` or `true` must raise `invalid_leaderboard`. |
| 13 | `test_md19_module_facade_passes_through` | monkeypatch `_default_client._client` (pattern `tests/test_leaderboards.py:630-632`); `sf.leaderboards.update_submission` is missing. |

GREEN after each row with the smallest change. REFACTOR on green only.

No CHAR rows are marked for the SDK. The existing `tests/test_leaderboards.py` is the safety
net: `test_client_submits_a_candidate_result_without_repeating_report_fields`
(`tests/test_leaderboards.py:387-425`) compares the whole `LeaderboardScore`. It must stay green
with no edit. The new fields have defaults, and a body without them decodes to the defaults.

## 7. Edge cases, what not to do, gates

Edge cases:
- `authors=None` in `update_submission` means "reset to the submitter" (MD-E7). In `submit`,
  `authors=None` still means "do not send the key" (`leaderboards.py:477-480`). Do not merge the
  two meanings.
- A `412` is permanent for this request. Do not retry it. The caller reads `exc.details` and
  calls again with the new revision.
- A retried `PATCH` whose first try did commit gets `200` (MD-D4), not `412`. The SDK does
  nothing special for it.
- The 15 s timeout is per request, not for the two tries together.

What not to do:
- Do not parse the `ETag` to get the revision.
- Do not add `paper_url` URL rules to the SDK (one validator, at the data owner).
- Do not import anything from `apps/` (the SDK never imports an app).
- Do not log author emails (PII). This unit adds no log lines.
- Do not edit a prior test (the append-only gate). If a prior test must change, stop and ask.
- No OS keychain, no credential storage. This unit touches no credential.

Gates (from the repo root):

```bash
uv run .claude/scripts/run_gates.py screamingface --base e14-reproducible-submission-spec
```

This runs, in `packages/screamingface`: `ruff check`, `ruff format --check`, `pyright`,
`pytest --cov=screamingface --cov-fail-under=95 -q`, the notebook check, `uv build`, and
`scripts/check_distribution.py` (`.claude/sdlc.local.md`, stack `screamingface`). WHY this
`--base`: the unit branch starts at the e14 branch HEAD (D1), so the append-only check must
compare against that HEAD, not against `origin/main`.

## 8. Verification

```bash
cd packages/screamingface
uv run pytest tests/test_leaderboard_metadata_edit.py -q
uv run pytest tests/test_leaderboards.py tests/test_public_surface.py -q
cd ../.. && uv run .claude/scripts/run_gates.py screamingface --base e14-reproducible-submission-spec
```

Done when:
- All `test_md19_*` tests are green, sync and async.
- `tests/test_leaderboards.py` is green with no edit.
- The public surface snapshot is regenerated and shows only: `Leaderboards.update_submission`,
  `AsyncLeaderboards.update_submission`, `submit(..., paper_url)`, the two new
  `LeaderboardScore` fields, and the facade `update_submission`.
- The CHANGELOG has the entry. The gates are green. The ledger outcome is filled.
- Conventional commits (`feat(screamingface): ...`) on `unit/SDK-meta`, no `Co-Authored-By`.
  Do not open a PR. Tell the integrator that the unit branch is ready (D1).

## 9. Open decisions

None open. The earlier items are closed:

- **Coded error body shape.** Decided: D7 (X-8). The scoreboard sends
  `{"detail": {"code": "<code>", "message": "...", ...}}`. §4.6 reads `detail.code` first and
  keeps the status map as the fallback.
- **The name `update_submission` and a required `expected_revision`.** Decided (default): the
  names come from the PRD (MD-H6). `expected_revision` is required, because a `PATCH` without
  `If-Match` always gets `428` (MD-E4).
- **respx.** Decided: D7 (X-20). The tests use `httpx.MockTransport`
  (`tests/test_leaderboards.py:180-192`). This unit adds no dependency.
- **Release order.** Decided: D1. SB-meta and this unit land on one branch and ship together.
