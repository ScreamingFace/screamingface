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

const fusionSig = `sf.Fanout(
    members: Sequence[str | Recipe],
    *,
    signals: Mapping[str, SignalSource] | None = None,
    quorum: int | Literal["all"] = "all",
    name: str | None = None,
    prompt: str | None = None,
) >> sf.Synthesize(
    model: str | Recipe,
    *,
    prompt: str | None = None,
)`

const fusionExample = `fusion = sf.Fanout(
    ["openrouter/deepseek/deepseek-v4-pro", "openrouter/z-ai/glm-5.2"],
) >> sf.Synthesize("openrouter/moonshotai/kimi-k3")
report = sf.evaluate(fusion, benchmark="ifeval", limit=1)`
</script>

<template>
  <DocLayout
    title="Fusion"
    description="Combine parallel members into one answer through a synthesizer."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A fusion is a <RouterLink to="/sf-client/api/recipes">Recipe</RouterLink> that runs several
      members in parallel and combines their answers with an explicit synthesizer. You build it as a
      chain: <code>sf.Fanout(members)</code> sends the question to every member, and
      <code>&gt;&gt; sf.Synthesize(model)</code> adds the synthesizer. The chain is an
      <RouterLink to="/sf-client/api/pipelines"><code>sf.Pipeline</code></RouterLink>. Like every
      recipe it is frozen and holds no Client, so you can build it before connecting. The
      <RouterLink to="/sf-client/guides/fusions">Fusions guide</RouterLink> walks through building
      one.
    </p>

    <CodeBlock :code="fusionSig" language="python" />

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
            The fusion's name. Inferred by joining member names with <code>+</code> unless you pass
            <code>name</code> to <code>sf.Fanout</code>.
          </td>
        </tr>
        <tr>
          <td><code>steps</code></td>
          <td><code>tuple</code></td>
          <td>
            The <code>Fanout</code> step, then the <code>Synthesize</code> step. The
            <code>Fanout</code> step keeps the members that run in parallel (at least one). The
            <code>Synthesize</code> step keeps the <code>model</code> that combines the members'
            answers into the single graded answer.
          </td>
        </tr>
        <tr>
          <td><code>optional</code></td>
          <td><code>bool</code></td>
          <td>
            <code>False</code>. Set it on an <code>sf.Pipeline</code> that wraps the chain, for an
            optional member.
          </td>
        </tr>
      </tbody>
    </table>

    <Note>
      Members and the synthesizer are themselves recipes, so any of them can be a
      <code>Model</code>, another fusion, or a
      <RouterLink to="/sf-client/api/pipelines">Pipeline</RouterLink>, nested in any combination.
      Only the synthesizer's final answer is graded. A reducer such as <code>sf.Vote</code> can
      close the block in place of <code>sf.Synthesize</code>.
    </Note>

    <div class="not-prose">
      <NbCell :count="1" :code="fusionExample" />
    </div>
  </DocLayout>
</template>
