<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import NbCell from '@/components/nb/NbCell.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const pipelineSig = `sf.Pipeline(
    steps: Sequence[str | Recipe | Step],
    *,
    name: str | None = None,
    optional: bool = False,
)`

const pipelineExample = `pipeline = sf.Pipeline(
    ["openrouter/deepseek/deepseek-v4-pro", "openrouter/z-ai/glm-5.2"],
)
report = sf.evaluate(pipeline, benchmark="ifeval", limit=1)`
</script>

<template>
  <DocLayout
    title="Pipeline"
    description="Chain recipes in series, each stage refining the last."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A Pipeline is a <RouterLink to="/sf-client/api/recipes">Recipe</RouterLink> that passes one
      input through an ordered sequence of stages; each stage refines the previous stage's answer,
      and the last stage's answer is graded. Like every recipe it is frozen and holds no Client. The
      <RouterLink to="/sf-client/guides/pipelines">Pipelines guide</RouterLink> walks through
      building one.
    </p>

    <CodeBlock :code="pipelineSig" language="python" />

    <table>
      <thead>
        <tr>
          <th>Attribute</th>
          <th>Type</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>name</code></td>
          <td><code>str</code></td>
          <td>
            The pipeline's name. Inferred by joining stage names with <code>-&gt;</code> unless you
            pass one.
          </td>
        </tr>
        <tr>
          <td><code>optional</code></td>
          <td><code>bool</code></td>
          <td>
            <code>True</code> for a chain that is an optional member of a <code>sf.Fanout</code>.
            Defaults to <code>False</code>.
          </td>
        </tr>
        <tr>
          <td><code>steps</code></td>
          <td><code>tuple</code></td>
          <td>
            The ordered steps, each refining the previous answer. At least one. A fusion block shows
            as its <code>Fanout</code> and <code>Synthesize</code> steps.
          </td>
        </tr>
      </tbody>
    </table>

    <Note>
      An unnamed Pipeline nested inside another flattens into the outer pipeline's stages; a
      Pipeline you give an explicit <code>name</code> stays grouped as one stage. Naming is
      behavioral, not cosmetic: it participates in equality, so two pipelines with the same stages
      but different naming are not equal.
    </Note>

    <p>
      <code>a &gt;&gt; b</code> joins two stages and returns a Pipeline.
      <code>a &gt;&gt; b &gt;&gt; c</code> reads left to right and returns a new
      <code>sf.Pipeline</code>. See <RouterLink to="/sf-client/api/recipes">Recipe</RouterLink>.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="pipelineExample" />
    </div>
  </DocLayout>
</template>
