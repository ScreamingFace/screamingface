---
title: Send the declared model identities on a leaderboard submission — spec
ticket: OME-1180
status: approved — scope inherited from OME-1179; rule-5 exception approved 2026-09-11
date: 2026-09-11
parent: OME-1179
---

# OME-1180 — send the declared model routes

## 1. Problem

`_submission()` (`_scoreboard/leaderboards.py:443`) sends `_providers(candidate_result.models)`,
and `_providers` (line 502) keeps only the first path segment of each route. The identities the
recipe declares never reach the board.

## 2. Change

One key on the payload:

```python
"models": list(candidate_result.models),
```

`CandidateResult.models` is required, ordered, unique and non-empty, so it is always available
and needs no fallback.

`ran_with_providers` stays exactly as it is. It is required on `ScoreSubmission`, the portal's
Backends column reads it, and `_content_hash` on the Scoreboard hashes the wire value — changing
or removing it would rewrite recipe identity for every existing row.

## 3. Declared, not observed

These are the routes the recipe composes. `_evaluation/results.py:141` builds
`CandidateResult(models=candidate.models)` from the composed candidate, never from the run
outcome, so a fallback model that never fired still appears. That is correct for a statistic
about what a system is *made of*, and it is what `OME-1179`'s contract asks for.

## 4. Rollout — ships SECOND

`ScoreSubmission` is `extra="forbid"`, so a Scoreboard that does not know `models` returns
**422 for every submission**. `OME-1181` must be deployed and confirmed live before this is
released — merging it is not enough.

`packages/screamingface` is on release-please, so merging this branch starts a release PR.
Merging *that* publishes to PyPI. The gate is therefore on the merge of the release PR, not on
the merge of this one.

## 5. Confidence-Gate exception (owner-approved, 2026-09-11)

`test_the_submission_payload_gains_only_the_cost_key` asserts the payload's exact key set. It is
a characterisation guard whose stated purpose is that "an accidental change to a neighbouring
field should fail loudly rather than ship" — this change is deliberate, so the guard is working
as designed and the intended response is to record the new key.

Approved: add the single string `"models"` to the expected set. Nothing removed, nothing
loosened, set stays exhaustive.

**Rejected alternative:** nest `models` inside the free-form `metadata` dict, as
`benchmark_revision` already is (`store.py:110-118`, OME-775 D5). That touches no existing test
and removes the deploy-ordering constraint entirely, since any Scoreboard version ignores
unknown metadata keys. Rejected because it leaves the field untyped and unvalidated on the wire
— the opposite of why a typed field was chosen — and would require reopening `OME-1181` after
its review.

## 6. Acceptance

* `models` carries the declared routes verbatim — a regression to provider prefixes fails
* `models` and `ran_with_providers` describe the same set, so the two cannot drift
* a fusion sends its members **and** its synthesizer
* the payload survives `json.dumps`
* `ran_with_providers` is unchanged
* the CHANGELOG records the payload addition
* full `screamingface` gates green, including coverage at **95%**

## 7. Not in scope

Observed models; the Backends column; anything on the Scoreboard side.
