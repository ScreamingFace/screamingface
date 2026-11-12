# Url4

Source: https://docs.screamingface.ai/sf-client/api/url4

The string value a run carries, and the editable Python it forks to.

A `Url4` is the complete expression a candidate executed: you get it as `candidate.url4` and on every [leaderboard entry](sf-client-api-leaderboards.md). It subclasses `str`, so every string operation works and it compares and serializes as its own text. Pass one back to [evaluate()](sf-client-api-clients.md) to reproduce the run.

Note: Two things share the name. The lowercase `url4` is the protocol, a text grammar covered on the [url4 concept page](learn-url4.md). `Url4` here is the Python value the Client hands back. The [Reproduce & share guide](sf-client-guides-reproduce-and-share.md) is the how-to.

```python
class Url4(str):
    def to_python(self) -> str: ...
```

| Name | Returns | Meaning |
| --- | --- | --- |
| `to_python()` | `str` | Editable ScreamingFace Python for the compiled candidate or evaluation: a fork you can modify and re-run. A recipe with several steps is written as a chain joined with `>>`, one step per line. It raises `ValueError` for a url4 with the old scoring-judge template (`URL4 Candidate has an unsupported judge call`) and a url4 with an old max or min field pick (`URL4 Candidate has a pick spec this SDK version cannot rebuild`). |

You rarely build one by hand; when you do, `sf.Url4(value: str)` wraps a string. Because it is a `str`, it prints, slices, and stores like any string; `to_python()` is the one extra affordance.

```python
line = report.candidates.only.url4
print(line.to_python())
```

```
import screamingface as sf

candidate = (
    sf.Fanout([sf.Model('openrouter/google/gemini-3.5-flash-lite', name='a', params={'max_tokens': 120}), sf.Model('openrouter/google/gemini-3.5-flash-lite', name='b', params={'max_tokens': 120})])
    >> sf.Judge('openrouter/google/gemini-3.5-flash-lite', rubric='Score 10 if the answer is 2, else 1.')
    >> sf.ArgMax('score:judge')
)

report = sf.evaluate(
    candidate,
    benchmark='medxpert',
    limit=1,
)
```
