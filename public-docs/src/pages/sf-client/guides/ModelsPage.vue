<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const basic = `import screamingface as sf

opus = sf.Model("openrouter/anthropic/claude-opus-4.8")
opus`
const basicOut = `Model('openrouter/anthropic/claude-opus-4.8')`

const named = `sf.Model("openrouter/openai/gpt-5.5", name="gpt-run-2")`
const namedOut = `Model('openrouter/openai/gpt-5.5', name='gpt-run-2')`

const policy = `sf.Model(
    "openrouter/openai/gpt-5.5",
    prompt="Answer concisely.",
    params={"reasoning": "high"},
)`
const policyOut = `Model('openrouter/openai/gpt-5.5', prompt='Answer concisely.', params={'reasoning': 'high'})`

const listing = `sf.models.list()`
const listingOut = `ModelInfo('anthropic/claude-opus-4-8', provider='anthropic', parameters=9, tools=2)
ModelInfo('anthropic/claude-haiku-4-5', provider='anthropic', parameters=9, tools=2)
ModelInfo('codex/gpt-5.5', provider='codex', parameters=4, tools=1)
ModelInfo('gemini-cli/gemini-2.5-pro', provider='gemini-cli', parameters=4, tools=1)
ModelInfo('huggingface/deepseek-ai/DeepSeek-R1:novita', provider='huggingface', parameters=7, tools=0)
ModelInfo('openrouter/anthropic/claude-opus-4.8', provider='openrouter', parameters=12, tools=2)
ModelInfo('openrouter/openai/gpt-5.5', provider='openrouter', parameters=12, tools=2)
ModelInfo('openrouter/google/gemini-3.1-pro-preview', provider='openrouter', parameters=12, tools=2)
…   # 29 entries across 6 providers on this engine`

const details = `gpt = sf.models.get("openrouter/openai/gpt-5.5")
gpt.parameters["reasoning"].enabled, "web_search" in gpt.tools`
const detailsOut = `(True, True)`

const discover = `gpt = sf.models.get("openrouter/openai/gpt-5.5")

# What can I configure on this route?
len(gpt.parameters), sorted(gpt.parameters)[:4]`
const discoverOut = `(12, ['frequency_penalty', 'max_tokens', 'presence_penalty', 'reasoning'])`

const inspect = `temp = gpt.parameters["temperature"]

# Each parameter carries a schema: type, bounds, and any fixed value set.
temp.schema.type, temp.schema.minimum, temp.schema.maximum, temp.enabled`
const inspectOut = `('number', 0.0, 2.0, True)`
</script>

