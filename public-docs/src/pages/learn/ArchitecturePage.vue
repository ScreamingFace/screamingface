<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { storeToRefs } from 'pinia'
import DocLayout from '@/components/layout/DocLayout.vue'
import { useThemeStore } from '@/stores/themeStore'
import { learnNavigation as navigation } from '@/navigation/learn'

const { isDark } = storeToRefs(useThemeStore())

const GH = 'https://github.com/ScreamingFace/screamingface/tree/main'

const localDiagram = (dark: boolean) =>
  `/diagrams/screamingface-request-architecture-local-${dark ? 'dark' : 'light'}.svg`
const cloudDiagram = (dark: boolean) =>
  `/diagrams/screamingface-request-architecture-cloud-${dark ? 'dark' : 'light'}.svg`

const components = [
  { name: 'url4: the protocol', path: 'packages/url4' },
  { name: 'engine: the cloud service', path: 'apps/screamingface-engine' },
  { name: 'engine: the DAG executor', path: 'packages/url4/src/url4/dag' },
  { name: 'AI gateway', path: 'apps/aigateway' },
  { name: 'Client: the Python library', path: 'packages/screamingface' },
  // Studio hidden for now: { name: 'Studio: the desktop app', path: 'apps/screamingface-studio' },
  { name: 'Leaderboard', path: 'apps/scoreboard' },
]
</script>

<template>
  <DocLayout
    title="Architecture"
    description="How the pieces fit (url4 the protocol, the engine that runs it, and the surfaces you compose from) and where each one lives in the codebase."
    :navigation="navigation"
  >
    <p>
      ScreamingFace is a small stack built around one idea: describe an entire AI system as a single
      <RouterLink to="/learn/url4"><strong>url4</strong></RouterLink> expression, run it behind a
      trust boundary, and hand anyone that same expression to reproduce the result. This page shows
      how the pieces fit and where each lives in the
      <a :href="GH" target="_blank" rel="noopener">codebase</a>.
    </p>

    <h2>The layers</h2>

    <ul>
      <li>
        <RouterLink to="/learn/url4"><strong>url4: the protocol.</strong></RouterLink> One line
        naming some sources and an intent, which compiles to a typed graph of operations. It can
        fetch data, call models, run code, fan those out, and reduce the results to one answer. A
        source can itself be another url4, so expressions nest into arbitrarily large systems. This
        is the artifact everything else passes around.
      </li>
      <li>
        <RouterLink to="/learn/engine"
          ><strong>The engine: runtime and trust boundary.</strong></RouterLink
        >
        Runs a url4 expression: it schedules the graph, sends each model call out to a provider, and
        streams back tokens, cost, and the result. It holds the provider credentials, so the Client
        never sees them.
      </li>
      <li>
        <RouterLink to="/learn/ai-gateway"><strong>The AI gateway.</strong></RouterLink> A
        LiteLLM-based gateway the engine calls to reach every provider through one OpenAI-shaped
        endpoint. It stores provider credentials encrypted at rest.
      </li>
      <li>
        <RouterLink to="/sf-client"><strong>The Client.</strong></RouterLink> The Python library
        researchers use. It composes fusions and benchmarks and talks only to an engine, never to a
        provider directly.
      </li>
      <!-- Studio is hidden for now.
      <li>
        <strong>Studio.</strong> A desktop app over the same stack, for people who would rather
        click than script.
      </li>
      -->
      <li>
        <RouterLink to="/learn/leaderboard"><strong>The Leaderboard.</strong></RouterLink> Where
        results go public, after an independent re-run rather than on the submitter's word. Each
        entry keeps the url4 that produced it, so a rank can always be checked. The board itself is
        at
        <a href="https://leaderboard.screamingface.ai" target="_blank" rel="noopener"
          >leaderboard.screamingface.ai</a
        >.
      </li>
    </ul>

    <h2>How a request flows</h2>

    <p>
      A run always follows the same path. The Client compiles what you built into a url4 expression
      and sends it to an engine. The engine runs the expression as a graph, with independent nodes
      running in parallel, and sends each model call out through the AI gateway to the provider.
      Usage and results stream back as the graph runs. Replay the same expression and the whole
      system runs again.
    </p>

    <p>
      There are two ways to run, and only the engine URL changes. A <strong>local</strong> engine
      runs on your own machine, on your own keys, with its own cache, and nothing on the local path
      takes a cut.
    </p>

    <figure class="not-prose diagram">
      <img
        :src="localDiagram(isDark)"
        alt="Local request flow: the Client drives an engine on your own machine, which fans model calls out through the AI gateway to the providers you hold keys for."
      />
      <figcaption>
        <strong>Local.</strong> The Client drives an engine on your own machine; model calls fan out
        through the gateway to the providers you hold keys for.
      </figcaption>
    </figure>

    <p>
      A <strong>hosted</strong> engine, one we operate, runs the identical protocol but adds the
      <RouterLink to="/learn/caching">shared community cache</RouterLink> and subsidized compute for
      chosen cohorts, so reproducing or building on a published run is usually a cache hit rather
      than a fresh spend.
    </p>

    <figure class="not-prose diagram">
      <img
        :src="cloudDiagram(isDark)"
        alt="Cloud request flow: a hosted engine runs the same protocol; a control plane schedules the run and streams execution events back to the Client."
      />
      <figcaption>
        <strong>Cloud.</strong> A hosted engine runs the same protocol; a control plane schedules
        the run and streams execution events back.
      </figcaption>
    </figure>

    <h2>The trust boundary</h2>

    <p>
      Provider credentials live behind the engine and gateway, never in the Client. A key is handed
      to the engine once, stored encrypted (AES-256-GCM), and used to reach providers on your
      behalf. The Client keeps none. In an evaluation, the benchmark prompts go out to the models,
      but the answer keys and grading stay engine-side. That is what makes a verified result mean
      something. The credential store is the
      <a :href="`${GH}/apps/aigateway`" target="_blank" rel="noopener">AI gateway</a>'s encrypted
      <code>credential_blobs</code>; the master key (<code>AIGATEWAY_SECRET_KEY</code>) is never
      stored with the data or logged.
    </p>

    <h2>Where the code lives</h2>

    <table>
      <thead>
        <tr>
          <th>Component</th>
          <th>Path</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="c in components" :key="c.path">
          <td>{{ c.name }}</td>
          <td>
            <a :href="`${GH}/${c.path}`" target="_blank" rel="noopener"
              ><code>{{ c.path }}</code></a
            >
          </td>
        </tr>
      </tbody>
    </table>
  </DocLayout>
</template>

<style scoped>
.diagram {
  margin: 1.75rem 0;
  border: 1px solid var(--border);
  background: var(--surface);
}
.diagram img {
  display: block;
  width: 100%;
  height: auto;
  padding: var(--space-6);
}
.diagram figcaption {
  border-top: 1px solid var(--border);
  padding: var(--space-3) var(--space-5);
  font-size: var(--text-sm);
  color: var(--text-2);
}
.diagram figcaption strong {
  color: var(--text);
  font-weight: var(--weight-semibold);
}
</style>
