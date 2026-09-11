---
title: Accept and store model identities — plan
ticket: OME-1181
spec: docs/spec/2026-09-11-OME-1181-model-identities.md
status: approved
date: 2026-09-11
---

# OME-1181 — implementation plan

Five phases, each RED → GREEN → gates → commit. Ordered so the pure, DB-free work lands first
and the schema change lands as late as it can while still preceding its consumers.

Tests are **append-only**. Nothing under `tests/` is edited or deleted; every phase adds.

---

## Phase 1 — `classify_model()` (pure, no DB, no migration)

`apps/scoreboard/src/scoreboard/classification/openness.py`

Add, without touching `classify_providers` / `classify_score` / `classify_baseline`:

```python
_ROUTING_PREFIXES: tuple[str, ...] = ("openrouter",)
_OPEN_MODEL_MARKERS: tuple[str, ...]   # gpt-oss, gemma, moonshotai, kimi
def _strip_routing_prefix(route: str) -> str
def classify_model(route: str) -> Literal["open", "closed", "unknown"]
```

Order of resolution inside `classify_model`, and it matters:

1. strip a leading routing prefix
2. **specific open-model markers first** — `gpt-oss`, `gemma`, `moonshotai`, `kimi`
3. then the existing `_OPEN_PROVIDER_MARKERS`
4. then `_CLOSED_PROVIDER_MARKERS`
5. otherwise `unknown`, logged via the existing `_log_unrecognized`

Step 2 before 4 is the whole point: `openai/gpt-oss-120b` must not be caught by `openai`.

**RED:** `tests/unit/classification/test_classify_model.py`

- `openrouter/openai/gpt-oss-120b` → open (fails without the carve-out AND without the strip)
- `openrouter/google/gemma-2-27b-it` → open
- `openrouter/moonshotai/kimi-k2.6` → open
- `openrouter/openai/gpt-5.5` → closed — the carve-out must not swallow the owner rule
- `openrouter/google/gemini-3-pro` → closed
- `openrouter/mistralai/mistral-large-2411` → open (Q1: downloadable)
- `anthropic/claude-opus-4.8` → closed with no prefix to strip
- `acme/never-heard-of-it` → unknown, and `unknown != "closed"`
- parametrised: every route classifies identically with and without `openrouter/`
- **guard:** `classify_providers(["openrouter"])` still returns `closed` — the existing
  row-level surfaces are untouched

## Phase 2 — wire, bounds, column, migration

`schemas.py`:

```python
_MODELS_MAX_ROUTES = 32
_MODELS_MAX_BYTES = 4096
ModelRoute = Annotated[str, Field(max_length=255, pattern=_MODEL_ROUTE_PATTERN)]
```

`_MODEL_ROUTE_PATTERN` mirrors the Client's `_MODEL_ROUTE_RE`
(`_evaluation/candidate.py:429`), anchored.

- `ScoreSubmission.models: Annotated[list[ModelRoute], Field(min_length=1)] | None = None`
- `@field_validator("models")` → route count and serialized-size caps, same shape as
  `validate_distinct_authors`
- `ScoreSchema.models: list[str] | None = None`
- **`LeaderboardEntry` is NOT touched** (spec §3, Q2 option A)

`models/score.py`: `models = fields.JSONField(null=True)` with a FEATURE anchor.

`migrations/0013_score_models.py`: `ops.AddField`, depending on `0012_score_authors`.

`store.py`: `_submission_to_kwargs` carries `models`; `_score_to_schema` projects it.

**RED:** additive cases in `tests/unit/scores/test_schemas.py` and a new
`tests/unit/scores/test_model_identities.py`

- a valid `models` round-trips through submit → store → `ScoreSchema`
- absent `models` still succeeds and stores `null`
- `models: []` is rejected
- 33 routes rejected; 32 accepted
- a 256-char route rejected
- a payload over 4096 serialized bytes rejected with a field error
- a malformed route (spaces, empty segment) rejected
- **guard:** `_content_hash` is byte-identical with and without `models`, so a resubmission
  carrying it dedups to the same row rather than creating a second

## Phase 3 — derive `ran_with_providers`

`store.py`: when `submission.models` is present, `_submission_to_kwargs` stores providers
derived from the routes rather than the client's copy.

**INVARIANT to encode as a comment and a test:** `_content_hash` keeps reading
`submission.ran_with_providers`, the wire value. Deriving into the hash would change every
existing recipe's identity and split dedup history.

**RED:**

- routes present → stored providers derived from them
- routes absent → the client's `ran_with_providers` stored unchanged
- a client sending *inconsistent* providers and models → storage reflects the models, the
  content hash reflects the wire value

## Phase 4 — republish enrichment

`store.py` `_confirm_replayable` (~L835-849): add `models` to the `updates` allowlist inside
the existing `same_candidate_owner` branch. No new guard, no new lock.

**RED:**

- same submitter republishes with `models` → the existing row gains them, no new row
- a **different** submitter republishing cannot set them — the anti-hijack guard holds
- a republish omitting `models` does not erase existing ones (None means "not specified")
- a row that already has `models` is not overwritten by a worse value

## Phase 5 — chunked frontier-scoped read

`store.py`: `models_for_score_ids(ids) -> dict[str, list[str] | None]`, selecting `id, models`
only, issued in chunks.

**RED:**

- returns the right mapping for a small set
- exercised above one chunk boundary, asserting more than one query was issued
- **guard:** it selects only `id, models` — a widened projection fails

---

## Gates, every phase

```
uv run .claude/scripts/run_gates.py scoreboard --base origin/main
```

Append-only, ruff check, ruff format, pyright, pytest with `--cov-fail-under=80`, and all
three portal suites. No `--skip-append-only` should be needed — this unit adds tests only.

## Companion skills

`tortoise-dev` is mandatory and applies to phase 2: model-per-file is already the layout, the
abstract `BaseScore` already exists, `class Meta` stays first, and the migration uses the
built-in Tortoise CLI — never Aerich.

## Stop conditions

Return to the owner rather than working around, if:

- the migration cannot depend cleanly on `0012_score_authors` (a second head appeared on main)
- deriving providers turns out to change `_content_hash` for any existing row
- phase 4 cannot reuse the existing guard and would need a new write path
- any existing test has to change
