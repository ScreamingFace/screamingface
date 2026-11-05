<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import ThemedDiagram from '@/components/ui/ThemedDiagram.vue'
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
      <RouterLink to="/sf-client/api/pipelines"><code>sf.Pipeline</code></RouterLink
      >. Like every recipe it is frozen and holds no Client, so you can build it before connecting.
      The <RouterLink to="/sf-client/guides/fusions">Fusions guide</RouterLink> walks through
      building one.
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

    <p>
      A member marked <code>optional=True</code> (on a <code>Model</code>, a
      <code>Pipeline</code> or a <code>Fusion</code>) can fail while the run still synthesizes, as
      long as at least <code>quorum</code> members succeed. A failed optional member appears as a
      failed answer with the reason <code>missing</code> and never as a vote. A required member that
      fails fails the candidate. <code>optional</code> is only valid in a Fusion's member position.
    </p>

    <ThemedDiagram
      name="sf-client-0-1-10-fusion-quorum"
      alt="Topology: members A and B succeed and member C, optional, fails; the quorum check passes the answers that arrived to the synthesizer when enough members succeeded, and the candidate fails when the quorum is not met or a required member failed."
      caption="Which members reach the synthesizer, and where a failure stops the candidate."
    />
  </DocLayout>
</template>
