# Compose model fusions. Reproduce every run from one line.

Source: https://docs.screamingface.ai

ScreamingFace · documentation

ScreamingFace is an open toolkit for composing model *fusions*: any multi-model orchestration graded as one against a real benchmark. Every fusion can be expressed as a single line, re-runnable for free from cache or on your own keys.

[Quickstart](sf-client-first-fusion.md) [Overview](sf-client.md) [Installation](sf-client-installation.md)[GitHub](https://github.com/ScreamingFace)

```
$ pip install screamingface
```

In these docs

[start here Overview What ScreamingFace is, the smallest end-to-end example, and how the Client, engine, and url4 fit together.](sf-client.md) [tutorial Quickstart Compose a fusion, run it against a benchmark, and read how it compares to its best single member.](sf-client-first-fusion.md) [setup Installationdraft Install the ScreamingFace Client and point it at an engine.](sf-client-installation.md) [concepts Learn more Architecture, the url4 protocol and SDK, the engine and its trust boundary, caching, and the leaderboard.](learn.md)

A few terms

`fusion`

A composed AI system built from many heterogeneous models, such as an ensemble, a router, a routed ensemble, a cascade, or any multi-model artifact you compose, run, and share.

[`url4`](learn-url4.md)

A grammar and protocol: one line that describes a fusion and its benchmark run, and reproduces it. It is also an address the engine resolves, so anyone holding the `url4` can rerun the result or call the fusion like a single model.

[`engine`](learn-engine.md)

The runtime that executes a fusion. You point the Client at one you run locally, or a hosted one.

😱ScreamingFace

[Overview](sf-client.md) [Quickstart](sf-client-first-fusion.md)[GitHub](https://github.com/ScreamingFace)
