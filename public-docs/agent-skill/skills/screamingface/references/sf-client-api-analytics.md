# Analytics

Source: https://docs.screamingface.ai/sf-client/api/analytics

Analytics controls for opting in and out, and what it collects.

`sf.analytics` controls the Client's analytics. Analytics are on by default. No account identity or login is involved: events carry a random installation ID. Per the notice, the Client collects API usage, the SDK version and whether you chose a local or a hosted engine, and it stores no fusion, prompt, output, score or key.

## The first import

On the first `import screamingface` with no saved choice, the Client prints this notice to standard error, saves the choice `accepted` with a random installation ID, and prints nothing on later imports. The notice never waits for input. When `DO_NOT_TRACK` is set, the first import prints no notice and saves nothing.

```
ScreamingFace collects anonymous usage analytics (API usage, SDK versioning, and your local-or-hosted engine preference) to help us build a better API. It does not store any fusion, prompts, outputs, scores, or keys. It's on by default; turn it off anytime with `sf.analytics.disable()` (or set `DO_NOT_TRACK=1`).
```

## Functions

| Signature | What it does |
| --- | --- |
| `sf.analytics.status()` | Returns a `dict` with the saved choice and the effective state. |
| `sf.analytics.enable(*, persist=True)` | Opts in and prints `Analytics enabled.`. With `persist=False`, the opt-in lasts for this process only. When `DO_NOT_TRACK` is set, it prints `Couldn't enable analytics; tracking remains off.` |
| `sf.analytics.disable(*, process_only=False)` | Stops tracking, saves the choice `declined`, discards the installation ID and prints `Analytics disabled.`. With `process_only=True`, it stops tracking in this process and saves nothing. |
| `sf.analytics.reset_identifier()` | Rotates the installation ID of an accepted installation, so old and new activity do not join, and returns the status. It changes nothing when analytics are off or session-only. |

## Status

| Key | Meaning |
| --- | --- |
| `choice` | `'unknown'` when no choice is saved (`DO_NOT_TRACK` was set at the first import, or the file is unreadable or invalid), `'accepted'` or `'declined'`. An opt-in with `persist=False` reads `'accepted'`. |
| `enabled` | `True` only when the choice is `'accepted'` and neither `DO_NOT_TRACK` nor `disable(process_only=True)` is in effect. |
| `scope` | `'installation'` for a saved choice, `'session'` for `persist=False`, `'browser'` in Colab. |
| `installation_id` | The random installation ID while analytics are enabled, otherwise `None`. Always `None` in Colab and in a session-only opt-in. |

```python
import screamingface as sf

sf.analytics.status()
```

```
{'choice': 'accepted', 'enabled': True, 'scope': 'installation',
 'installation_id': 'cfcae993-e908-4513-8e01-7d1f3822031c'}
```

```python
sf.analytics.enable()
sf.analytics.status()
```

```
Analytics enabled.
{'choice': 'accepted', 'enabled': True, 'scope': 'installation',
 'installation_id': 'cfcae993-e908-4513-8e01-7d1f3822031c'}
```

```python
sf.analytics.reset_identifier()['installation_id']
```

```
'd0115a23-dae9-4614-aeee-d82614ed3fdb'
```

```python
sf.analytics.disable()
sf.analytics.status()
```

```
Analytics disabled.
{'choice': 'declined', 'enabled': False, 'scope': 'installation', 'installation_id': None}
```

```python
sf.analytics.enable(persist=False)
sf.analytics.status()
```

```
Analytics enabled.
{'choice': 'accepted', 'enabled': True, 'scope': 'session', 'installation_id': None}
```

```python
sf.analytics.disable(process_only=True)
```

```
Analytics disabled for this process.
```

## Where the choice is saved

A saved choice lives in `~/.screamingface/analytics.json`, independent of the runtime data directory. `SCREAMINGFACE_ANALYTICS_CONFIG` names another path. The file is replaced atomically, so a reader sees the old or the new document, never a partial write. A missing file is a new install: the first import saves `accepted`, unless `DO_NOT_TRACK` is set. An unreadable or invalid file reads as `unknown` and analytics stay off. The file holds these keys:

```json
{"version": 1, "consent_version": "1", "choice": "accepted", "installation_id": "74a24bce-39a4-490a-926a-a5baab1e75aa"}
```

## screamingface analytics

The shell command runs the same controls and prints the resulting status as one line of JSON. `reset-id` is `reset_identifier()`.

```bash
screamingface analytics status
screamingface analytics enable
screamingface analytics reset-id
screamingface analytics disable
```

```bash
screamingface analytics enable
```

```
{"choice": "accepted", "enabled": true, "scope": "installation", "installation_id": "88d3a1ad-4122-43f3-a3b2-aa9947e43120"}
```

## DO\_NOT\_TRACK

Analytics are off while `DO_NOT_TRACK` has any value other than an empty string, `0`, `false`, `no` or `off`, compared without regard to case. The variable wins over a saved opt-in: `status()['enabled']` is `False` while the saved choice stays `accepted`, and `enable()` does not turn analytics on. The sample below ran on a machine with no saved choice.

```bash
DO_NOT_TRACK=1 python -c "import screamingface as sf; sf.analytics.enable(); print(sf.analytics.status())"
```

```
Couldn't enable analytics; tracking remains off.
{'choice': 'unknown', 'enabled': False, 'scope': 'installation', 'installation_id': None}
```

## Colab

This section was read from the source and not run on 0.1.11, because it needs a Colab notebook.

In Google Colab the choice lives in the browser, not on disk. The Client reads and writes it through a bridge to the notebook page.

-   **Status:** `scope` is `'browser'`, `installation_id` is `None`, and the dict adds `persistent_id` (the browser's saved ID) and `pending` (a browser round trip is in flight).
-   **`enable()`:** Waits up to 3 seconds for the browser to confirm. A timeout leaves analytics off. `enable(persist=False)` raises `ValueError`, because a Colab opt-in needs browser consent.
-   **`disable()`:** Saves the decline in the browser. The printed message says when the browser is still saving or could not save.
-   **Setup notice:** The browser reports its saved state when the notice would appear.
