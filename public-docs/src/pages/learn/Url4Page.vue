<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import { learnNavigation as navigation } from '@/navigation/learn'

const GH_TREE = 'https://github.com/ScreamingFace/screamingface/tree/main'
const GH_BLOB = 'https://github.com/ScreamingFace/screamingface/blob/main'

const examples = `https://x!summarize                         # fetch a source, then apply an intent
(article=https://x)!use $article            # bind a source to a name, reference it as $article
(https://x, https://y)!first=$1 second=$2    # two parallel sources, referenced by position
claude:0.6:/claude(x)!go                     # a named source with a weight, calling another expression
(a, b)*('row: $item')!'per row'              # iterate a body over a collection, then reduce`

const roundtrip = `import url4

node = url4.build("(https://a, https://b)!'summarize both'")
url4.render(node)   # -> "(https://a, https://b)!'summarize both'"   (lossless round-trip)`
</script>

<template>
  <DocLayout
    title="url4"
    description="The grammar and protocol that packages sources and an intent into one line, so a fusion runs, reproduces, and can be reused like a model call."
    :navigation="navigation"
  >
    <p>
      <strong>url4</strong> is a grammar and a protocol for saying
      <em>given these sources, do this</em>. It packs the sources, the intent, and everything needed
      to run them into one line of text: <code>(data)!intent</code>.
    </p>

    <p>
      Everything you build in the <RouterLink to="/sf-client">Client</RouterLink> compiles to one of
      these, whether it is a single model, a
      <RouterLink to="/sf-client/guides/fusions">Fusion</RouterLink>, or a whole benchmark run. The
      line is also an <strong>address</strong>: hand it to the
      <RouterLink to="/learn/engine">engine</RouterLink> and it resolves, the way a URL resolves.
    </p>

    <p>
      That is what makes a composed system shareable at all. A model is easy to pass around because
      it is a thing with a name; an ensemble usually is not, because it lives as glue code in
      somebody's notebook. url4 gives it a name you can copy. A Fusion you like stops being a
      one-off and becomes an artifact you can log, diff, publish, and call again like any single
      model.
    </p>

    <h2>Two layers</h2>

    <p>
      A url4 string has two layers. The <strong>grammar</strong>, <code>(data)!intent</code>, is
      what you write and what a node parses: sources in parentheses, an intent after the
      <code>!</code>. The <strong>protocol</strong> is how any conforming node, such as the engine,
      resolves each source, runs the intent, and returns a result. You write the grammar; the
      protocol is what makes the same string runnable anywhere.
    </p>

    <h2>The shape</h2>

    <p>
      Sources go in parentheses; the intent comes after the <code>!</code>. The simplest expression
      is a single source and an intent:
    </p>

    <CodeBlock code="(a=https://x, tone='formal')!'Summarize $a in a $tone tone'" language="text" />

    <p>
      A source can be a URI, a literal value, or a nested url4 expression. Sources can be named
      (<code>a=…</code>), referenced by name (<code>$a</code>) or position (<code>$1</code>),
      weighted and budgeted, iterated over, and expanded. Because a source can itself be another
      url4 expression, an expression composes recursively into an arbitrary graph. A few real
      shapes, drawn from the grammar's own test suite:
    </p>

    <CodeBlock :code="examples" language="text" />

    <h2>Two ways to run it</h2>

    <p>The same grammar drives two execution modes, and one expression can mix them freely.</p>

    <p>
      <strong>Model mode</strong> (the spec's <em>LLM mode</em>). Sources are context and the intent
      is a natural-language prompt. The engine feeds the resolved sources to a model, or to a
      <RouterLink to="/sf-client/guides/fusions">Fusion</RouterLink> of models, and synthesizes one
      answer. This is the mode the Client uses: a Fusion is a url4 expression in model mode.
    </p>

    <p>
      <strong>Compute mode</strong> (the spec's <em>remote data science</em>, or <em>RDS</em>,
      mode). Sources are structured inputs and the intent points at code, a script or a notebook.
      The engine binds the inputs to the code's contract and runs it, so computation can run next to
      data that never has to move. A single expression can chain the two: a compute step that
      prepares data, feeding a model step that summarizes it. The whole chain stays one addressable
      url4.
    </p>

    <h2>How it runs</h2>

    <p>
      Parsing a url4 string produces a syntax tree, which is then lowered to a
      <strong>typed DAG</strong>. Independent nodes run in parallel, and the references you wrote
      (<code>$a</code>, <code>$1</code>) become the edges between them. The graph is demand-driven,
      so only the nodes your result actually depends on get scheduled.
    </p>

    <p>
      Text and tree are two views of the same thing, and converting between them loses nothing in
      either direction: <code>url4.build(url4.render(node))</code> gives back the tree you started
      with. That guarantee is what lets a run be logged, shared, and replayed exactly rather than
      approximately.
    </p>

    <CodeBlock :code="roundtrip" language="python" />

    <h2>An address, not just a string</h2>

    <p>
      Because the whole request lives in one URI, the engine treats a url4 expression the way
      <code>http</code> treats a URL: as an address it resolves. The same expression always
      describes the same work, which makes the call cacheable and safe to repeat. Save a Fusion's
      url4, hand it to an <RouterLink to="/learn/engine">engine</RouterLink>, and it runs like any
      other model call. A source inside one expression can be the result of another expression on
      another node, so fusions nest into larger systems without anyone having to unpack them.
    </p>

    <p>
      Putting the request in the URI rather than in out-of-band configuration has a practical
      payoff: ordinary HTTP infrastructure such as gateways, caches, and logs can route and trace it
      without understanding the grammar, and attribution metadata travels <em>with</em> the request
      instead of beside it. To serve and call a url4 node yourself, see the
      <RouterLink to="/learn/url4-sdk">url4 SDK</RouterLink>, which exposes the same shape the
      engine does.
    </p>

    <h2>Why it exists</h2>

    <p>
      Every run compiles to one canonical url4 string, and that string is the audit trail. Import it
      and you hold the system itself along with its benchmark run, not a description of either. It
      is also what the <RouterLink to="/learn/leaderboard">Leaderboard</RouterLink> stores next to a
      rank, which is how a published result stays checkable.
    </p>

    <p>
      Be careful about what it pins down, though. Model outputs vary between runs, so replaying an
      expression will not reproduce the numbers to the decimal. What the expression fixes is the
      <em>definition</em> of the run, not its results. Stability is the promise on top of that: a
      url4 written today is meant to run tomorrow.
    </p>

    <h2>In code</h2>

    <p>
      To parse, build, and execute url4 from Python, see the
      <RouterLink to="/learn/url4-sdk">url4 SDK</RouterLink>. The grammar, parser, and DAG live in
      <a :href="`${GH_TREE}/packages/url4`" target="_blank" rel="noopener"
        ><code>packages/url4</code></a
      >: the recursive-descent parser in
      <a :href="`${GH_BLOB}/packages/url4/src/url4/core/grammar.py`" target="_blank" rel="noopener"
        ><code>core/grammar.py</code></a
      >, the canonical renderer in
      <a :href="`${GH_BLOB}/packages/url4/src/url4/core/render.py`" target="_blank" rel="noopener"
        ><code>core/render.py</code></a
      >, and the executor in
      <a :href="`${GH_TREE}/packages/url4/src/url4/dag`" target="_blank" rel="noopener"
        ><code>src/url4/dag</code></a
      >.
    </p>
  </DocLayout>
</template>
