# Classify

Source: https://docs.screamingface.ai/sf-client/api/classify

Send one text to a text classifier and read its label scores.

`sf.classify(model, input)` and `Client.classify(model, input)` send one text to a text classifier that you configured on your own endpoint, through the engine's `/classify`, and return a `Classification`. The call is synchronous: `AsyncClient` has no `classify`. An engine without `/classify` raises `EngineCapabilityError`.

[Diagram: Flow: the Client sends the classify call to the Engine, which reaches your classifier endpoint through the AI Gateway, using the key you stored with sf.connect.]

The path of sf.classify from the Client to your classifier endpoint.

## The call

| Signature | What it does |
| --- | --- |
| `sf.classify(model: str, input: str) -> Classification` | Classifies `input` with the classifier named by `model`, a model id such as `byom_<id>/classifier_v1`. `Client.classify` takes the same arguments on a Client you built. |

```python
import screamingface as sf
result = sf.classify("byom_<id>/classifier_v1", "I love this")
result
```

```
Classification(model='byom_<id>/classifier_v1', contract='classification-scores-v1',
               scores=(LabelScore(label='POSITIVE', score=0.8),
                       LabelScore(label='NEGATIVE', score=0.2)))
```

## What the classifier endpoint receives

The engine sends `{"inputs": <input>}` to the endpoint's request path with the bearer key stored by `sf.connect(<endpoint id>, api_key=...)`. The response is a flat list or a single-batch list of `{"label", "score"}` objects with scores from 0 to 1.

## What it returns

| Type | Field | Meaning |
| --- | --- | --- |
| `Classification` | `model` | The classifier model id that answered. |
| `contract` | The result contract. It is `classification-scores-v1` today. |
| `scores` | A tuple of `LabelScore` values in the classifier's own order, ties included. |
| `LabelScore` | `label` | The label, a `str`. |
| `score` | The score for that label, a `float`. |

## Limits and timing

-   **Size:** The encoded request may be at most 8,192 bytes. A longer input raises `PlanningError` with the code `uri_too_long` before any call.
-   **Time:** The call asks the engine to wait at most 30 seconds and reads the response for 45 seconds.
-   **Retries:** The SDK never sends a classification again, neither after a sign-in nor through a redirect. A result that the engine spilled to an artifact is fetched only from the engine's exact signed artifact path, and that fetch alone is sent once more when a Cloudflare Access sign-in interrupted it.

## Errors

| Error and code | Raised when |
| --- | --- |
| `PlanningError: uri_too_long` | The encoded request is larger than 8,192 bytes. Raised before any call. |
| `PlanningError: malformed_source` | The model id or the input holds a character that UTF-8 cannot encode. Raised before any call. |
| `PlanningError: classifier_not_found` | The engine refused the call: no classifier with this model id is available to you. |
| `ExecutionError: profile_not_found` | No key is connected for the endpoint. Connect one with `sf.connect(<endpoint id>, api_key=...)`. The error says the classification may have run and been billed. |
| `EngineCapabilityError` | The engine does not serve `/classify`. |

An error is `retryable` only when nothing ran: the engine was not reached, a rate limit, or a refusal at admission. An engine timeout, any other server failure, a connection lost after the request was sent and a result that could not be read are not retryable, because classifying again runs the classifier again and may bill it again. See [Errors and warnings](sf-client-api-errors.md) for the attributes every error carries.

```python
sf.classify("byom_abc/classifier_v1", "hello")
```

```
PlanningError: The SF Engine refused the classification: no classifier with this model ID is available to the caller
```

```python
sf.classify("byom_abc/classifier_v1", "x" * 9000)
```

```
PlanningError: The classification request is 9088 bytes once encoded; the SF Engine takes at most 8192
```
