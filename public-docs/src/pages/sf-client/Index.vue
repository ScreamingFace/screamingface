<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { storeToRefs } from 'pinia'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import { SF_ENGINE_URL } from '@/lib/engine'
import { useThemeStore } from '@/stores/themeStore'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const { isDark } = storeToRefs(useThemeStore())

const localDiagram = (dark: boolean) =>
  `/diagrams/screamingface-request-architecture-local-${dark ? 'dark' : 'light'}.svg`

// The smallest complete run: name the engine, compose a Fusion, evaluate it
// beside its own member, read both scores. Every name here is shipped API.
const smallestExample = `import screamingface as sf

sf.configure(engine_url="${SF_ENGINE_URL}")

gpt = sf.Model("openrouter/openai/gpt-5.5")
flash = sf.Model("openrouter/google/gemini-3-flash-preview")
fusion = sf.Fusion([gpt, flash], synthesizer="openrouter/openai/gpt-5.5")

# Score the solo model beside the fusion, on the same cases.
report = sf.evaluate([gpt, fusion], benchmark="ifeval", limit=3)
{c.name: c.score for c in report.candidates}`

const smallestExampleOut = `{'gpt-5.5': 0.667, 'gpt-5.5+gemini-3-flash-preview': 1.0}`
</script>

<template>
  <DocLayout
    title="Overview"
    description="Open infrastructure for composing and measuring model fusions, and the smallest end-to-end run."
    :navigation="navigation"
    :version="version"
  >
    <p>
      ScreamingFace is open, Python-first infrastructure for composing model ensembles (it calls
      them
      <strong>fusions</strong>) and measuring them under grading you do not control. It is built
      around one approach: advancing capability by composition, combining existing models rather
      than training new ones. You assemble a fusion from providers you hold keys for, evaluate it
      against a research benchmark, and read back its score next to its cost.
    </p>

    <p>
      A fusion can score higher than any single model within it. A reproduction of the
      <strong>DRACO</strong> deep-research benchmark put the best fusion at
      <strong>68.6%</strong> against <strong>60.2%</strong> for the best single model (<a
        href="https://andrewtrask.substack.com/p/6-weeks-ago-frontier-ai-labs-lost"
        target="_blank"
        rel="noopener"
        >published results</a
      >), an effect that recurs across the ensemble literature, for instance in
      <a href="https://openreview.net/forum?id=XSIYfTm2h7" target="_blank" rel="noopener"
        ><em>Beyond Leaderboards: Tokenomics of Agentic Small Language Model Ensembles</em></a
      >
      (Skurikhin et al., Los Alamos). The effect itself is not new. What the Client adds is the
      infrastructure around it: held-out grading, a reproducible record of every run, and cost
      reported next to accuracy.
    </p>

    <h2>What the Client provides</h2>

    <ul>
      <li>
        <strong>Held-out grading.</strong> Benchmark answer keys, rubrics, and judges live on the
        engine and are never returned to the Client, so a score does not rest on trusting whoever
        produced it.
      </li>
      <li>
        <strong>A reproducible artifact for every run.</strong> Each evaluation compiles to one
        <RouterLink to="/learn/url4">url4</RouterLink> expression recording the models, their
        parameters, and the benchmark revision that was used. Anyone holding it can run the same
        evaluation.
      </li>
      <li>
        <strong>Your own providers.</strong> You connect the API keys you already have, and calls
        are billed to your own accounts rather than resold to you.
      </li>
      <li>
        <strong>Caching.</strong> Every model response is
        <RouterLink to="/learn/caching">cached</RouterLink> against its exact request, so comparing
        many fusion candidates over one benchmark is billed only for the calls that have not been
        made before. A model shared between two candidates answers once, and swapping a single
        member re-uses what the others already produced.
      </li>
      <li>
        <strong>Cost reported alongside accuracy.</strong> Tokens, spend, and duration stream while
        the run is in progress and are totalled per model and per fusion, so the price of a gain is
        visible at the same time as the gain.
      </li>
      <li>
        <strong>Reusable recipes.</strong> Recipes published to the leaderboard can be imported,
        modified, and re-run, and on a hosted engine the cache is shared across the community, so
        repeating someone else's run usually costs a fraction of the original.
      </li>
    </ul>

    <h2>How it works</h2>

    <p>
      The Client never calls a model provider itself. It compiles your recipe into one
      <strong>url4</strong> expression and hands that to an
      <RouterLink to="/learn/engine">engine</RouterLink>, which holds the credentials and the
      benchmark answer keys and does the grading.
    </p>

    <p>
      A <strong>url4</strong> is a single-line expression, following a fixed grammar and protocol,
      that describes a composed system: which models take part, how their answers are combined, and
      what each one is asked to do. It is both the record of what ran and the instruction for
      running it again, so a published result carries its own method instead of describing it in
      prose.
    </p>

    <p>
      From there the engine resolves the expression, calls each model, applies the benchmark's
      grader, and streams usage back while the run proceeds. What returns is the set of scores, any
      failures, and the total cost. Because the url4 travels with the result, someone else can
      repeat the evaluation and compare what they get against what you reported.
    </p>

    <figure class="not-prose diagram">
      <img
        :src="localDiagram(isDark)"
        alt="Local request flow: the Client compiles your recipe into one url4 expression and hands it to an engine on your own machine, which fans each model call out through the AI gateway to the providers you hold keys for and streams scores and cost back."
      />
      <figcaption>
        <strong>The local flow.</strong> The Client compiles your recipe into one url4 expression
        and hands it to an engine on your own machine; the engine fans model calls out through the
        gateway to the providers you hold keys for, then streams scores and cost back.
      </figcaption>
    </figure>

    <h2>Two ways to run</h2>

    <p>You point the Client at an engine in one of two places.</p>

    <ul>
      <li>
        <strong>A local engine</strong> ships with the toolkit and runs on your own machine, using
        your keys and its own cache. Nothing is hosted and no third party sits between you and your
        providers, but the cache starts empty and you pay for the compute.
      </li>
      <li>
        <strong>A hosted engine</strong> runs the same software as a service and adds the shared
        community cache, on compute we provide once you log in. It does not take your own provider
        keys; bring-your-own-key is the local path, and your prompts run on an engine we operate.
      </li>
    </ul>

    <p>
      The code you write is identical either way and only the engine URL differs, so the decision is
      reversible. The <RouterLink to="/sf-client/installation">Installation</RouterLink> guide
      covers both.
    </p>

    <h2>The smallest example</h2>

    <div class="not-prose">
      <NbCell :count="1" :code="smallestExample"><NbTextOut :text="smallestExampleOut" /></NbCell>
    </div>

    <p>
      <code>score</code> is each candidate's accuracy over the same cases, where higher is better.
      The report carries no baseline or gain field, because the comparison is simply that you ran
      the solo model and the fusion in one call and can read both numbers.
    </p>
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
