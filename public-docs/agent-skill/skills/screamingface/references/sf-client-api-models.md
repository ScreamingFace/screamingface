# Models

Source: https://docs.screamingface.ai/sf-client/api/models

The Model recipe class you build, and the discovery types routes come back as: ModelInfo, ModelDetails, and their fields.

This page documents the `Model` recipe class you build, and the read-only **discovery types** the engine returns when you inspect what a route supports.

## Model

A `Model` is a single model route answering on its own: the simplest recipe, and the building block every [Fusion](sf-client-guides-fusions.md) and [Pipeline](sf-client-guides-pipelines.md) is made of. See the [Models guide](sf-client-guides-models.md) for help picking a route.

```python
sf.Model(
    model: str,
    *,
    name: str | None = None,
    prompt: str | None = None,
    params: Mapping[str, str | int | float | bool] | None = None,
    optional: bool = False,
)
```

### Parameters

| Name | Type | Meaning |
| --- | --- | --- |
| `model` | `str` | The provider route, like `openrouter/openai/gpt-5.5`. Required, positional. |
| `name` | `str | None` | Label that shows up in reports and on the leaderboard. Defaults to everything after the last `/` in the route, so `openrouter/openai/gpt-5.5` becomes `gpt-5.5`. Setting an explicit name also marks this Model as an independent sample. |
| `prompt` | `str | None` | The instruction given to the model alongside the case. Leave it out and the SDK uses its own default prompt (not the benchmark's). |
| `params` | `Mapping | None` | Generation overrides like `temperature`. Values must be `str`, `int`, `float`, or `bool` (floats have to be finite). Only the params you set get sent, since the SDK adds no defaults. Transport, tool, and benchmark-protocol names (like `model`, `messages`, `tools`, `web_search`) are reserved and will be rejected. |
| `optional` | `bool` | Whether this Model, as a Fusion member, may fail without stopping the Fusion while its [quorum](sf-client-api-fusions.md) is met. |

### Attributes

`model`, `name`, and `prompt` give you back what you passed in. `params` returns a `mappingproxy`, so you can't mutate the overrides after construction.

### Raises

| When | Error |
| --- | --- |
| The route or name is not a string | `TypeError` |
| The route or name is empty or only whitespace | `ValueError: model route must not be empty` |
| The route or name contains control characters | `ValueError` |
| A `params` value is not a scalar, or a float is not finite | `TypeError` / `ValueError` |
| A `params` name is reserved, or a name or value cannot be encoded | `ValueError` |

## Discovery types

These are the read-only values model discovery returns. `client.models.list()` hands back a `ModelInfo` for every route the configured engine can currently reach, and `client.models.get(id)` returns the fuller `ModelDetails` for one route. Consulting them before naming a route in a [Model](#model) is worthwhile: a route the engine does not carry raises a `PlanningError` at evaluation time rather than at construction time.

Everything here is read-only and assigning to a field raises `FrozenInstanceError: cannot assign to field 'provider'`. These values also never refresh themselves and the Client needs to be called again when current data is desired.

## ModelInfo

A `ModelInfo` is one model route the configured engine can currently reach. `client.models.list()` returns every addressable route, and consulting it before naming a route in a [Model](#model) is worthwhile: a route the engine does not carry raises a `PlanningError` at evaluation time rather than at construction time.

| Name | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | The route, which is what you pass to `sf.Model()`. |
| `provider` | `str` | Which provider serves the route. |
| `supported_parameters` | `tuple[str, ...]` | Which request parameters this route accepts, such as `temperature`. Passing one it does not accept fails before the run. |
| `supported_tools` | `tuple[str, ...]` | Which tools it can use, such as `web_search`. |

```python
import screamingface as sf

client = sf.Client(engine_url="http://127.0.0.1:9108")
client.models.list()[0]
```

```
ModelInfo('anthropic/claude-opus-5', provider='anthropic', parameters=5, tools=1)
```

## ModelDetails

`client.models.get(id)` returns the fuller `ModelDetails` for one route: every parameter with its schema and whether the gateway currently projects it, the tool and transport capabilities, and whether the details are stale or degraded. In a notebook it renders as a card.

| Name | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | The route, which is what you pass to `sf.Model()`. |
| `provider` | `str` | Which provider serves the route. |
| `upstream_id` | `str` | The provider's own id for the route, before canonicalization. |
| `contract_id` | `str` | Identifies the capability contract these details were built from. |
| `scope` | `str` | Which connection this was built for. `'account_connection'` means the route as your account's connection sees it, built from that connection's auth mode, rather than the route in general. |
| `auth_mode` | `str` | The authentication mode these details apply under: `api_key`, `oauth` or `none`. |
| `context_revision` | `str` | The revision of the discovery context these details were resolved against. |
| `source_revision` | `str | None` | The revision of the provider source it came from, when known. |
| `parameters` | `Mapping[str, ModelParameter]` | Each request parameter the route exposes, keyed by name. |
| `tools` | `Mapping[str, ModelCapability]` | Each tool capability, such as `web_search`, keyed by name. |
| `transport` | `Mapping[str, ModelCapability]` | Each transport capability, keyed by name. |
| `observed_at` | `datetime | None` | When the details were observed, as a timezone-aware value. `None` on degraded details and when the provider reports no observation time. |
| `expires_at` | `datetime | None` | When the observation window ends. Present together with `observed_at` and `None` otherwise. |
| `stale` | `bool` | Whether the details are past their observation window and should be refetched. |
| `degraded` | `bool` | Whether the details were served without a fresh observation. Mutually exclusive with `stale`. |
| `execution_access` | `'configured' | 'missing' | None` | Whether your account has provider access to run this route: `'configured'` when it does, `'missing'` when it does not. `None` when the gateway is too old to report it. |

Its repr shows counts rather than the full mappings, so the shape stays legible at a glance:

```python
client.models.get("anthropic/claude-opus-5")
```

```
ModelDetails('anthropic/claude-opus-5', provider='anthropic', scope='account_connection', parameters=5, tools=1, transport=1)
```

## ModelParameter

A `ModelParameter` describes one request parameter a route exposes: what it is called, how the gateway treats it, and where the description came from. The values in `ModelDetails.parameters` are these.

| Name | Type | Meaning |
| --- | --- | --- |
| `name` | `str` | The parameter name, such as `temperature`. |
| `request_path` | `str` | Where the value lands in the request the gateway sends upstream. |
| `schema` | `ModelParameterSchema | None` | The value's type and bounds, when the provider published one. `None` when no schema is known. |
| `provider_support` | `str` | Whether the provider supports the parameter. |
| `provider_source` | `str` | Where the provider description came from. |
| `provider_stale` | `bool` | Whether the provider description is out of date. |
| `provider_deprecated` | `bool | None` | Whether the provider has deprecated the parameter. |
| `gateway_status` | `str` | Whether the gateway forwards the parameter: `"enabled"` or `"disabled"`. |
| `gateway_projection` | `str | None` | How the gateway projects the value onto the request it sends. |
| `gateway_reason` | `str | None` | Why the gateway is in that state, when it has a reason to give. |
| `cache_behavior` | `str` | How this parameter participates in caching. |
| `applicable_auth_modes` | `tuple[str, ...]` | Which authentication modes the parameter applies under. |

It also carries one read-only property, `enabled`, which is `True` when `gateway_status == "enabled"`.

## ModelParameterSchema

A `ModelParameterSchema` is the bounded value schema the gateway applies to one request parameter: its type and whatever constraints the provider published. It is the type of `ModelParameter.schema`. Only the fields that constrain the declared `type` are set; the rest stay `None`.

| Name | Type | Meaning |
| --- | --- | --- |
| `type` | `str | tuple[str, ...]` | The allowed value type, such as `number` or `string`, or a tuple when more than one is accepted. |
| `minimum` | `float | None` | The lowest allowed value, for a numeric type. |
| `maximum` | `float | None` | The highest allowed value, for a numeric type. |
| `enum` | `tuple[str, ...] | None` | The closed set of allowed values, when the parameter is restricted to one. |
| `items` | `str | None` | The element type each array entry must be, for an array type. |
| `pattern` | `str | None` | An anchored regular expression a string value must match. |
| `max_length` | `int | None` | The longest allowed string length. |

It also carries a `validate(value)` method that raises `ValueError` when a value violates the published schema, and returns `None` otherwise.

## ModelCapability

A `ModelCapability` describes one tool or transport capability. The values in `ModelDetails.tools` and `ModelDetails.transport` are these.

| Name | Type | Meaning |
| --- | --- | --- |
| `provider_support` | `str` | Whether the provider supports the capability. |
| `gateway_status` | `str` | Whether the gateway exposes the capability: `"enabled"` or `"disabled"`. |
| `reason` | `str` | Why the capability is in that state, when there is a reason to give. |
