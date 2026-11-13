# Errors

Source: https://docs.screamingface.ai/sf-client/api/errors

What the Client raises, and the warnings it emits when a run or a submission carries a caveat.

Errors the Client raises about the engine, a provider, a leaderboard or an evaluation inherit from `ScreamingFaceError`. Nine subclasses say where the failure happened, and each carries a machine-readable code alongside its message. Argument validation raises `ValueError`, `TypeError` or `KeyError` instead (for example `limit=0` raises `ValueError`), and a closed Client raises `RuntimeError`. Catch `ScreamingFaceError` for runtime failures and let validation errors surface.

```python
import screamingface as sf

try:
    report = sf.evaluate(recipe, benchmark="medxpert", limit=1)
except sf.ScreamingFaceError as exc:
    print(exc.code, exc.retryable, exc.hint)
```

## The hierarchy

```
Exception
└── ScreamingFaceError
    ├── AuthenticationError
    ├── CachePullError
    ├── EngineUnavailableError
    ├── ExecutionError
    ├── LeaderboardError
    ├── MediaUnavailableError
    ├── PlanningError
    │   └── EngineCapabilityError
    ├── ProviderConnectionError
    └── ReproductionError

Warning
└── UserWarning
    └── EvaluationWarning
        ├── DuplicateMembersWarning
        ├── FixedSeedSittingWarning
        └── JudgeWriterWarning
```

## Errors

| Class | Raised when |
| --- | --- |
| `ScreamingFaceError` | Never directly. It is the base for expected failures at the public interface, and the one to catch when you do not care which. |
| `PlanningError` | An evaluation could not be resolved or validated safely, so nothing ran and nothing was charged. A route the engine does not carry, or a benchmark id that does not exist. |
| `ExecutionError` | A run reached the engine and ended without a valid report. |
| `EngineUnavailableError` | The configured engine could not be reached at all. |
| `AuthenticationError` | The engine rejected caller authentication. On a hosted engine this usually means `login()` is needed. |
| `ProviderConnectionError` | A provider connection could not be read or updated safely, including a key the provider refuses. |
| `ReproductionError` | A published capture cannot be replayed, or the Engine did not confirm replay mode. `.reproduction` carries the refusal or failure verdict. No report is returned. |
| `CachePullError` | `sf.cache.pull_from_remote()` stopped before its last page. Its `result` attribute is the `PullResult` that says how far it got. See [Cache](sf-client-api-cache.md). |
| `LeaderboardError` | A [leaderboard](sf-client-api-leaderboards.md) operation could not be completed safely. |
| `MediaUnavailableError` | A picture or file of a case cannot be fetched from the engine. The code `media_not_kept` means the engine no longer holds it, and the error is permanent. See [Case media](sf-client-api-candidate-result.md#case-media). |

`PlanningError` is the one worth distinguishing: it means the run never started, so the fix is to change the candidate, benchmark or configuration and try again at no cost.

```python
sf.evaluate(sf.Model("anthropic/claude-opus-4-8"), benchmark="medxpert", limit=1)
```

```
ProviderConnectionError: Provider 'anthropic' is not connected for Model 'anthropic/claude-opus-4-8'
```

## What an error carries

The subclasses share a diagnostic shape, so you can branch on a stable value rather than on message text.

| Attribute | Type | Meaning |
| --- | --- | --- |
| `code` | `str | None` | Stable identifier such as `model_unavailable`. Match on this, never on `message`. |
| `message` · `user_message` | `str` | What went wrong, and the form intended for display. |
| `retryable` | `bool` | Whether the same call could plausibly succeed again. The inverse of `permanent`. |
| `permanent` | `bool | None` | Whether retrying is pointless. |
| `hint` | `str | None` | A suggested next step, where one applies. |
| `status` | `int | None` | The HTTP status behind the failure, when there was one. |
| `details` | `object` | Structured context, such as which model routes were missing. |

```python
e = sf.PlanningError("boom", code="model_unavailable", permanent=True)
e.code, e.retryable, e.permanent, e.hint
```

```
('model_unavailable', False, True, None)
```

`EngineCapabilityError` is a `PlanningError` with the code `engine_capability_missing`. It means the engine lacks a capability the evaluation needs, for example the combine operators a [reducer](sf-client-api-reducers.md) compiles to. It is raised before anything is spent.

## Replay errors and verdicts

```python
import screamingface as sf

try:
    replay = sf.evaluate(pinned_cache="<pinned-cache-id>")
except sf.ReproductionError as exc:
    print(exc.code, exc.reproduction.outcome, exc.reproduction.reason)
else:
    reproduction = replay.candidates.only.reproduction
    if reproduction is not None:
        print(reproduction.outcome, reproduction.reason)
```

| Exception and code | Meaning |
| --- | --- |
| `ReproductionError: not_reproducible` | No run starts. `exc.reproduction.outcome` is `"not_reproducible"`; its reason is `"partial"` or `"unknown"` for a missing capture status, pinned cache id or benchmark revision. |
| `ReproductionError: replay_unsupported` | The Engine did not confirm replay mode. `exc.reproduction.outcome` is `"failed"` and its reason is `"replay_unsupported"`. The Client tries to stop an unacknowledged run; if that stop fails, it also emits an `EvaluationWarning`. |
| `PlanningError: partial_replay_unavailable` | The Engine cannot rebuild the published recipe and a compatible subset for `limit=n`. No run starts; use a full replay. |
| `LeaderboardError: invalid_leaderboard` | The board returned a malformed response, including a score id that differs from the requested one. No replay starts. |

A completed replay that differs from the published score returns `result.reproduction.outcome == "failed"`. Read `.reason` and `.missed_cases`; this verdict does not itself raise an exception. Partial replays and captures with no public score return `reproduction=None`. Wrong seed, recipe or id combinations raise `ValueError` before execution. Other service and execution errors still propagate.

## Warnings

A warning usually accompanies a completed run whose quality needs attention. Replay can also warn when every case misses an unsubmitted capture, or when an unacknowledged run could not be stopped. `EvaluationWarning` is the one the Client emits, and it subclasses `UserWarning`, so it appears in normal warning output and `warnings.simplefilter` controls it.

| Warning | Emitted when |
| --- | --- |
| `EvaluationWarning` | A submission carries a caveat. A run made with `limit` is a partial submission, which is not directly comparable with a full run and does not enter the ranking. |
| `DuplicateMembersWarning` | Two members of a reducer Fusion send the same request, so they may be one cached answer. It is emitted once per group. Use `sf.samples()` for independent samples. |
| `FixedSeedSittingWarning` | A run sets `answer_seed` while some calls set their own `seed` (every `sf.samples()` member does). Those calls send the same request in every sitting, so the spread across sittings is not measured. The run still goes on. |
| `JudgeWriterWarning` | A judge and the writer of the same block use one model, or a stage that reads a judge is followed directly by a model stage with the judge's model. The writer is then also the scorer. It is emitted when the SDK compiles the recipe, and the run still goes on. The message names the stages and the model: `Stage 1 (a fanout block) uses the same model 'openrouter/google/gemini-3.5-flash-lite' for its judge and its writer`. Give the judge or the writer another model to clear it. A judge on another model emits nothing. |

Note: Read the warning alongside the report or exception. Promote warnings to errors if your workflow must stop on these caveats.

```python
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("error", sf.EvaluationWarning)
    report = sf.evaluate(recipe, benchmark="draco", limit=1)
```
