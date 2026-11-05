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

fusion = sf.Fanout([a, b, c]) >> sf.Vote()
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)`

const mean = `def number(n, name):
    return sf.Model(
        "openrouter/google/gemini-3.5-flash-lite",
        name=name,
        prompt=f"Ignore the question. Reply with exactly the number {n} and nothing else.",
    )

a, b, c = number(1, "a"), number(2, "b"), number(6, "c")
fusion = sf.Fanout([a, b, c]) >> sf.Mean(weights=[1, 1, 2])
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
report.candidates.only.cases[0].output`
const meanOut = `'3.75'`

const median = `fusion = sf.Fanout([a, b, c]) >> sf.Median()
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
report.candidates.only.cases[0].output`
const medianOut = `'2'`

const argmax = `def reply(answer, confidence, name):
    return sf.Model(
        "openrouter/google/gemini-3.5-flash-lite",
        name=name,
        prompt=f'Ignore the question. Reply with exactly this JSON: {{"answer": "{answer}", "confidence": {confidence}}}',
    )

members = [reply("red", 0.2, "a"), reply("green", 0.9, "b"), reply("blue", 0.5, "c")]
fusion = sf.Fanout(members) >> sf.ArgMax("field:confidence", output="answer")
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
report.candidates.only.cases[0].output`
const argmaxOut = `'green'`

const judgePick = `judge = sf.JudgePick(
    "openrouter/google/gemini-3.5-flash-lite",
    rubric="Pick the answer that follows every instruction.",
)
fusion = sf.Fanout([a, b]) >> judge`

const scoreJudge = `fusion = (
    sf.Fanout([a, b])
    >> sf.Judge("openrouter/google/gemini-3.5-flash-lite", rubric="Score 10 if the answer is 2, else 1.")
    >> sf.ArgMax("score:judge")
)`

const selection = `# a narrow step keeps some members for the writer that follows
ranked = (
    sf.Fanout([a, b, c])
    >> sf.Rank(2, by="cost_usd", order="min")
    >> sf.Synthesize("openrouter/deepseek/deepseek-v4-flash")
)`

const gateCode = `def number(n, name):
    return sf.Model(
        "openrouter/google/gemini-3.5-flash-lite",
        name=name,
        prompt=f"Ignore the question. Reply with exactly the number {n} and nothing else.",
    )

members = [number(1, "a"), number(1, "b"), number(2, "c")]   # the vote is 2 of 3
gated = sf.Fanout(members) >> sf.Gate(
    when=sf.agreement() >= 0.7, then=sf.Vote(), otherwise="abstain"
)
report = sf.evaluate(gated, benchmark="medxpert", limit=1)
case = report.candidates.only.cases[0]
case.abstained, [(a.member_id, a.status, a.reason) for a in case.answers()][-1]`
const gateOut = `(True, (None, 'abstain', 'gate_not_met'))`

const gateOpen = `sf.Gate(when=sf.agreement() >= 0.6, then=sf.Vote(), otherwise="abstain")
# the same three members: case.output is '1'`

const verbalized = `def stated(answer, confidence, name):
    return sf.Model(
        "openrouter/google/gemini-3.5-flash-lite",
        name=name,
        prompt=f"Ignore the question. Reply with exactly: Answer: {answer}  Confidence: {confidence}",
    )

fusion = sf.Fanout(
    [stated("x", 90, "a"), stated("y", 20, "b"), stated("y", 30, "c")],
    signals={"conf": sf.Verbalized(r"Confidence: (\\d+)")},
) >> sf.Vote(weights="conf")
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
case = report.candidates.only.cases[0]
case.output, [a.signals["conf"] for a in case.answers()[:3]]`
const verbalizedOut = `('Answer: x  Confidence: 90', [90.0, 20.0, 30.0])`

const sumCode = `signals = {
    "x": sf.Verbalized(r"x: (\\d+)"),
    "y": sf.Verbalized(r"y: (\\d+)"),
    "s": sf.Sum({"x": 0.5, "y": 0.3}),
}
fusion = sf.Fanout([a, b], signals=signals) >> sf.ArgMax("s")`
const sumOut = `member 1: {'s': 2.3, 'x': 4.0, 'y': 1.0}
member 2: {'s': 3.1999999999999997, 'x': 1.0, 'y': 9.0}`

