# url4

Source: https://docs.screamingface.ai/learn/url4

The grammar and protocol that packages sources and an intent into one line, so a fusion runs, reproduces, and can be reused like a model call.

**url4** is a grammar and a protocol for saying *given these sources, do this*. It packs the sources, the intent, and everything needed to run them into one line of text: `(data)!intent`.

Everything you build in the [Client](sf-client.md) compiles to one of these, whether it is a single model, a [Fusion](sf-client-guides-fusions.md), or a whole benchmark run. The line is also an **address**: hand it to the [engine](learn-engine.md) and it resolves, the way a URL resolves.

That is what makes a composed system shareable at all. A model is easy to pass around because it is a thing with a name; an ensemble usually is not, because it lives as glue code in somebody's notebook. url4 gives it a name you can copy. A Fusion you like stops being a one-off and becomes an artifact you can log, diff, publish, and call again like any single model.

## Two layers

A url4 string has two layers. The **grammar**, `(data)!intent`, is what you write and what a node parses: sources in parentheses, an intent after the `!`. The **protocol** is how any conforming node, such as the engine, resolves each source, runs the intent, and returns a result. You write the grammar; the protocol is what makes the same string runnable anywhere.

## The shape

Sources go in parentheses; the intent comes after the `!`. The simplest expression is a single source and an intent:

```
(a=https://x, tone='formal')!'Summarize $a in a $tone tone'
```

A source can be a URI, a literal value, or a nested url4 expression. Sources can be named (`a=…`), referenced by name (`$a`) or position (`$1`), weighted and budgeted, iterated over, and expanded. Because a source can itself be another url4 expression, an expression composes recursively into an arbitrary graph. A few real shapes, drawn from the grammar's own test suite:

```
https://x!summarize                         # fetch a source, then apply an intent
(article=https://x)!use $article            # bind a source to a name, reference it as $article
(https://x, https://y)!first=$1 second=$2    # two parallel sources, referenced by position
(claude:0.6:/claude(x)!go)!combine           # a named source with a weight, calling another expression
(a, b)*('row: $item')!'per row'              # iterate a body over a collection, then reduce
```

## Two ways to run it

The same grammar drives two execution modes, and one expression can mix them freely.

**Model mode** (the spec's *LLM mode*). Sources are context and the intent is a natural-language prompt. The engine feeds the resolved sources to a model, or to a [Fusion](sf-client-guides-fusions.md) of models, and synthesizes one answer. This is the mode the Client uses: a Fusion is a url4 expression in model mode.

**Compute mode** (the spec's *remote data science*, or *RDS*, mode). Sources are structured inputs and the intent points at code, a script or a notebook. The engine binds the inputs to the code's contract and runs it, so computation can run next to data that never has to move. A single expression can chain the two: a compute step that prepares data, feeding a model step that summarizes it. The whole chain stays one addressable url4.

## How it runs

Parsing a url4 string produces a syntax tree, which is then lowered to a **typed DAG**. Independent nodes run in parallel, and the references you wrote (`$a`, `$1`) become the edges between them. The graph is demand-driven, so only the nodes your result actually depends on get scheduled.

Text and tree are two views of the same thing. `url4.render` writes the canonical form, so `url4.build(url4.render(node))` gives back the tree you started with. An expression you typed in a shorter form comes back normalised: `https://x!summarize` renders as `(https://x)!summarize`. Strings that came from a report are already canonical and round-trip exactly, which is what lets a run be logged, shared, and rebuilt exactly rather than approximately.

```python
import url4

node = url4.build("(https://a, https://b)!'summarize both'")
url4.render(node)   # -> "(https://a, https://b)!'summarize both'"   (lossless round-trip)
```

## An address, not just a string

Because the whole request lives in one URI, the engine treats a url4 expression the way `http` treats a URL: as an address it resolves. The same expression always describes the same work, which makes the call cacheable and safe to repeat. Save a Fusion's url4, hand it to an [engine](learn-engine.md), and it runs like any other model call. A source inside one expression can be the result of another expression on another node, so fusions nest into larger systems without anyone having to unpack them.

Putting the request in the URI rather than in out-of-band configuration has a practical payoff: ordinary HTTP infrastructure such as gateways, caches, and logs can route and trace it without understanding the grammar, and attribution metadata travels *with* the request instead of beside it. To serve and call a url4 node yourself, see the [url4 SDK](learn-url4-sdk.md), which exposes the same shape the engine does.

## Why it exists

Every run compiles to one canonical url4 string, and that string is the audit trail. Import it and you hold the system itself along with its benchmark run, not a description of either. It is also what the [Leaderboard](learn-leaderboard.md) stores next to a rank, which is how a published result stays checkable.

Be careful about what it pins down, though. Model outputs vary between runs, so running an expression again will not reproduce the numbers to the decimal. What the expression fixes is the *definition* of the run, not its results. Stability is the promise on top of that: a url4 written today is meant to run tomorrow.

## In code

To parse, build, and execute url4 from Python, see the [url4 SDK](learn-url4-sdk.md). The grammar, parser, and DAG live in [`packages/url4`](https://github.com/ScreamingFace/screamingface/tree/main/packages/url4): the recursive-descent parser in [`core/grammar.py`](https://github.com/ScreamingFace/screamingface/blob/main/packages/url4/src/url4/core/grammar.py), the canonical renderer in [`core/render.py`](https://github.com/ScreamingFace/screamingface/blob/main/packages/url4/src/url4/core/render.py), and the executor in [`src/url4/dag`](https://github.com/ScreamingFace/screamingface/tree/main/packages/url4/src/url4/dag).
