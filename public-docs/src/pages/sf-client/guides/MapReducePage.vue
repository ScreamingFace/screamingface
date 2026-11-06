<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const map = `import screamingface as sf

a = sf.Model("openrouter/anthropic/claude-opus-4.8")
b = sf.Model("openrouter/openai/gpt-5.5")
c = sf.Model("openrouter/google/gemini-3.5-pro")

# Dispatch: send one question to every member, in parallel.
panel = sf.Fanout([a, b, c])
panel`
const mapOut = `Fanout(['openrouter/anthropic/claude-opus-4.8', 'openrouter/openai/gpt-5.5', 'openrouter/google/gemini-3.5-pro'])`

const reduce = `# Reduce: collapse the panel to one answer with a rule.
agree = sf.Fanout([a, b, c]) >> sf.Vote()
agree`
const reduceOut = `Fanout([...]) >> Vote()`

const weigh = `# A signal read as a weight: confidence-weighted vote.
signals = {"conf": sf.Verbalized(r"Confidence: (\\d+)")}
weighted = sf.Fanout([a, b, c], signals=signals) >> sf.Vote(weights="conf")
weighted`
const weighOut = `Fanout([...], signals={'conf': Verbalized('Confidence: (\\\\d+)')}) >> Vote(weights='conf')`

const narrow = `# The same signal read to filter: keep the two most confident, then write.
best = (
    sf.Fanout([a, b, c], signals={"conf": sf.Verbalized(r"Confidence: (\\d+)")})
    >> sf.Rank(2, by="conf")
    >> sf.Synthesize("openrouter/anthropic/claude-opus-4.8")
)
best`
const narrowOut = `Fanout([...], signals={'conf': Verbalized('Confidence: (\\\\d+)')}) >> Rank(2, by='conf') >> Synthesize('openrouter/anthropic/claude-opus-4.8')`

const worked = `import screamingface as sf

a = sf.Model("openrouter/anthropic/claude-opus-4.8")
b = sf.Model("openrouter/openai/gpt-5.5")
c = sf.Model("openrouter/google/gemini-3.5-pro")

# dispatch → map → reduce, as one recipe.
fusion = (
    sf.Fanout([a, b, c])                                   # dispatch: three answers
    >> sf.Judge(                                           # map:      a score on each
        "openrouter/google/gemini-3.5-flash-lite",
        rubric="Score 10 if the answer is fully correct, else lower.",
    )
    >> sf.ArgMax("score:judge")                            # reduce:   keep the best-scored answer
)

report = sf.evaluate(fusion, benchmark="ifeval", limit=20)
report.score`

const narrowUpgrade = `# Add a selector to keep the top two before a writer synthesizes.
fusion = (
    sf.Fanout([a, b, c])
    >> sf.Judge(
        "openrouter/google/gemini-3.5-flash-lite",
        rubric="Score 10 if the answer is fully correct, else lower.",
    )
    >> sf.Rank(2, by="score:judge")                        # filter: keep the top two
    >> sf.Synthesize("openrouter/anthropic/claude-opus-4.8")  # reduce: write from just those two
)`

const examples = `# Keep the single most confident answer.
sf.Fanout([a, b, c], signals={"conf": sf.Verbalized(r"Confidence: (\\d+)")}) >> sf.ArgMax("conf")

# Average the members' numbers, weighted by that same confidence.
sf.Fanout([a, b, c], signals={"conf": sf.Verbalized(r"Confidence: (\\d+)")}) >> sf.Mean(weights="conf")

# Self-consistency: rerun each member three times, keep the most stable.
sf.Fanout([a, b], signals={"cons": sf.Consistency(n=3)}) >> sf.ArgMax("cons")

# Trust the model that was most certain, by answer log-probability.
sf.Fanout([a, b], signals={"lp": sf.Logprob("prob")}) >> sf.ArgMax("lp")

# Among the two cheapest answers, take the majority.
sf.Fanout([a, b, c]) >> sf.Rank(2, by="cost_usd", order="min") >> sf.Vote()`</script>

