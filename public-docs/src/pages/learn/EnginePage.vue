<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import { learnNavigation as navigation } from '@/navigation/learn'

const GH_TREE = 'https://github.com/ScreamingFace/screamingface/tree/main'

const point = `import screamingface as sf

sf.configure(engine_url="http://127.0.0.1:9108")   # the Client talks only to an Engine`

const runLocal = `pip install "screamingface[runtime]"
screamingface prepare draco   # benchmark data, once
screamingface up              # engine, gateway, leaderboard on loopback`

const health = `screamingface status`
</script>

<template>
  <DocLayout
    title="ScreamingFace Engine"
    description="The runtime that turns a url4 expression into a result, and the trust boundary that holds the keys."
    :navigation="navigation"
  >
    <p>
      The engine is the runtime that runs
      <RouterLink to="/learn/url4">url4</RouterLink> expressions. The
      <RouterLink to="/sf-client">Client</RouterLink> never calls a model provider itself. It hands
      a url4 expression to an engine. The engine does the work: schedules the graph, reaches the
      providers, and streams back usage and the result. Because it sits between you and the
      providers, it is also the system's <strong>trust boundary</strong>, the one place that holds
      both your credentials and the benchmark answer keys.
    </p>

    <p>
      You mostly will not touch it directly. The
      <RouterLink to="/sf-client">Client</RouterLink> talks to it for you, and the only decision
      that usually matters is which engine to point at.
    </p>

    <h2>How it executes</h2>

    <p>
      At its core is a <strong>demand-driven, memoized DAG executor</strong>. Demand-driven means it
      works backwards from the result, so it only runs the nodes that result actually needs.
      Memoized means a value shared by several branches is computed exactly once, not repeated.
      Independent nodes run at the same time. The first failure cancels the others rather than
      letting a broken run drift on. The number of calls running at once is capped so a wide fan-out
      can't overwhelm the providers.
    </p>

    <p>
      The executor lives in
      <a :href="`${GH_TREE}/packages/url4/src/url4/dag`" target="_blank" rel="noopener"
        ><code>packages/url4/…/dag</code></a
      >; the cloud service that wraps it, control plane, one-shot runner, and the streaming wire
      protocol, is
      <a :href="`${GH_TREE}/apps/screamingface-engine`" target="_blank" rel="noopener"
        ><code>apps/screamingface-engine</code></a
      >.
    </p>

    <h2>The trust boundary</h2>

    <p>
      The engine holds what must not leak. Provider credentials are handed to it once and stored
      encrypted at rest (AES-256-GCM) by the AI gateway's credential store, and are never returned
      to the Client. Benchmark answer keys, rubrics, and grading stay engine-side. That separation
      is what makes a score mean something: the code being graded cannot read the answers it is
      being graded against, and neither can the person who wrote it.
    </p>

    <p>
      Be clear about the direction this runs, though. The boundary protects the answer keys and your
      credentials, not the content of your prompts. Whatever you put into a prompt is sent to the
      model provider you chose, exactly as any other API call would send it. If you are evaluating
      against sensitive material, that material reaches the provider.
    </p>

    <ul>
      <li>
        <strong>Credentials</strong>: encrypted <code>credential_blobs</code> in the
        <a :href="`${GH_TREE}/apps/aigateway`" target="_blank" rel="noopener">AI gateway</a>; the
        master key <code>AIGATEWAY_SECRET_KEY</code> is never stored with the data or logged.
      </li>
      <li>
        <strong>One endpoint, every provider</strong>: the engine fans out to open and closed
        providers alike through the LiteLLM-based gateway, so a fusion can mix models from different
        vendors behind a single connection.
      </li>
      <li>
        <strong>Full usage accounting</strong>: it streams an event for each node as the graph runs,
        reporting tokens, cost, and latency, so you can watch a run as it happens.
      </li>
    </ul>

    <h2>Running one</h2>

    <p>
      Your own engine ships in the client package, behind the <code>runtime</code> extra. Three
      commands install it, fetch the benchmark data it reads from disk, and start it:
    </p>

    <CodeBlock :code="runLocal" language="bash" />

    <p>
      That serves the engine on <code>127.0.0.1:9108</code>, alongside the gateway that holds your
      provider keys and a local leaderboard. <code>screamingface status</code> reports each of the
      three, and <code>screamingface down</code> stops them. The
      <RouterLink to="/sf-client/installation">Installation</RouterLink> guide covers the rest,
      including when a local engine needs its own web-search key.
    </p>

    <CodeBlock :code="health" language="bash" />

    <p>
      Point the Client at an engine with one call. Its default is a hosted engine, so a local one is
      always named explicitly:
    </p>

    <CodeBlock :code="point" language="python" />

    <p>
      The same engine runs three ways: <strong>bundled</strong> invisibly inside the Client and
      <RouterLink to="/learn/url4-sdk">SDK</RouterLink>, <strong>self-hosted</strong> for a team
      that wants the whole system inside its own walls, or <strong>hosted</strong> for shared,
      subsidized capacity that we run. The cloud deployment (Kubernetes Jobs, a streaming event bus,
      a Helm chart) lives in
      <a :href="`${GH_TREE}/apps/screamingface-engine`" target="_blank" rel="noopener"
        ><code>apps/screamingface-engine</code></a
      >. A local run needs none of it.
    </p>

    <blockquote>
      The engine is not a router. A router picks one model per call. The engine composes many into a
      graph. It is not open compute either: hosted capacity is subsidized for chosen cohorts, and
      self-hosting is on your own hardware.
    </blockquote>

    <h2>Where the code lives</h2>

    <ul>
      <li>
        <a :href="`${GH_TREE}/apps/screamingface-engine`" target="_blank" rel="noopener"
          ><code>apps/screamingface-engine</code></a
        >: the engine service (backend, runner, shared wire protocol).
      </li>
      <li>
        <a :href="`${GH_TREE}/packages/url4/src/url4/dag`" target="_blank" rel="noopener"
          ><code>packages/url4/…/dag</code></a
        >: the DAG executor it drives.
      </li>
      <li>
        <a :href="`${GH_TREE}/apps/aigateway`" target="_blank" rel="noopener"
          ><code>apps/aigateway</code></a
        >: the credential store and provider gateway.
      </li>
    </ul>
  </DocLayout>
</template>
