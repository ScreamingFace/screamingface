# Fusion

Source: https://docs.screamingface.ai/sf-client/api/fusions

Combine parallel members into one answer through a synthesizer.

A fusion is a [Recipe](sf-client-api-recipes.md) that runs several members in parallel and combines their answers with an explicit synthesizer. You build it as a chain: `sf.Fanout(members)` sends the question to every member, and `>> sf.Synthesize(model)` adds the synthesizer. The chain is an [`sf.Pipeline`](sf-client-api-pipelines.md). Like every recipe it is frozen and holds no Client, so you can build it before connecting. The [Fusions guide](sf-client-guides-fusions.md) walks through building one.

```python
sf.Fanout(
    members: Sequence[str | Recipe],
    *,
    signals: Mapping[str, SignalSource] | None = None,
    quorum: int | Literal["all"] = "all",
    name: str | None = None,
    prompt: str | None = None,
) >> sf.Synthesize(
    model: str | Recipe,
    *,
    prompt: str | None = None,
)
```

| Attribute | Type | Meaning |
| --- | --- | --- |
| `name` | `str` | The fusion's name. Inferred by joining member names with `+` unless you pass `name` to `sf.Fanout`. |
| `steps` | `tuple` | The `Fanout` step, then the `Synthesize` step. The `Fanout` step keeps the members that run in parallel (at least one). The `Synthesize` step keeps the `model` that combines the members' answers into the single graded answer. |
| `optional` | `bool` | `False`. Set it on an `sf.Pipeline` that wraps the chain, for an optional member. |

Note: Members and the synthesizer are themselves recipes, so any of them can be a `Model`, another fusion, or a [Pipeline](sf-client-api-pipelines.md), nested in any combination. Only the synthesizer's final answer is graded. A reducer such as `sf.Vote` can close the block in place of `sf.Synthesize`.

```python
fusion = sf.Fanout(
    ["openrouter/deepseek/deepseek-v4-pro", "openrouter/z-ai/glm-5.2"],
) >> sf.Synthesize("openrouter/moonshotai/kimi-k3")
report = sf.evaluate(fusion, benchmark="ifeval", limit=1)
```

A member marked `optional=True` (on a `Model` or a `Pipeline`, or a fusion wrapped in `sf.Pipeline([...], optional=True)`) can fail while the run still completes, as long as at least `quorum` members succeed. A failed optional member appears as an answer with the status `fail` and the reason `missing`, and never as a vote. When fewer than `quorum` members succeed, or a required member fails, the candidate fails and its score is `None`. `optional=True` is only valid on a member of `sf.Fanout`; elsewhere it raises `ValueError: optional=True is only supported on sf.Fanout members`.

[Diagram: Topology: members A and B succeed and member C, optional, fails; the quorum check passes the answers that arrived to the reducer or Synthesize step when enough members succeeded, and the candidate fails when the quorum is not met or a required member failed.]

Which members reach the last step, and where a failure stops the candidate.
