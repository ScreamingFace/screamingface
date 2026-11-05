<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
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
const exampleOut = `import screamingface as sf

candidate = (
    sf.Fanout([sf.Model('openrouter/google/gemini-3.5-flash-lite', name='a', params={'max_tokens': 120}), sf.Model('openrouter/google/gemini-3.5-flash-lite', name='b', params={'max_tokens': 120})])
    >> sf.Judge('openrouter/google/gemini-3.5-flash-lite', rubric='Score 10 if the answer is 2, else 1.')
    >> sf.ArgMax('score:judge')
)

report = sf.evaluate(
    candidate,
    benchmark='medxpert',
    limit=1,
)`
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
            modify and re-run. A recipe with several steps is written as a chain joined with
            <code>&gt;&gt;</code>, one step per line. It raises <code>ValueError</code> for a url4
            with the old scoring-judge template (<code
              >URL4 Candidate has an unsupported judge call</code
            >) and a url4 with an old max or min field pick (<code
              >URL4 Candidate has a pick spec this SDK version cannot rebuild</code
            >).
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
      <NbCell :count="1" :code="example"><NbTextOut :text="exampleOut" /></NbCell>
    </div>
  </DocLayout>
</template>