<template>
  <DocLayout
    title="Map-reduce for fusions"
    description="A fusion can dispatch a question to its member models, then map, filter and reduce what comes back into the one answer a benchmark grades. This page covers each stage and the signals that pass between them."
    :navigation="navigation"
    :version="version"
  >
    <p>
      In ScreamingFace, every <RouterLink to="/sf-client/guides/fusions">fusion</RouterLink> can be
      constructed as a map-reduce pipeline. A <strong>dispatch</strong> stage puts the question to the
      member models. A
      <strong>reduce</strong> stage turns what comes back into a single answer, and that answer is
      what the benchmark grades. Two optional stages can sit in between: <strong>map</strong>
      attaches a number, called a <strong>signal</strong>, to each answer independently, and
      <strong>filter</strong> drops answers before the reducer sees them.
    </p>

    <p>
      What varies most between fusions is the dispatch. The simplest, <code>sf.Fanout</code>,
      broadcasts the question to every member in parallel and hands on a <strong>panel</strong>: N
      answers, one per member. Other strategies route the question to some members, cascade through
      them in order, or
      <RouterLink to="/sf-client/guides/pipelines">chain them as a pipeline</RouterLink>, and what
      they hand on depends on the strategy.
    </p>

    <p>
      You write the stages left to right and join them with <code>&gt;&gt;</code>. A fusion starts
      with a dispatch (or a solo <RouterLink to="/sf-client/guides/models">Model</RouterLink>) and
      ends with a reducer; anything in between is optional.
    </p>

    <figure class="not-prose" style="margin: var(--space-8) 0">
      <svg
        class="dg"
        viewBox="0 0 860 186"
        role="img"
        aria-label="A fusion as a chain. sf.Fanout maps the question to three members and passes on three answers. An optional mapper scores each answer. An optional selector filters to the top two. A reducer collapses them to one answer, which the benchmark grades."
      >
        <defs>
          <marker
            id="mr-a"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="6"
            markerHeight="6"
            orient="auto"
          >
            <path d="M0 0 L8 4 L0 8 z" style="fill: var(--text-2)" />
          </marker>
        </defs>
        <g class="edge" marker-end="url(#mr-a)">
          <path d="M150 115.0 H196" />
          <path d="M346 115.0 H392" />
          <path d="M542 115.0 H588" />
          <path d="M738 115.0 H784" />
        </g>
        <rect class="box map" x="16" y="92" width="134" height="46" />
        <rect class="box enrich optional" x="212" y="92" width="134" height="46" />
        <rect class="box narrow optional" x="408" y="92" width="134" height="46" />
        <rect class="box reduce" x="604" y="92" width="134" height="46" />
        <rect class="box graded" x="784" y="92" width="76" height="46" />
        <g class="lbl" text-anchor="middle">
          <text x="83" y="119.5">sf.Fanout</text>
          <text x="279" y="119.5">mapper</text>
          <text x="475" y="119.5">selector</text>
          <text x="671" y="119.5">reducer</text>
          <text x="822" y="119.5">graded</text>
        </g>
        <g text-anchor="middle" style="fill: var(--text-2); font-size: 12.5px">
          <text x="83" y="34">3 answers</text>
          <text x="279" y="34">3 answers, scored</text>
          <text x="475" y="34">top 2 kept</text>
          <text x="671" y="34">1 answer</text>
        </g>
        <!-- dispatch: three plain answers -->
        <g>
          <rect x="28.0" y="46" width="32" height="18" rx="3" style="fill:var(--surface);stroke:var(--data-azure-500);stroke-width:1.5" />
          <text x="44.0" y="59" text-anchor="middle" style="fill:var(--text);font-size:12px">a</text>
        </g>
        <g>
          <rect x="67.0" y="46" width="32" height="18" rx="3" style="fill:var(--surface);stroke:var(--data-azure-500);stroke-width:1.5" />
          <text x="83.0" y="59" text-anchor="middle" style="fill:var(--text);font-size:12px">b</text>
        </g>
        <g>
          <rect x="106.0" y="46" width="32" height="18" rx="3" style="fill:var(--surface);stroke:var(--data-azure-500);stroke-width:1.5" />
          <text x="122.0" y="59" text-anchor="middle" style="fill:var(--text);font-size:12px">c</text>
        </g>
        <!-- map: each answer scored (teal bar) -->
        <g>
          <rect x="224.0" y="46" width="32" height="18" rx="3" style="fill:var(--surface);stroke:var(--data-teal-500);stroke-width:1.5" />
          <text x="240.0" y="59" text-anchor="middle" style="fill:var(--text);font-size:12px">a</text>
          <rect x="224.0" y="68" width="32" height="3.5" rx="1.5" style="fill:var(--data-teal-500)" />
        </g>
        <g>
          <rect x="263.0" y="46" width="32" height="18" rx="3" style="fill:var(--surface);stroke:var(--data-teal-500);stroke-width:1.5" />
          <text x="279.0" y="59" text-anchor="middle" style="fill:var(--text);font-size:12px">b</text>
          <rect x="263.0" y="68" width="13" height="3.5" rx="1.5" style="fill:var(--data-teal-500)" />
        </g>
        <g>
          <rect x="302.0" y="46" width="32" height="18" rx="3" style="fill:var(--surface);stroke:var(--data-teal-500);stroke-width:1.5" />
          <text x="318.0" y="59" text-anchor="middle" style="fill:var(--text);font-size:12px">c</text>
          <rect x="302.0" y="68" width="23" height="3.5" rx="1.5" style="fill:var(--data-teal-500)" />
        </g>
        <!-- filter: top two kept, b dropped -->
        <g>
          <rect x="420.0" y="46" width="32" height="18" rx="3" style="fill:var(--surface);stroke:var(--data-orange-500);stroke-width:1.5" />
          <text x="436.0" y="59" text-anchor="middle" style="fill:var(--text);font-size:12px">a</text>
          <rect x="420.0" y="68" width="32" height="3.5" rx="1.5" style="fill:var(--data-teal-500)" />
        </g>
        <g opacity="0.3">
          <rect x="459.0" y="46" width="32" height="18" rx="3" style="fill:var(--surface);stroke:var(--data-orange-500);stroke-width:1.5" stroke-dasharray="3 2" />
          <text x="475.0" y="59" text-anchor="middle" style="fill:var(--text);font-size:12px">b</text>
          <rect x="459.0" y="68" width="13" height="3.5" rx="1.5" style="fill:var(--data-teal-500)" />
        </g>
        <g>
          <rect x="498.0" y="46" width="32" height="18" rx="3" style="fill:var(--surface);stroke:var(--data-orange-500);stroke-width:1.5" />
          <text x="514.0" y="59" text-anchor="middle" style="fill:var(--text);font-size:12px">c</text>
          <rect x="498.0" y="68" width="23" height="3.5" rx="1.5" style="fill:var(--data-teal-500)" />
        </g>
        <!-- reduce: one final answer -->
        <g>
          <rect x="655.0" y="46" width="32" height="18" rx="3" style="fill:var(--data-green-500);stroke:var(--data-green-500);stroke-width:1.5" fill-opacity="0.18" />
        </g>
        <g class="sub" text-anchor="middle" style="font-size: 12px">
          <a href="#dispatch"><text x="83" y="162">dispatch</text></a>
          <a href="#map"><text x="279" y="162">map · optional</text></a>
          <a href="#filter"><text x="475" y="162">filter · optional</text></a>
          <a href="#reduce"><text x="671" y="162">reduce</text></a>
        </g>
      </svg>
    </figure>

    <h2>The four stages at a glance</h2>

    <p>
      In the fusions on this page, every step is one of four kinds, and each kind has a fixed
      contract with the panel:
    </p>

    <table>
      <thead>
        <tr>
          <th>Stage</th>
          <th>Step</th>
          <th>Panel in → out</th>
          <th>Required</th>
          <th>Examples</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Dispatch</td>
          <td><code>sf.Fanout</code></td>
          <td>question → N answers</td>
          <td>Yes, always first</td>
          <td><code>sf.Fanout([a, b, c])</code></td>
        </tr>
        <tr>
          <td>Map</td>
          <td>mapper</td>
          <td>N → N, plus a signal on each</td>
          <td>No</td>
          <td><code>sf.Judge</code></td>
        </tr>
        <tr>
          <td>Filter</td>
          <td>selector</td>
          <td>N → N or fewer</td>
          <td>No</td>
          <td><code>sf.Rank</code>, <code>sf.Filter</code></td>
        </tr>
        <tr>
          <td>Reduce</td>
          <td>reducer</td>
          <td>N → 1 answer</td>
          <td>Yes, always last</td>
          <td><code>sf.Vote</code>, <code>sf.ArgMax</code>, <code>sf.Synthesize</code></td>
        </tr>
      </tbody>
    </table>

    <p>
      Mappers and selectors take a panel and return a panel, so you can stack them between the
      dispatch and the reducer.
    </p>

    <h2 id="dispatch">Dispatch: fan out to a panel</h2>

    <p>
      <code>sf.Fanout(members)</code> is the simplest dispatch: it broadcasts the question to every
      member in parallel and returns a <strong>panel</strong> with one answer per member. Nothing is
      scored or chosen yet. Members are usually <code>sf.Model</code> instances, each identified by a
      provider-prefixed model id (see <RouterLink to="/sf-client/guides/models">Models</RouterLink>);
      since fusions nest, a member can also be another fusion. The fan-out is also where you declare
      signals measured from each member's own response, with <code>signals=</code>, covered under Map
      below.
    </p>

    <p>
      On its own, a fan-out is a valid expression but not a runnable fusion. It opens a chain that a
      reducer has to close:
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="map"><NbTextOut :text="mapOut" /></NbCell>
    </div>

    <h2 id="reduce">Reduce: collapse to one answer</h2>

    <p>
      A <strong>reducer</strong> reads the whole panel and returns one answer. It is
      <strong>terminal</strong>: nothing can follow it, and its output is what the benchmark grades.
      The simplest is <code>sf.Vote()</code>, which returns the answer most members agree on:
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="reduce"><NbTextOut :text="reduceOut" /></NbCell>
    </div>

    <p>
      That is a complete, runnable fusion. Everything after this section is optional; reach for it
      when plain agreement isn't enough.
    </p>

    <h3>Choosing a reducer</h3>

    <p>
      Reducers differ in where the final answer comes from: copied verbatim from one member, computed
      from the members' answers, or newly written by a model. Several decide using a signal, the
      number covered in the next section. The
      <RouterLink to="/sf-client/api/reducers">Reducers reference</RouterLink> has full signatures.
    </p>

    <table>
      <thead>
        <tr>
          <th>Reducer</th>
          <th>What it returns</th>
          <th>Final answer is</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>sf.Vote()</code></td>
          <td>
            The answer most members agree on. Pass <code>weights=</code> to count some answers more.
          </td>
          <td>Copied from a member</td>
        </tr>
        <tr>
          <td><code>sf.Median()</code> · <code>sf.Mean()</code></td>
          <td>The middle, or the (weighted) average, of the members' numeric answers.</td>
          <td>Computed, or the nearest member</td>
        </tr>
        <tr>
          <td><code>sf.ArgMax(by)</code> · <code>sf.ArgMin(by)</code></td>
          <td>The answer with the highest / lowest value of the signal <code>by</code>.</td>
          <td>Copied from a member</td>
        </tr>
        <tr>
          <td><code>sf.Synthesize(model)</code></td>
          <td>A new answer that <code>model</code> writes after reading the panel.</td>
          <td>Newly written</td>
        </tr>
      </tbody>
    </table>

    <h2 id="map">Map: score each answer</h2>

    <p>
      A <strong>signal</strong> is a named number on each answer: a stated confidence, a judge's
      score, a cost. Every answer carries a <code>signals</code> map of name to number, for example
      <code>{ "conf": 90, "cost_usd": 0.004 }</code>. A step names the one it wants (as
      <code>weights=</code>, <code>by=</code> or <code>where=</code>), and you can read them yourself
      with <code>answer.signals["name"]</code>. Signals come from three places:
    </p>

    <ul>
      <li>
        <strong>Extracted from the model's response</strong>, declared with
        <code>signals={"name": source}</code> on <code>sf.Fanout</code>. Each source measures
        something about a member's own answer as it comes back, with no extra step in the chain:
        <ul>
          <li>
            <code>sf.Verbalized(pattern)</code>: a number the model states in its text, pulled out by
            a regex (e.g. a <code>Confidence: 90</code> line).
          </li>
          <li>
            <code>sf.Logprob(...)</code>: how certain the model was, from the token probabilities of
            its answer.
          </li>
          <li>
            <code>sf.Consistency(n=N)</code>: how stable the answer is. Rerun the member N times and
            take the fraction that give the same answer.
          </li>
        </ul>
      </li>
      <li>
        <strong>Scored by a judge</strong>, an extra step that runs after the answers come back.
        <code>sf.Judge</code> runs a separate judge model over each answer and records its grade as
        <code>score:judge</code>.
      </li>
      <li>
        <strong>Recorded by the engine</strong>, always present with nothing to declare: each call's
        <code>cost_usd</code>, <code>latency_ms</code>, <code>tokens_in</code> and
        <code>tokens_out</code>, plus any field of a JSON answer read as <code>field:&lt;path&gt;</code>
        (e.g. <code>field:confidence</code>).
      </li>
    </ul>

    <p>
      The example below reads a signal as a <strong>weight</strong>. Each member is prompted to end
      with a <code>Confidence:</code> line, <code>sf.Verbalized</code> pulls that number out as
      <code>conf</code>, and <code>sf.Vote(weights="conf")</code> makes more confident answers count
      for more. Every signal has its own requirement, listed in the table that follows.
    </p>

    <div class="not-prose">
      <NbCell :count="3" :code="weigh"><NbTextOut :text="weighOut" /></NbCell>
    </div>

    <h3>Available signals</h3>

    <table>
      <thead>
        <tr>
          <th>Signal</th>
          <th>The number it yields</th>
          <th>Requires</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>sf.Verbalized(pattern)</code></td>
          <td>
            A number the model wrote in its answer, extracted with a regex (e.g.
            <code>Confidence: 90</code>).
          </td>
          <td>The prompt asks the model to write it.</td>
        </tr>
        <tr>
          <td><code>sf.Logprob(...)</code></td>
          <td>The answer's mean log-probability.</td>
          <td>The provider returns logprobs.</td>
        </tr>
        <tr>
          <td><code>sf.Entropy(...)</code></td>
          <td>The uncertainty of the token distribution.</td>
          <td>The provider returns logprobs.</td>
        </tr>
        <tr>
          <td><code>sf.Consistency(n=N)</code></td>
          <td>The fraction of N re-runs that agree.</td>
          <td>N extra calls per member.</td>
        </tr>
        <tr>
          <td><code>"score:judge"</code></td>
          <td>The judge model's score for the answer.</td>
          <td>An <code>sf.Judge</code> step earlier in the chain.</td>
        </tr>
        <tr>
          <td><code>"field:&lt;path&gt;"</code></td>
          <td>A value parsed from the answer's JSON (e.g. <code>field:confidence</code>).</td>
          <td>The member returns that field.</td>
        </tr>
        <tr>
          <td>
            <code>"cost_usd"</code> · <code>"latency_ms"</code> · <code>"tokens_in"</code> ·
            <code>"tokens_out"</code>
          </td>
          <td>The call's recorded cost, latency or token counts.</td>
          <td>Nothing; always available.</td>
        </tr>
      </tbody>
    </table>

    <h3>Reading a signal</h3>

    <p>
      Steps refer to signals by name: pass it to <code>weights=</code> to weigh by it, or to
      <code>by=</code> to rank by it. To read one directly, use <code>sf.signal("name")</code>.
    </p>

    <p>
      A missing value is not an error. If an answer lacks the signal (say a model skipped its
      <code>Confidence:</code> line), the value is <code>None</code> and that answer sits out the
      step. An unknown name is an error: a name that no earlier step provides raises before any model
      is called, so a typo never costs you a run.
    </p>

    <h3>Signals in practice</h3>

    <p>
      A few canonical patterns. Each declares or reads a different signal, then lets a reducer act on
      it:
    </p>

    <CodeBlock :code="examples" language="python" />

    <h3>Putting it together: a judged fusion</h3>

    <p>
      Dispatch, map and reduce in one chain: fan out to three models, have a cheap judge model score
      each answer, and keep the highest-scoring one. No selector needed.
    </p>

    <CodeBlock :code="worked" language="python" />

    <p>
      Stage by stage: <code>sf.Fanout</code> <strong>dispatches</strong> the question to three
      members, <code>sf.Judge</code> <strong>maps</strong> a <code>score:judge</code> onto each
      answer, and <code>sf.ArgMax("score:judge")</code> <strong>reduces</strong> the panel to the
      best-scored answer. <code>sf.evaluate</code> then runs the fusion on 20 IFEval prompts and
      grades each final answer. Every stage swaps independently: change the rubric, weigh by the
      judge's score with <code>sf.Vote(weights="score:judge")</code> instead of taking the max, or
      drop the judge and rank by a declared signal. Each swap is a new fusion built from the same
      four kinds of step.
    </p>

    <h2 id="filter">Filter: drop answers before reducing</h2>

    <p>
      A <strong>selector</strong> removes answers from the panel, usually by reading a signal, so the
      reducer only sees the ones worth keeping. This matters most for <code>sf.Synthesize</code>,
      which reads every answer it's given. A selector is not terminal: a reducer still has to follow
      it.
    </p>

    <ul>
      <li>
        <code>sf.Rank(k, by=...)</code> keeps the top <code>k</code> by a signal. The count is fixed:
        always <code>k</code>, as long as that many answers carry the signal.
      </li>
      <li>
        <code>sf.Filter(where=...)</code> keeps every answer that clears a threshold. The count
        varies, and can be zero.
      </li>
      <li><code>sf.Concat</code> joins the panel's answers.</li>
    </ul>

    <p>
      Selectors read the same signals reducers do. The <code>conf</code> signal from earlier can
      decide whether an answer survives, or how much it counts:
    </p>

    <figure class="not-prose" style="margin: var(--space-7) 0">
      <svg
        class="dg"
        viewBox="0 0 660 196"
        role="img"
        aria-label="One signal, conf, scores answers a, b and c at 90, 60 and 75. sf.Rank(2, by=conf) reads it to keep a and c and drop b. sf.Vote(weights=conf) reads it to let all three vote, weighted 90, 60 and 75."
      >
        <defs>
          <marker
            id="sg-a"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="6"
            markerHeight="6"
            orient="auto"
          >
            <path d="M0 0 L8 4 L0 8 z" style="fill: var(--text-2)" />
          </marker>
        </defs>
        <g class="edge" marker-end="url(#sg-a)">
          <path d="M216 98 C 256 98, 256 54, 300 54" />
          <path d="M216 98 C 256 98, 256 142, 300 142" />
        </g>
        <rect class="box enrich" x="20" y="38" width="196" height="120" />
        <text x="36" y="62" class="lbl">signal "conf"</text>
        <text x="40" y="88" style="fill:var(--text);font-size:12.5px">a</text>
        <rect x="58" y="80" width="94.5" height="8" rx="2" style="fill:var(--data-teal-500)" />
        <text x="196" y="88" text-anchor="end" style="fill:var(--text-2);font-size:12.5px">90</text>
        <text x="40" y="112" style="fill:var(--text);font-size:12.5px">b</text>
        <rect x="58" y="104" width="63.0" height="8" rx="2" style="fill:var(--data-teal-500)" />
        <text x="196" y="112" text-anchor="end" style="fill:var(--text-2);font-size:12.5px">60</text>
        <text x="40" y="136" style="fill:var(--text);font-size:12.5px">c</text>
        <rect x="58" y="128" width="78.8" height="8" rx="2" style="fill:var(--data-teal-500)" />
        <text x="196" y="136" text-anchor="end" style="fill:var(--text-2);font-size:12.5px">75</text>
        <rect class="box narrow" x="300" y="24" width="344" height="60" />
        <rect class="box reduce" x="300" y="112" width="344" height="60" />
        <g class="lbl">
          <text x="316" y="49">filter · sf.Rank(2, by="conf")</text>
          <text x="316" y="137">reduce · sf.Vote(weights="conf")</text>
        </g>
        <g style="fill: var(--text-2); font-size: 12.5px">
          <text x="316" y="70">keeps a and c, drops b</text>
          <text x="316" y="158">all three vote: a counts 90, c 75, b 60</text>
        </g>
      </svg>
      <figcaption class="dgcap">
        One declared signal, two readers: <code>sf.Rank</code> uses it to decide which answers
        survive, <code>sf.Vote</code> to decide how much each one counts.
      </figcaption>
    </figure>

    <p>Keep the two most confident answers, then have a model write the final answer from just those two:</p>

    <div class="not-prose">
      <NbCell :count="4" :code="narrow"><NbTextOut :text="narrowOut" /></NbCell>
    </div>

    <p>
      The same move extends the judged fusion: rank by the judge's score, keep the top two, and swap
      <code>sf.ArgMax</code> for <code>sf.Synthesize</code> so a model writes the final answer from
      the two best-scored drafts.
    </p>

    <CodeBlock :code="narrowUpgrade" language="python" />

    <h2>Other ways to dispatch</h2>

    <p>
      <code>sf.Fanout</code> is the simplest dispatch: every member answers every question. Routers,
      cascades and pipelines are dispatch strategies too. They add <strong>control flow</strong>,
      deciding <em>which</em> members run and in what order, often by reading the same signals you
      have seen here. <code>sf.Gate</code> is the first control-flow piece: it reads a signal and
      decides whether to answer or abstain. What each strategy hands to the stages after it depends on
      the strategy; this page covers what follows a fan-out.
    </p>

    <h2>See also</h2>

    <ul>
      <li>
        <RouterLink to="/sf-client/guides/fusions">Fusions</RouterLink>: the fan-out and
        <code>sf.Synthesize</code> in depth.
      </li>
      <li>
        <RouterLink to="/sf-client/guides/pipelines">Pipelines</RouterLink>: chaining steps and
        nesting recipes.
      </li>
      <li>
        <RouterLink to="/sf-client/api/reducers">Reducers reference</RouterLink>: signatures for
        every reducer, selector, judge and signal.
      </li>
    </ul>
  </DocLayout>
