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

const signature = `class Url4(str):
    def to_python(self) -> str: ...`

const example = `line = report.candidates.only.url4
print(line.to_python())`
</script>

<template>
  <DocLayout
    title="Url4"
    description="The string value a run carries, and the editable Python it forks to."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A <code>Url4</code> is the complete expression a candidate executed: you get it as
      <code>candidate.url4</code> and on every
      <RouterLink to="/sf-client/api/leaderboards">leaderboard entry</RouterLink>. It subclasses
      <code>str</code>, so every string operation works and it compares and serializes as its own
      text. Pass one back to <RouterLink to="/sf-client/api/clients">evaluate()</RouterLink> to
      reproduce the run.
    </p>

    <Note>
      Two things share the name. The lowercase <code>url4</code> is the protocol, a text grammar
      covered on the <RouterLink to="/learn/url4">url4 concept page</RouterLink>. <code>Url4</code>
      here is the Python value the Client hands back. The
      <RouterLink to="/sf-client/guides/reproduce-and-share"
        >Reproduce &amp; share guide</RouterLink
      >
      is the how-to.
    </Note>

    <CodeBlock :code="signature" language="python" />

    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Returns</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>to_python()</code></td>
          <td><code>str</code></td>
          <td>
            Editable ScreamingFace Python for the compiled candidate or evaluation: a fork you can
            modify and re-run.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      You rarely build one by hand; when you do, <code>sf.Url4(value: str)</code> wraps a string.
      Because it is a <code>str</code>, it prints, slices, and stores like any string;
      <code>to_python()</code> is the one extra affordance.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="example" />
    </div>
  </DocLayout>
</template>