const consistency = `fusion = sf.Fanout([a, b], signals={"cons": sf.Consistency(n=3)}) >> sf.ArgMax("cons")
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
case = report.candidates.only.cases[0]
len([e for e in case.trace() if e.kind == "model_call"]), [a.signals["cons"] for a in case.answers()[:2]]`
const consistencyOut = `(8, [1.0, 1.0])`

const logprob = `sf.Fanout([a, b], signals={"lp": sf.Logprob("prob")}) >> sf.ArgMax("lp")`
const logprobOut = `failure code: logprobs_unsupported
(a member's answers: no usable value, reason no_signal, when the provider returns no log-probabilities)`

const answers = `case = report.candidates.only.cases[0]
[(a.member_id, a.status, a.reason) for a in case.answers()]`
const answersOut = `[('member_1', 'answered', None),
 ('member_2', 'answered', None),
 ('member_3', 'answered', None),
 ('member_1', 'answered', None)]`

const abstain = `fusion = sf.Fanout([a, b]) >> sf.Vote(over="boxed")
report = sf.evaluate(fusion, benchmark="medxpert", limit=1)
case = report.candidates.only.cases[0]
case.abstained, case.output, report.candidates.only.score`
const abstainOut = `(True, '', 0.0)`
</script>

<template>
  <DocLayout
    title="Reducers"
    description="The steps of a fan-out block: reducers, judges, narrow steps, a gate and declared signals."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A fusion is a chain of steps joined with <code>&gt;&gt;</code>. <code>sf.Fanout</code> sends
      the question to every member. The block ends in one <strong>reducer</strong>, a step the
      engine runs without writing a new answer, or in one <code>sf.Synthesize</code> writer, which
      is a model. A reducer reads each member's answer, picks or builds the result, and compiles to
      one combine call in the candidate's <RouterLink to="/sf-client/api/url4">url4</RouterLink>.
      The <RouterLink to="/sf-client/api/fusions">Fusions</RouterLink> reference covers
      <code>sf.Fanout</code> and <code>sf.Synthesize</code>.
    </p>

    <Note>
      Reducers need an engine that serves the combine operators, and a narrow step before a reducer
      needs an engine with the narrow step. An engine without them raises
      <code>sf.EngineCapabilityError</code> (code <code>engine_capability_missing</code>) before
      anything is spent.
    </Note>

    <div class="not-prose">
      <NbCell :count="1" :code="vote" />
    </div>

    <h2>The steps of a block</h2>

    <table>
      <thead>
        <tr>
          <th>Role</th>
          <th>Steps</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Map</td>
          <td>
            <code>sf.Fanout</code>: sends the input to every member and opens the block. It declares
            the signals that later steps read.
          </td>
        </tr>
        <tr>
          <td>Score</td>
          <td>
            <code>sf.Judge</code>: one judge call scores every member. The score is the signal
            <code>score:judge</code>.
          </td>
        </tr>
        <tr>
          <td>Narrow</td>
          <td>
            <code>sf.Rank</code>, <code>sf.Filter</code> and <code>sf.Concat</code>: keep some
            members, or join them, for the step that follows.
          </td>
        </tr>
        <tr>
          <td>End</td>
          <td>
            <code>sf.Vote</code>, <code>sf.Median</code>, <code>sf.Mean</code>,
            <code>sf.ArgMax</code>, <code>sf.ArgMin</code>, <code>sf.First</code>,
            <code>sf.Merge</code>, <code>sf.JudgePick</code>, <code>sf.Gate</code> or
            <code>sf.Synthesize</code>.
          </td>
        </tr>
      </tbody>
    </table>

    <p>The chain checks these rules, and each one raises <code>ValueError</code>:</p>

    <table>
      <thead>
        <tr>
          <th>Rule</th>
          <th>Message</th>
          <th>Raised</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>A block ends in one reducer or one <code>sf.Synthesize</code>.</td>
          <td>
            <code>the chain ends inside a sf.Fanout block: add a reducer or sf.Synthesize</code>
          </td>
          <td>When you compile or evaluate</td>
        </tr>
        <tr>
          <td>A block has at most one judge.</td>
          <td>
            <code
              >a block takes one judge: sf.Judge and sf.JudgePick use the same judge signal</code
            >
          </td>
          <td>When you build the chain</td>
        </tr>
        <tr>
          <td>A <code>sf.Judge</code> needs a step that reads <code>score:judge</code>.</td>
          <td><code>sf.Judge scores the members, but no step reads score:judge</code></td>
          <td>When you build the chain</td>
        </tr>
        <tr>
          <td>A block has at most 4 narrow steps.</td>
          <td><code>a block takes at most 4 narrow steps</code></td>
          <td>When you build the chain</td>
        </tr>
        <tr>
          <td><code>sf.Concat</code> is followed by <code>sf.Synthesize</code>.</td>
          <td><code>sf.Concat must be followed by sf.Synthesize</code></td>
          <td>When you build the chain</td>
        </tr>
        <tr>
          <td>A step reads only a signal that the <code>sf.Fanout</code> declares.</td>
          <td>
            <code
              >a step reads sf.signal('nope'), which this sf.Fanout does not declare (declared:
              none)</code
            >
          </td>
          <td>When you build the chain</td>
        </tr>
      </tbody>
    </table>

    <h2>Reducers that end a block</h2>

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
            <code>sf.Vote(*, over="last_line", normalize="text", weights=None)</code>
          </td>
          <td>
            The first member, in author order, that holds the most common answer, as that member's
            text unchanged. <code>over</code> is a rule name, <code>"field:&lt;path&gt;"</code> or
            an <code>sf.Extract(...)</code>. <code>weights</code> is a list with one positive number
            per member, or a signal key such as <code>"conf"</code>. A member with no usable value
            does not vote.
          </td>
        </tr>
        <tr>
          <td>
            <code>sf.Median(*, over="last_number", select="nearest", weights=None)</code>
          </td>
          <td>
            The median of the members' numeric answers: the nearest member's text
            (<code>select="nearest"</code>), or the number itself (<code>select="value"</code>).
            <code>weights</code> takes the same values as for <code>sf.Vote</code>. With weights,
            the answer is the first value where the running weight reaches half the total, or the
            mean of that value and the next at exactly half. A member with a missing or non-positive
            weight is dropped and is never the nearest member. Any other <code>select</code> raises
            <code>ValueError: sf.Median select must be 'nearest' or 'value'</code>.
          </td>
        </tr>
        <tr>
          <td>
            <code>sf.Mean(*, over="last_number", select="value", weights=None)</code>
          </td>
          <td>
            The mean of the members' numeric answers: the number (<code>select="value"</code>), or
            the text of the member nearest the mean (<code>select="nearest"</code>), where a tie
            goes to the first member in author order. <code>weights</code> takes one positive number
            per member, or a signal key. A member with a missing, zero, negative or non-number
            weight is dropped. The sums are exact and the one division is rounded to 34 significant
            digits. Give every member the same scale for a confidence weight: the engine cannot tell
            that one member writes <code>80</code> and another <code>0.8</code>.
          </td>
        </tr>
        <tr>
          <td><code>sf.ArgMax(by, *, output=None)</code></td>
          <td>
            The member with the highest value of one signal, as that member's text unchanged.
            <code>by</code> is a signal key: <code>cost_usd</code>, <code>latency_ms</code>,
            <code>tokens_in</code>, <code>tokens_out</code>, <code>score:judge</code>,
            <code>field:&lt;path&gt;</code> or a signal the fan-out declares. A member whose field
            is missing or is not a number is left out with the reason <code>no_signal</code>. With
            <code>output="answer"</code>, the answer is that top-level field of the winner's JSON
            reply instead: a string as it is, any other value as canonical JSON. When the field is
            missing, <code>null</code> or blank, or the reply is not a JSON object, the case
            abstains with the reason <code>output_missing</code>, and the next member is never used.
          </td>
        </tr>
        <tr>
          <td><code>sf.ArgMin(by, *, output=None)</code></td>
          <td>
            The member with the lowest value of one signal, with the same keys and
            <code>output=</code> as <code>sf.ArgMax</code>. A tie goes to the first member in author
            order. A judge rubric such as an error count reads as lower is better with
            <code>sf.Judge(...) &gt;&gt; sf.ArgMin("score:judge")</code>.
          </td>
        </tr>
        <tr>
          <td><code>sf.First(*, where, output=None)</code></td>
          <td>
            The first member, in author order, whose JSON field equals a value:
            <code>sf.First(where=sf.field("answer") == "yes")</code>.
            <code>sf.field(path, normalize=None)</code> names the field. <code>output=</code> works
            as for <code>sf.ArgMax</code>.
          </td>
        </tr>
        <tr>
          <td><code>sf.Merge(fields)</code></td>
          <td>
            One JSON object with exactly the declared fields. <code>fields</code> maps each name to
            a <code>sf.FieldRule</code>. A member that is not a JSON object is skipped.
          </td>
        </tr>
        <tr>
          <td>
            <code>sf.JudgePick(model, *, rubric, params=None)</code>
          </td>
          <td>
            A judge model names one member, and the answer is that member's text unchanged. A reply
            that is not valid fails the case with <code>judge_reply_invalid</code>. Members reach
            the judge in author order, so a judge can favour a position.
          </td>
        </tr>
        <tr>
          <td>
            <code>sf.Gate(*, when, then, otherwise="abstain", abstain_if=None)</code>
          </td>
          <td>
            Keeps the answer of <code>then</code> when <code>when</code> holds. See
            <a href="#gate">Gate</a>.
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

    <p>The same three members under <code>sf.Median()</code> return the nearest member's text:</p>

    <CodeBlock :code="median" language="python" />
    <CodeBlock :code="medianOut" language="text" />

    <p>
      With members that reply in JSON, <code>sf.ArgMax</code> with <code>output="answer"</code>
      returns one field of the winner's reply:
    </p>

    <CodeBlock :code="argmax" language="python" />
    <CodeBlock :code="argmaxOut" language="text" />

    <h2>Judges</h2>

    <table>
      <thead>
        <tr>
          <th>Step</th>
          <th>What it does</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>sf.Judge(model, *, rubric, params=None)</code></td>
          <td>
            Scores every member with one judge call. The judge replies with one JSON object with one
            finite score per member, and a later step reads the scores as
            <code>score:judge</code>: <code>sf.ArgMax("score:judge")</code>,
            <code>sf.ArgMin("score:judge")</code>, <code>sf.Rank(k, by="score:judge")</code>,
            <code>sf.Filter(where=sf.signal("score:judge") &gt;= x)</code> or a weight
            <code>sf.Vote(weights="score:judge")</code>. The rubric says which way is better.
          </td>
        </tr>
        <tr>
          <td><code>sf.JudgePick(model, *, rubric, params=None)</code></td>
          <td>A reducer: the judge names one member.</td>
        </tr>
      </tbody>
    </table>

    <div class="not-prose">
      <NbCell :count="2" :code="judgePick" />
      <NbCell :count="3" :code="scoreJudge" />
    </div>

    <p>
      A <code>sf.Judge</code> scores call uses the template <code>judge-template@2</code>, with
      <code>input=panel</code> when the fan-out has a quorum. <code>sf.JudgePick</code> keeps
      <code>judge-template@1 returns=label</code>. When a judge and the writer after it use the same
      model, the SDK warns with <code>sf.JudgeWriterWarning</code>.
    </p>

    <h2>Narrow steps</h2>

    <p>
      A narrow step keeps some members. It comes before a reducer in the same combine call, or
      before an <code>sf.Synthesize</code> writer, and a narrow step never ends a recipe. At most 4
      narrow steps fit in a block. A member that a narrow step leaves out is excluded with the
      reason <code>not_selected</code>.
    </p>

    <table>
      <thead>
        <tr>
          <th>Step</th>
          <th>What it keeps</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>sf.Rank(k, *, by, order="max")</code></td>
          <td>
            The <code>k</code> members with the highest (<code>order="max"</code>) or lowest value
            of the signal <code>by</code>, best first. <code>k</code> is 1 to 256:
            <code>sf.Rank(0, ...)</code> raises
            <code>ValueError: sf.Rank k must be between 1 and 256</code>. A member with no value for
            the signal is left out with the reason <code>no_signal</code>.
          </td>
        </tr>
        <tr>
          <td><code>sf.Filter(*, where, over=None)</code></td>
          <td>
            The members that pass <code>where</code>, in author order:
            <code>sf.matches(pattern)</code>, or a comparison on a signal such as
            <code>sf.signal("field:x") &gt;= 0.6</code>. <code>over=</code> reads the text for
            <code>sf.matches</code>, and a comparison on a signal with <code>over=</code> raises
            <code>ValueError</code>.
          </td>
        </tr>
        <tr>
          <td><code>sf.Concat(separator="\n\n---\n\n", *, label=True)</code></td>
          <td>
            Every member's text in author order, joined with visible boundaries, for the
            <code>sf.Synthesize</code> that must follow. It makes no model call.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      The <code>sf.Synthesize</code> writer after a <code>sf.Rank</code> or
      <code>sf.Filter</code> receives one JSON object. Its <code>input</code> key holds the Case
      input, and its <code>selected</code> key holds the kept members as a list of
      <code>{"id": ..., "text": ...}</code>, best first for a Rank and in author order for a Filter.
      When nothing is kept, <code>selected</code> is <code>[]</code>.
    </p>

    <ThemedDiagram
      name="sf-client-0-1-11-reducers-selection"
      alt="Flow: the Case input goes to the members, their answers go to Rank or Filter, and the writer receives the Case input and the kept members as one JSON object."
      caption="What the writer after Rank or Filter receives: the Case input, and the kept members as a list of id and text."
    />

    <div class="not-prose">
      <NbCell :count="4" :code="selection" />
    </div>

    <h2 id="gate">Gate</h2>

    <p>
      <code>sf.Gate(when=..., then=sf.Vote(...), otherwise=..., abstain_if=...)</code> keeps the
      majority answer only when a condition holds. <code>then</code> takes
      <code>sf.Vote</code> only: any other step raises
      <code>TypeError: sf.Gate then= takes sf.Vote until E4c</code>. <code>when</code> compares one
      reference with a number. The references are <code>sf.agreement()</code>, the share of the
      members that hold the vote's answer, from 0 to 1, and
      <code>sf.signal(name).chosen()</code> and <code>sf.signal(name).mean()</code> for a signal
      that the fan-out declares: the chosen member's value and the members' mean. A reference to a
      key such as <code>cost_usd</code> raises
      <code>ValueError: sf.signal('cost_usd').chosen() reads a declared signal</code>.
      <code>&gt;=</code> keeps the majority at equality. <code>otherwise</code> is
      <code>"abstain"</code>, <code>sf.JudgePick(...)</code> or <code>sf.Synthesize(...)</code>.
      <code>abstain_if=ref.between(lo, hi)</code> abstains inside a band.
    </p>

    <p>
      Three members answer 1, 1 and 2. The vote holds 2 of 3, so <code>agreement()</code> is 0.667.
      A threshold of 0.7 is not met, and the case abstains with the reason
      <code>gate_not_met</code>:
    </p>

    <div class="not-prose">
      <NbCell :count="5" :code="gateCode"><NbTextOut :text="gateOut" /></NbCell>
    </div>

    <CodeBlock :code="gateOpen" language="python" />

    <h2>Declared signals</h2>

    <p>
      A fan-out declares a named number for each member in <code>signals=</code>. A later step reads
      it by name: <code>sf.Vote(weights="conf")</code>, <code>sf.ArgMax("cons")</code>,
      <code>sf.Rank(2, by="lp")</code>. A signal key that the fan-out does not declare raises
      <code>ValueError</code> when you build the chain. <code>sf.Synthesize</code> right after
      <code>sf.Fanout</code> reads no signal, so that block refuses <code>signals=</code>.
    </p>

    <table>
      <thead>
        <tr>
          <th>Signal</th>
          <th>The value of each member</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>sf.Verbalized(pattern, *, ignore_case=False)</code></td>
          <td>
            A number that the member states in its text: the first group of the regular expression,
            for example <code>sf.Verbalized(r"Confidence: (\d+)")</code>.
          </td>
        </tr>
        <tr>
          <td><code>sf.Logprob(form)</code></td>
          <td>
            The token log-probability of the reply: <code>"mean"</code>, <code>"sum"</code> or
            <code>"prob"</code>. OpenRouter models only.
          </td>
        </tr>
        <tr>
          <td><code>sf.Entropy(*, top_logprobs=5)</code></td>
          <td>The mean token entropy of the reply, in nats. OpenRouter models only.</td>
        </tr>
        <tr>
          <td><code>sf.Consistency(n, *, temperature=1.0)</code></td>
          <td>
            The share of <code>n</code> more answers, at distinct fixed seeds and the stated
            temperature, that agree with the member's answer. Each member answers
            <code>n</code> more times, so the run makes <code>n</code> more model calls per member.
          </td>
        </tr>
        <tr>
          <td><code>sf.Sum(coefficients)</code></td>
          <td>
            A fixed linear sum of other declared signals of the same fan-out:
            <code>sf.Sum({"x": 0.5, "y": 0.3})</code> gives <code>0.5 × x + 0.3 × y</code>. Each
            component is another declared name and not another sum. An undeclared name raises
            <code>ValueError: sf.Sum 's' adds 'x', which this sf.Fanout does not declare</code>.
          </td>
        </tr>
        <tr>
          <td><code>sf.signal(key)</code></td>
          <td>
            A reference to a signal on a member's answer. Keys: <code>cost_usd</code>,
            <code>latency_ms</code>, <code>tokens_in</code>, <code>tokens_out</code>,
            <code>score:judge</code>, <code>field:&lt;path&gt;</code> and the declared names. A
            missing value is <code>None</code>. A <code>by=</code> or <code>weights=</code> takes
            the key as a string.
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      A vote weighted by the confidence that each member states. The member that answers
      <code>x</code> at 90 outweighs the two that answer <code>y</code> at 20 and 30:
    </p>

    <div class="not-prose">
      <NbCell :count="6" :code="verbalized"><NbTextOut :text="verbalizedOut" /></NbCell>
    </div>

    <p>A sum of two declared signals, with the value that each member got:</p>

    <CodeBlock :code="sumCode" language="python" />
    <CodeBlock :code="sumOut" language="text" />

    <p>
      <code>sf.Consistency(n=3)</code> with two members makes 8 model calls: 2 answers and 3 more
      for each member.
    </p>

    <div class="not-prose">
      <NbCell :count="7" :code="consistency"><NbTextOut :text="consistencyOut" /></NbCell>
    </div>

    <p>
      <code>sf.Logprob</code> and <code>sf.Entropy</code> need a model whose endpoint returns
      log-probabilities. On <code>gemini-3.5-flash-lite</code> and <code>gpt-5.5</code> through
      OpenRouter, the run fails with the code <code>logprobs_unsupported</code>. On
      <code>deepseek-v4-flash</code>, <code>qwen3.8-2.4t-a95b</code>, <code>gpt-oss-120b</code> and
      <code>llama-4-maverick</code>, each member is excluded with the reason <code>no_signal</code>,
      and the case abstains with <code>no_votes</code>. No model that was tried returned a value, so
      no printed value is shown for these two signals.
    </p>

    <CodeBlock :code="logprob" language="python" />
    <CodeBlock :code="logprobOut" language="text" />

    <h2>Extractors and predicates</h2>

    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>What it is</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>sf.Extract(rule, normalize=None, **args)</code></td>
          <td>
            How a member's answer is read. Rules: <code>boxed</code>, <code>last_number</code>,
            <code>field</code>, <code>regex</code>, <code>last_line</code>, <code>whole</code>,
            <code>json</code>, <code>benchmark</code>, <code>inspect_number</code>,
            <code>inspect_aime</code>. Normalizers: <code>numeric</code>, <code>text</code>,
            <code>set</code>, <code>inspect_numeric</code>, <code>identity</code>. A rule name,
            <code>"field:&lt;path&gt;"</code> or <code>sf.Extract(...)</code> goes in
            <code>over=</code>.
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
      <code>status</code> (<code>answered</code>, <code>abstain</code>, <code>excluded</code> or
      <code>fail</code>), <code>reason</code> and <code>signals</code>. A computed answer has no
      <code>member_id</code> unless a step chose one.
    </p>

    <div class="not-prose">
      <NbCell :count="8" :code="answers"><NbTextOut :text="answersOut" /></NbCell>
    </div>

    <p>
      When no member gives a usable value, the case <strong>abstains</strong>: its output is
      <code>''</code>, its score is <code>0.0</code>, and <code>case.abstained</code> is
      <code>True</code>. It does not fail, and <code>report.ok</code> stays <code>True</code>.
      <code>CandidateResult.abstained_count</code> counts them. The reasons seen in these runs are
      <code>no_votes</code>, <code>gate_not_met</code>, <code>output_missing</code>,
      <code>no_signal</code> and <code>missing</code>.
    </p>

    <div class="not-prose">
      <NbCell :count="9" :code="abstain"><NbTextOut :text="abstainOut" /></NbCell>
    </div>

    <p>
      <code>CaseResult.trace()</code> returns the steps in operation order as
      <code>TraceEntry</code> values of kind <code>model_call</code>, <code>extract</code> and
      <code>reduce</code>.
      <RouterLink to="/sf-client/api/candidate-result">CandidateResult</RouterLink> covers the
      combine evidence of each step.
    </p>

    <CodeBlock
      code="[e.kind for e in case.trace()]
['model_call', 'model_call', 'model_call', 'extract', 'extract', 'extract', 'reduce']"
      language="python"
    />
  </DocLayout>
</template>
