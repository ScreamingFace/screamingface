<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import ThemedDiagram from '@/components/ui/ThemedDiagram.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const vote = `a = sf.Model("openrouter/deepseek/deepseek-v4-flash", name="a")
b = sf.Model("openrouter/google/gemini-3.5-flash-lite", name="b")
c = sf.Model("openrouter/anthropic/claude-haiku-4.5", name="c")

fusion = sf.Fusion([a, b, c], synthesizer=sf.Vote())
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)`

const mean = `def number(n, name):
    return sf.Model(
        "openrouter/google/gemini-3.5-flash-lite",
        name=name,
        prompt=f"Ignore the question. Reply with exactly the number {n} and nothing else.",
    )

a, b, c = number(1, "a"), number(2, "b"), number(6, "c")
fusion = sf.Fusion([a, b, c], synthesizer=sf.Mean(weights=[1, 1, 2]))
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
report.candidates.only.cases[0].output`
const meanOut = `'3.75'`

const pick = `def reply(answer, confidence, name):
    return sf.Model(
        "openrouter/google/gemini-3.5-flash-lite",
        name=name,
        prompt=f'Ignore the question. Reply with exactly this JSON: {{"answer": "{answer}", "confidence": {confidence}}}',
    )

members = [reply("red", 0.2, "a"), reply("green", 0.9, "b"), reply("blue", 0.5, "c")]
fusion = sf.Fusion(members, synthesizer=sf.Pick("confidence", order="max", output="answer"))
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
report.candidates.only.cases[0].output`
const pickOut = `'green'`

const judge = `judge = sf.Judge(
    "openrouter/google/gemini-3.5-flash-lite",
    returns="label",
    rubric="Pick the answer that follows every instruction.",
)
fusion = sf.Fusion([a, b], synthesizer=judge)`

const selection = `# a selection hands members to the next stage, so it sits in a Pipeline
ranked = sf.Pipeline([
    sf.Fusion([a, b, c], synthesizer=sf.Rank(2, by_signal=sf.signal("cost_usd"), order="min")),
    sf.Model("openrouter/deepseek/deepseek-v4-flash", name="final"),
])`

const answers = `case = report.candidates.only.cases[0]
[(a.member_id, a.status, a.reason) for a in case.answers()]`
const answersOut = `[('member_1', 'answered', None),
 ('member_2', 'answered', None),
 ('member_3', 'answered', None),
 ('member_1', 'answered', None)]`

const abstain = `fusion = sf.Fusion([a, b], synthesizer=sf.Vote(extract="boxed"))
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
case = report.candidates.only.cases[0]
case.abstained, case.output, report.candidates.only.score`
const abstainOut = `(True, '', 0.0)`
</script>

<template>
  <DocLayout
    title="Reducers"
    description="Deterministic and judge-based synthesizers, and the blocks they are built from."
    :navigation="navigation"
    :version="version"
  >
    <p>
      The synthesizer of a <RouterLink to="/sf-client/api/fusions">Fusion</RouterLink> can be a
      model, or a <strong>reducer</strong>: a combine step the engine runs without writing a new
      answer. A reducer reads each member's answer, picks or builds the result, and compiles to one
      combine call in the candidate's <RouterLink to="/sf-client/api/url4">url4</RouterLink>. A
      reducer is valid only as a Fusion synthesizer. Anywhere else it raises <code>TypeError</code>.
    </p>

    <Note>
      Reducers need an engine that serves the combine operators. An engine without them raises
      <code>sf.EngineCapabilityError</code> (code <code>engine_capability_missing</code>) before
      anything is spent.
    </Note>

    <div class="not-prose">
      <NbCell :count="1" :code="vote" />
    </div>

    <h2>Reducers that end a candidate</h2>

    <table>
      <thead>
        <tr>
          <th>Reducer</th>
          <th>What it returns</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            <code>sf.Vote(*, extract="last_line", normalize="text", weights=None, judge=None)</code>
          </td>
          <td>
            The first member, in author order, that holds the most common answer, as that member's
            text unchanged. <code>weights</code> is a list with one positive number per member, or
            an <code>sf.signal(...)</code>. A member with no usable value does not vote.
          </td>
        </tr>
        <tr>
          <td>
            <code>sf.Median(*, extract="last_number", select="nearest", weights=None)</code>
          </td>
          <td>
            The median of the members' numeric answers: the nearest member's text
            (<code>select="nearest"</code>), or the number itself (<code>select="value"</code>).
            <code>weights</code> takes the same values as for <code>sf.Vote</code>. With weights,
            the answer is the first value where the running weight reaches half the total, or the
            mean of that value and the next at exactly half. A member with a missing or non-positive
            weight is dropped and never the nearest member.
          </td>
        </tr>
        <tr>
          <td>
            <code>sf.Mean(*, extract="last_number", select="value", weights=None)</code>
          </td>
          <td>
            The mean of the members' numeric answers: the number (<code>select="value"</code>), or
            the text of the member nearest the mean (<code>select="nearest"</code>), where a tie
            goes to the first member in author order. <code>weights</code> takes one positive number
            per member, or <code>sf.signal(key)</code>. A member with a missing, zero, negative or
            non-number weight is dropped. The sums are exact and the one division is rounded to 34
            significant digits. Give every member the same scale for a confidence weight: the engine
            cannot tell that one member writes <code>80</code> and another <code>0.8</code>.
          </td>
        </tr>
        <tr>
          <td>
            <code>sf.Judge(model, *, returns, rubric, params=None, order="max")</code>
          </td>
          <td>
            A judge model picks one member. <code>returns="label"</code> names one member;
            <code>returns="scores"</code> scores every member. The answer is that member's text
            unchanged. <code>order="min"</code> with <code>returns="scores"</code> tells the judge
            that a lower number is a better answer, and the answer is the member with the lowest
            score; a tie goes to the first member in author order. <code>order="min"</code> with
            <code>returns="label"</code> raises <code>ValueError</code>, and
            <code>sf.Rank(by=...)</code> and <code>sf.Vote(judge=...)</code> refuse it. A reply that
            is not valid fails the case with <code>judge_reply_invalid</code>. Members reach the
            judge in author order, so a judge can favour a position.
          </td>
        </tr>
        <tr>
          <td>
            <code
              >sf.Pick(field=None, *, by_signal=None, order=None, equals=None, normalize=None,
              output=None)</code
            >
          </td>
          <td>
            The member whose JSON <code>field</code> is the largest (<code>order="max"</code>), the
            smallest (<code>"min"</code>) or equal to <code>equals</code>. Or, with
            <code>by_signal</code>, the member whose named signal is highest or lowest. The text is
            that member's own. With <code>output="answer"</code>, the answer is that top-level field
            of the winner's JSON reply instead: a string as it is, any other value as canonical
            JSON. When the field is missing, <code>null</code> or blank, or the reply is not a JSON
            object, the case abstains with the reason <code>output_missing</code>, and the next
            member is never used.
          </td>
        </tr>
        <tr>
          <td><code>sf.Merge(fields)</code></td>
          <td>
            One JSON object with exactly the declared fields. <code>fields</code> maps each name to
            a <code>sf.FieldRule</code>. A member that is not a JSON object is skipped.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      <code>sf.FieldRule</code> is built with a constructor method, never directly:
      <code>FieldRule.majority(normalize=None)</code>, <code>FieldRule.max()</code>,
      <code>FieldRule.union(normalize=None)</code>, <code>FieldRule.from_member(position)</code>
      (1-based author position), and
      <code>FieldRule.model(model, *, prompt, params=None)</code>, where a model writes the field
      from that field's values only.
    </p>

    <p>
      Three members that answer 1, 2 and 6, combined by a mean weighted <code>[1, 1, 2]</code>, give
      (1 + 2 + 12) / 4:
    </p>

    <CodeBlock :code="mean" language="python" />
    <CodeBlock :code="meanOut" language="text" />

    <p>
      With members that reply in JSON, <code>Pick</code> with <code>output="answer"</code> returns
      one field of the winner's reply:
    </p>

    <CodeBlock :code="pick" language="python" />
    <CodeBlock :code="pickOut" language="text" />

    <div class="not-prose">
      <NbCell :count="2" :code="judge" />
    </div>

    <h2>Selections that hand off</h2>

    <p>
      A selection keeps some members and passes their original texts to the next stage, so it must
      be followed by another stage of a
      <RouterLink to="/sf-client/api/pipelines">Pipeline</RouterLink>. One that ends a candidate, is
      a Fusion member, or feeds a corrective loop raises <code>ValueError</code> at compile time.
    </p>

    <table>
      <thead>
        <tr>
          <th>Selection</th>
          <th>What the next stage receives</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            <code>sf.Rank(k, *, by=None, by_field=None, by_signal=None, order="max")</code>
          </td>
          <td>
            The <code>k</code> best-scored members, best first. Give exactly one of
            <code>by</code> (a scores judge), <code>by_field</code> (a number in each member's JSON
            reply) and <code>by_signal</code>.
          </td>
        </tr>
        <tr>
          <td><code>sf.Concat(separator="\n\n---\n\n", *, label=True)</code></td>
          <td>
            Every member's text in author order, joined with visible boundaries. It makes no model
            call.
          </td>
        </tr>
        <tr>
          <td><code>sf.Filter(*, where, extract=None, judge=None)</code></td>
          <td>
            The members that pass <code>where</code>, in author order:
            <code>sf.matches(pattern)</code> or a comparison on a signal such as
            <code>sf.signal("field:x") &gt;= 0.6</code>. With
            <code>where=sf.signal("score:judge") &gt;= x</code> and
            <code>judge=sf.Judge(..., returns="scores")</code>, one judge call scores every member
            and the Filter keeps each member whose score passes. A <code>score:judge</code>
            comparison without a judge, a judge without one, a label judge or an
            <code>order="min"</code> judge raises <code>ValueError</code> before any call.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      The stage after a <code>Rank</code> or <code>Filter</code> receives one JSON object. Its
      <code>input</code> key holds the Case input, and its <code>selected</code> key holds the kept
      members as a list of <code>{"id": ..., "text": ...}</code>, best first for a Rank and in
      author order for a Filter. When nothing is kept, <code>selected</code> is <code>[]</code>.
    </p>

    <ThemedDiagram
      name="sf-client-0-1-9-reducers-selection"
      alt="Flow: the Case input goes to the members, their answers go to Rank or Filter, and the next stage receives the Case input and the kept members as one JSON object."
      caption="What the stage after Rank or Filter receives: the Case input, and the kept members as a list of id and text."
    />

    <div class="not-prose">
      <NbCell :count="3" :code="selection" />
    </div>

    <h2>Signals, extractors and the block form</h2>

    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>What it is</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>sf.signal(key)</code></td>
          <td>
            A named number on a member's answer that a reducer reads. Keys: <code>cost_usd</code>,
            <code>latency_ms</code>, <code>tokens_in</code>, <code>tokens_out</code>,
            <code>score:judge</code> and <code>field:&lt;path&gt;</code>. A missing value is
            <code>None</code>, never an error. Any other key raises <code>ValueError</code>.
          </td>
        </tr>
        <tr>
          <td><code>sf.Extract(rule, normalize=None, **args)</code></td>
          <td>
            How a member's answer is read. Rules: <code>boxed</code>, <code>last_number</code>,
            <code>field</code>, <code>regex</code>, <code>last_line</code>, <code>whole</code>,
            <code>json</code>, <code>benchmark</code>, <code>inspect_number</code>,
            <code>inspect_aime</code>. Normalizers: <code>numeric</code>, <code>text</code>,
            <code>set</code>, <code>inspect_numeric</code>, <code>identity</code>.
          </td>
        </tr>
        <tr>
          <td><code>sf.matches(pattern, *, ignore_case=False)</code></td>
          <td>
            A filter predicate: the member's text matches the regular expression. A pattern the
            engine would refuse raises <code>ValueError</code> before any spend.
          </td>
        </tr>
        <tr>
          <td><code>sf.Reduce(op, mode=None, **options)</code></td>
          <td>
            The generic block. <code>op</code> is one of <code>plurality</code>,
            <code>weighted</code>, <code>argmax</code>, <code>top_k</code>, <code>filter</code>,
            <code>pick_field</code>, <code>concat</code>, <code>median</code>, <code>mean</code>,
            <code>judge</code>, <code>merge</code> and <code>context</code>. For
            <code>median</code> and <code>mean</code>, <code>select="value"</code> returns the
            number and <code>select="nearest"</code> returns the text of the nearest member. A block
            that gives both <code>mode=</code> and <code>select=</code> raises
            <code>ValueError</code>. It compiles to the same url4 as the named form, and
            <code>Url4(...).to_python()</code>
            writes the named form back.
          </td>
        </tr>
        <tr>
          <td>
            <code
              >sf.samples(model, n, *, seeds=None, temperature=None, prompts=None,
              params=None)</code
            >
          </td>
          <td>
            <code>n</code> Models of one route that differ in an integer <code>seed</code>, so a
            vote counts <code>n</code> real answers. A route whose provider rejects
            <code>seed</code> fails before the run starts.
          </td>
        </tr>
      </tbody>
    </table>

    <h2>Reading what a reducer decided</h2>

    <p>
      <code>CaseResult.answers()</code> returns one <code>sf.Answer</code> per member in author
      order, then the computed answer of the step. An <code>Answer</code> has
      <code>member_id</code>, <code>text</code> (the member's original output, or
      <code>None</code> when it cannot be attributed), <code>raw</code>, <code>value</code>,
      <code>status</code> (<code>answered</code>, <code>abstain</code> or <code>fail</code>),
      <code>reason</code> and <code>signals</code>. A computed answer has no
      <code>member_id</code> unless a select chose one.
    </p>

    <div class="not-prose">
      <NbCell :count="4" :code="answers"><NbTextOut :text="answersOut" /></NbCell>
    </div>

    <p>
      When no member gives a usable value, the case <strong>abstains</strong>: its output is
      <code>''</code>, its score is <code>0.0</code>, and <code>case.abstained</code> is
      <code>True</code>. It does not fail, and <code>report.ok</code> stays <code>True</code>.
      <code>CandidateResult.abstained_count</code> counts them.
    </p>

    <div class="not-prose">
      <NbCell :count="5" :code="abstain"><NbTextOut :text="abstainOut" /></NbCell>
    </div>

    <p>
      <code>CaseResult.trace()</code> returns the steps in operation order as
      <code>TraceEntry</code> values of kind <code>model_call</code>, <code>extract</code> and
      <code>reduce</code>.
    </p>

    <CodeBlock
      code="[e.kind for e in case.trace()]
['model_call', 'model_call', 'model_call', 'extract', 'extract', 'extract', 'reduce']"
      language="python"
    />
  </DocLayout>
</template>
