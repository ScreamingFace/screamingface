<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import { learnNavigation as navigation } from '@/navigation/learn'

const GH_TREE = 'https://github.com/ScreamingFace/screamingface/tree/main'
const GH_BLOB = 'https://github.com/ScreamingFace/screamingface/blob/main'

const install = `pip install url4`

const roundtrip = `import url4

# Parse a url4 string into a syntax tree, and render it back, losslessly.
node = url4.build("(https://a, https://b)!'summarize both'")
assert url4.render(node) == "(https://a, https://b)!'summarize both'"

for child in url4.walk(node):   # preorder traversal of the tree
    ...`

const build = `import url4

# Build the same expression with the Python DSL instead of a string.
expr = url4.expr(
    url4.src("https://a"),
    url4.src("https://b"),
    intent=url4.text("summarize both"),
)
print(url4.render(expr))   # a canonical url4 string`

const run = `import url4

# A StaticIOLayer returns fixed content per source, ideal for tests.
io = url4.StaticIOLayer({"https://a": "alpha", "https://b": "beta"})

result = url4.evaluate_sync("(https://a, https://b)!'summarize both'", io=io)
print(result.text)      # the reduced answer
print(result.request)   # the canonical url4 that actually ran`

const serve = `# Serving needs the server extra: pip install "url4[server]"
from url4 import Url4Node

node = Url4Node("demo")
node.serve()   # 127.0.0.1:4404 by default, an HTTP node other expressions can call`

const cli = `url4 eval "(https://a, https://b)!'summarize both'"
url4 serve`
</script>

<template>
  <DocLayout
    title="url4 SDK"
    description="The Python library for building, reading, and running url4 expressions."
    :navigation="navigation"
  >
    <p>
      The url4 SDK is the Python library for the
      <RouterLink to="/learn/url4">url4</RouterLink> protocol: parse an expression, build one in
      code, walk the tree, or execute it. It ships as the <code>url4</code> package.
    </p>

    <CodeBlock :code="install" language="bash" />

    <h2>Parse and render</h2>

    <p>
      <code>build</code> parses a url4 string into a frozen syntax tree; <code>render</code> turns a
      tree back into canonical text. The two are exact inverses, so an expression survives a
      round-trip unchanged. That guarantee is what makes url4 a reliable audit trail.
      <code>walk</code> traverses the tree.
    </p>

    <CodeBlock :code="roundtrip" language="python" />

    <h2>Build in Python</h2>

    <p>
      When you would rather not assemble strings, the builder API constructs the same tree directly.
      <code>src</code> makes a source (with optional name, weight, budgets),
      <code>expr</code> groups sources under an intent, and <code>iterate</code> /
      <code>reduce</code> express map-and-reduce. <code>ref</code> and <code>text</code> build
      references and literals.
    </p>

    <CodeBlock :code="build" language="python" />

    <h2>Execute</h2>

    <p>
      Execution needs an <strong>I/O layer</strong>: the piece that resolves a source to content.
      <code>StaticIOLayer</code> returns fixed values (ideal for tests);
      <code>HttpIOLayer</code> fetches over the network. <code>evaluate_sync</code> runs an
      expression in one call and returns a result carrying both the answer and the canonical request
      that produced it. For async use, <code>url4.Client</code> runs expressions inside an event
      loop.
    </p>

    <CodeBlock :code="run" language="python" />

    <p>
      A url4 node can also be served over HTTP, so other expressions can call it as a source. This
      is the same shape the <RouterLink to="/learn/engine">engine</RouterLink> exposes. Serving
      needs uvicorn, which comes with the <code>url4[server]</code> extra rather than the base
      install:
    </p>

    <CodeBlock :code="serve" language="python" />

    <p>
      Parsing and execution raise typed errors: <code>ParseError</code> for malformed text,
      <code>ScopeError</code> for an unresolved reference, <code>CycleError</code> for a circular
      dependency, and <code>RenderError</code> when a tree cannot round-trip, all subclasses of
      <code>Url4Error</code>.
    </p>

    <h2>From the command line</h2>

    <CodeBlock :code="cli" language="bash" />

    <blockquote>
      <strong>url4 SDK vs the ScreamingFace Client.</strong> This library is the low-level protocol:
      parse, build, and run url4. The
      <RouterLink to="/sf-client">ScreamingFace Client</RouterLink> (<code>screamingface</code>) is
      the research-facing layer on top: it composes fusions and benchmarks, drives an engine, and
      reads back scored reports. Reach for the SDK when you are working with url4 itself; reach for
      the Client when you are running evaluations.
    </blockquote>

    <h2>Where the code lives</h2>

    <ul>
      <li>
        <a :href="`${GH_TREE}/packages/url4`" target="_blank" rel="noopener"
          ><code>packages/url4</code></a
        >: the package, with its
        <a :href="`${GH_BLOB}/packages/url4/README.md`" target="_blank" rel="noopener">README</a>.
      </li>
      <li>
        <a
          :href="`${GH_BLOB}/packages/url4/src/url4/core/builders.py`"
          target="_blank"
          rel="noopener"
          ><code>src/url4/core/builders.py</code></a
        >: the Python builder API.
      </li>
      <li>
        <a :href="`${GH_TREE}/packages/url4/examples`" target="_blank" rel="noopener"
          ><code>packages/url4/examples</code></a
        >: runnable examples.
      </li>
    </ul>
  </DocLayout>
</template>
