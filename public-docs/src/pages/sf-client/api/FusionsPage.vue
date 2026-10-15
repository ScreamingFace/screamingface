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

const fusionSig = `sf.Fusion(
    members: Sequence[str | Recipe],
    *,
    name: str | None = None,
    synthesizer: str | Recipe | Reducer,
    quorum: int | Literal["all"] = "all",
    optional: bool = False,
)`

const fusionExample = `fusion = sf.Fusion(
    ["openrouter/deepseek/deepseek-v4-pro", "openrouter/z-ai/glm-5.2"],
    synthesizer="openrouter/moonshotai/kimi-k3",
)
report = sf.evaluate(fusion, benchmark="ifeval", limit=1)`

const quorumExample = `fusion = sf.Fusion(
    [
        sf.Model("openrouter/deepseek/deepseek-v4-flash", name="a"),
        sf.Model("openrouter/google/gemini-3.5-flash-lite", name="b"),
        sf.Model("openrouter/anthropic/claude-haiku-4.5", name="c", optional=True),
    ],
    quorum=2,
    synthesizer=sf.Vote(),
)`
</script>

<template>
  <DocLayout
    title="Fusion"
    description="Combine parallel members into one answer through a synthesizer."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A Fusion is a <RouterLink to="/sf-client/api/recipes">Recipe</RouterLink> that runs several
      members in parallel and combines their answers with an explicit synthesizer. Like every recipe
      it is frozen and holds no Client, so you can build it before connecting. The
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
            one.
          </td>
        </tr>
        <tr>
          <td><code>members</code></td>
          <td><code>tuple[Recipe, ...]</code></td>
          <td>The members that run in parallel. At least one.</td>
        </tr>
        <tr>
          <td><code>synthesizer</code></td>
          <td><code>Recipe</code></td>
          <td>
            The recipe that combines the members' answers into the single graded answer. It can also
            be a <RouterLink to="/sf-client/api/reducers">reducer</RouterLink>.
          </td>
        </tr>
        <tr>
          <td><code>quorum</code></td>
          <td><code>int | "all"</code></td>
          <td>
            How many members must succeed, checked after the members finish. <code>"all"</code>
            (the default) needs every member. <code>0</code> lets synthesis run with no successful
            member, which is only valid when every member is optional.
          </td>
        </tr>
        <tr>
          <td><code>optional</code></td>
          <td><code>bool</code></td>
          <td>
            Whether this Fusion, as a member of another Fusion, may fail without stopping that
            Fusion, as long as its quorum is met. The synthesizer itself stays required.
          </td>
        </tr>
      </tbody>
    </table>

    <Note>
      Members and the synthesizer are themselves recipes, so any of them can be a
      <code>Model</code>, another <code>Fusion</code>, or a
      <RouterLink to="/sf-client/api/pipelines">Pipeline</RouterLink>, nested in any combination.
      Only the synthesizer's final answer is graded.
    </Note>

    <div class="not-prose">
      <NbCell :count="1" :code="fusionExample" />
    </div>

    <p>
      A member marked <code>optional=True</code> (on a <code>Model</code>, a
      <code>Pipeline</code> or a <code>Fusion</code>) can fail while the run still synthesizes, as
      long as at least <code>quorum</code> members succeed. A failed optional member appears as a
      failed answer with the reason <code>missing</code> and never as a vote. A required member
      that fails fails the candidate. <code>optional</code> is only valid in a Fusion's member
      position.
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="quorumExample" />
    </div>
  </DocLayout>
</template>