<template>
  <DocLayout
    title="Models"
    description="Select a model route and set the answer policy a candidate owns."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A <strong>Model</strong> names one model route and, optionally, the answer policy that route
      should use. It is the smallest thing you can evaluate, and the building block every
      <RouterLink to="/sf-client/guides/fusions">Fusion</RouterLink> is made of.
    </p>

    <p>
      A Model is <strong>immutable</strong>. Constructing one makes no request and needs no
      connection: it is a value describing what to ask for. Nothing happens until you pass it to an
      evaluation.
    </p>

    <h2>What you can do with it</h2>

    <ul>
      <li>Select a route to evaluate.</li>
      <li>Name a Model so two samples of the same route stay distinguishable.</li>
      <li>Override the answer prompt and generation parameters.</li>
      <li>List the routes this engine can actually reach.</li>
      <li>Read one route's profile to see which parameters and tools it supports.</li>
    </ul>

    <h2>Main APIs</h2>

    <table>
      <thead>
        <tr>
          <th>API</th>
          <th>What it does</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>sf.Model(model, *, name=None, prompt=None, params=None)</code></td>
          <td>
            Selects one model route as the smallest thing you can evaluate, optionally overriding
            its answer policy with a prompt and generation parameters.
          </td>
        </tr>
        <tr>
          <td><code>sf.models.list()</code></td>
          <td>
            Lists the routes this engine can reach as <code>sf.ModelInfo</code> values, spanning
            every provider the engine knows.
          </td>
        </tr>
        <tr>
          <td><code>sf.models.get(model_id)</code></td>
          <td>
            Returns one route's <code>sf.ModelDetails</code> profile: which parameters and tools it
            supports, and whether the profile is current.
          </td>
        </tr>
        <tr>
          <td>
            <code>.name</code> · <code>.model</code> · <code>.prompt</code> · <code>.params</code>
          </td>
          <td>Read back what a Model resolved to, including its inferred or explicit name.</td>
        </tr>
      </tbody>
    </table>

    <h2>How to</h2>

    <h3>1 · Select a route</h3>

    <p>
      The route is the only required argument. The Model's <code>name</code> is inferred from its
      last segment, which is what appears in a report.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="basic"><NbTextOut :text="basicOut" /></NbCell>
    </div>

    <h3>2 · Name an independent sample</h3>

    <p>
      Two Models on the same route with the same policy are the <em>same</em> candidate:
      <RouterLink to="/learn/engine">the engine</RouterLink> deduplicates them by content inside one
      compiled graph. An explicit <code>name</code> is how you say you meant two independent
      samples, and it is the name the report uses.
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="named"><NbTextOut :text="namedOut" /></NbCell>
    </div>

    <h3>3 · Override the answer policy</h3>

    <p>
      The SDK supplies a general answer prompt, so a bare Model works. When an experiment needs
      something specific, <code>prompt</code> and <code>params</code> replace it.
    </p>

    <div class="not-prose">
      <NbCell :count="3" :code="policy"><NbTextOut :text="policyOut" /></NbCell>
    </div>

    <p>
      These are <strong>candidate-owned</strong> settings: they change how your candidate answers,
      and they can never touch benchmark-owned cases, judge models, grading or aggregation. That
      separation is what keeps two candidates comparable on the same benchmark. Whatever you set is
      resolved and embedded in the run's <RouterLink to="/learn/url4">url4</RouterLink>, so a report
      records the policy that actually ran.
    </p>

    <h3>4 · See what the engine can reach</h3>

    <div class="not-prose">
      <NbCell :count="4" :code="listing"><NbTextOut :text="listingOut" /></NbCell>
    </div>

    <p>
      Two things to note. The catalogue spans <strong>every provider the engine knows</strong>, not
      only the ones you have connected: a route you have no credential for will fail at evaluation,
      not here. And ID shapes differ per provider: <code>anthropic/claude-opus-4-8</code> against
      <code>openrouter/anthropic/claude-opus-4.8</code>. Copy the <code>id</code> rather than
      retyping it.
    </p>

    <blockquote>
      <strong>The catalogue is fixed for now.</strong> The engine does not yet discover models
      automatically, so only the routes listed here can be used to build fusions. A model missing
      from the list can't be added from the Client. Automatic discovery is work in progress.
    </blockquote>

    <h3>5 · Check that a route accepts your policy</h3>

    <p>
      <code>sf.models.get(id)</code> returns the fuller <code>sf.ModelDetails</code> profile for one
      route: each parameter with its schema and whether the gateway currently projects it, the tools
      and transports it supports, and whether the profile is stale. Consulting it is how you learn
      that <code>params={"reasoning": "high"}</code> will be honoured before a run spends anything.
    </p>

    <div class="not-prose">
      <NbCell :count="5" :code="details"><NbTextOut :text="detailsOut" /></NbCell>
    </div>

    <h3>6 · Discover a route's parameters</h3>

    <p>
      The same <code>ModelDetails</code> profile is also how you find out <em>what</em> a route lets
      you configure. <code>details.parameters</code> is a mapping keyed by parameter name, so
      listing its keys enumerates every knob the route exposes.
    </p>

    <div class="not-prose">
      <NbCell :count="6" :code="discover"><NbTextOut :text="discoverOut" /></NbCell>
    </div>

    <p>
      Each value is an <code>sf.ModelParameter</code>. Its <code>schema</code> gives the type and
      the bounds the gateway enforces — a numeric <code>minimum</code>/<code>maximum</code>, an
      <code>enum</code> of allowed values, a <code>max_length</code>, and so on — while
      <code>enabled</code> says whether the gateway currently honours it. Reading the schema tells
      you a value's legal range before you set it in <code>params</code>.
    </p>

    <div class="not-prose">
      <NbCell :count="7" :code="inspect"><NbTextOut :text="inspectOut" /></NbCell>
    </div>

    <p>
      A parameter that isn't listed isn't configurable on that route: setting it in
      <code>params</code> is refused at pre-flight rather than silently dropped, so a typo costs you
      nothing.
    </p>

    <h2>Links</h2>

    <ul>
      <li>
        <a
          href="https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/00_quickstart.ipynb"
          target="_blank"
          rel="noopener"
          >Companion notebook: <code>00_quickstart.ipynb</code></a
        >
      </li>
    </ul>
  </DocLayout>
</template>