</template>

<style scoped>
/* Map-reduce diagrams: neutral boxes, role encoded by border colour from the
   SFDS categorical --data-* palette, matching the Fusions and Pipelines guides. */
.dg {
  width: 100%;
  height: auto;
  font-family: var(--f-mono);
  font-size: 13px;
}
.dg .box {
  fill: var(--surface);
  stroke: var(--border);
  stroke-width: 1.75;
}
.dg .map {
  stroke: var(--data-azure-500);
}
.dg .enrich {
  stroke: var(--data-teal-500);
}
.dg .narrow {
  stroke: var(--data-orange-500);
}
.dg .reduce {
  stroke: var(--data-green-500);
}
.dg .graded {
  stroke: var(--data-green-500);
  stroke-dasharray: 3 3;
}
.dg .optional {
  stroke-dasharray: 4 3;
}
.dg .lbl {
  fill: var(--text);
  font-weight: 500;
}
.dg .sub {
  fill: var(--text-2);
  font-size: 11px;
}
.dg a {
  cursor: pointer;
}
.dg a text {
  text-decoration: underline;
  text-underline-offset: 2px;
}
.dg a:hover text {
  fill: var(--accent-text-low);
}
.dg .edge {
  fill: none;
  stroke: var(--text-2);
  stroke-width: 1.25;
}
.dgcap {
  font-size: var(--text-sm);
  line-height: 1.55;
  color: var(--text-2);
  margin-top: var(--space-4);
  max-width: 62ch;
}
/* Offset in-page jumps (from the diagram labels) so the sticky navbar
   does not cover the target heading. */
h2[id] {
  scroll-margin-top: 5rem;
}
</style>
