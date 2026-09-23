# OME-1247 — Client-side bounds on the submitted model routes

## §1 Problem

`OME-1180` adds `models` to the submission payload. The Scoreboard bounds that field; the
Client does not. The mismatch surfaces only in the field, after a release, as a 422 on the
entire submission.

## §2 The contract to mirror

Read off `apps/scoreboard/src/scoreboard/scores/schemas.py` on `origin/main`:

| Cap | Value | Board enforcement |
| -- | -- | -- |
| routes per submission | 32 | `len(value) > _MODELS_MAX_ROUTES` in `validate_bounded_models` |
| characters per route | 255 | `ModelRoute = Annotated[str, Field(max_length=255, pattern=...)]` |
| serialized bytes | 4096 | `len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())` |

**§2.1 The byte cap must be measured identically.** `json.dumps` with compact separators and
`ensure_ascii=False`, then `.encode()`. Any other spelling — default separators, ASCII
escaping, or measuring the Python strings rather than the JSON — makes the two ends disagree
about what 4096 bytes means, which is the exact class of bug this unit exists to close.

**§2.2 The route grammar is already mirrored** and is not in scope. `_MODEL_ROUTE_RE`
(`_evaluation/candidate.py:429`) and `_MODEL_ROUTE_PATTERN` (board) describe the same shape.
Only the bounds diverge.

## §3 Where the check belongs

At the **submission boundary**, not at `Pipeline` construction.

The caps are the leaderboard's, not the toolkit's. A researcher composing a 40-model ensemble
locally must not be blocked; only publishing it to a board that will refuse it is blocked.
`_submission()` is where the payload is built and where every other submission-only rule
already lives (`_submission_authors`, `_score_value`).

## §4 Failure mode

Raise `ValueError` before the request leaves, naming the cap and the offending value.

This follows `_submission_authors` exactly — same class of field, same class of cap, same
`ValueError` with the limit interpolated. The alternative, omitting `models` when over-cap,
was rejected on `OME-1247`: it would let the entry be classified from `ran_with_providers`,
which is the `OME-1145` bug this whole chain exists to fix.

**§4.1 The message must name the offending value**, not just the limit. A user who sees "at
most 32 routes" and has no idea they built 41 cannot act on it without reading the board's
source.

## §5 Boundaries are the test surface

An off-by-one here is a field failure after a release, so each cap is pinned on both sides:
32 passes / 33 raises, 255 passes / 256 raises, and a payload whose route count and lengths are
all legal but whose serialization exceeds 4096 bytes still raises.

## §6 Out of scope

- raising the board's cap (rejected on the ticket — it bounds a public unauthenticated write path)
- deduplication, which `_ordered_unique` already guarantees upstream at `candidate.py:294/326/359`
- the route grammar (§2.2)
