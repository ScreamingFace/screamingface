<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const cascade = `import screamingface as sf

panel = [
    "openrouter/deepseek/deepseek-v4-flash",
    "openrouter/google/gemini-3.5-flash-lite",
    "openrouter/anthropic/claude-haiku-4.5",
]

# The large model answers only when the panel does not agree.
cope = sf.Cascade(
    sf.Fanout(panel) >> sf.Vote(),
    sf.escalate_if(sf.agreement() < 0.8),
    "openrouter/anthropic/claude-opus-4.8",
)
# repr(cope) shows the Gate form it is sugar for:
# Fanout([...]) >> Gate(when=agreement() >= 0.8, then=Vote(),
#                       otherwise='openrouter/anthropic/claude-opus-4.8')`

const firstSuccess = `# First success: the next model runs only when the one before fails or abstains.
chain = sf.Cascade(
    "openrouter/google/gemini-3.5-flash-lite",
    sf.escalate_if(sf.unanswered()),
    "openrouter/deepseek/deepseek-v4-flash",
    sf.escalate_if(sf.unanswered()),
    "openrouter/anthropic/claude-opus-4.8",
)`

const closing = `# A human last tier: escalate on low agreement, else abstain.
cascade = sf.Cascade(
    sf.Fanout(panel) >> sf.Vote(),
    sf.escalate_if(sf.agreement() < 0.66),
    sf.abstain(),
)
# Equivalent, byte for byte, to a single gated vote:
same = sf.Fanout(panel) >> sf.Gate(when=sf.agreement() >= 0.66, then=sf.Vote(), otherwise=sf.abstain())
assert cascade == same`

const gotcha = `# A tier followed straight by an outcome, with no line, is refused:
sf.Cascade(sf.Fanout(panel) >> sf.Vote(), sf.abstain())
# ValueError: sf.Cascade part 2 can never run: write sf.escalate_if(...) after tier 1

# Put the sf.escalate_if(...) line between the tier and the outcome. Or, for a plain
# "vote, else abstain", use a single sf.Gate and skip the cascade entirely.`

const adaptive = `# Two samples first; five fresh samples only when the two do not agree.
model = "openrouter/google/gemini-3.5-flash-lite"
adaptive = sf.Cascade(
    sf.Fanout(sf.samples(model, 2)) >> sf.Vote(),
    sf.escalate_if(sf.agreement() < 1.0),
    sf.Fanout(sf.samples(model, 5, seeds=range(2, 7))) >> sf.Vote(),
)
# Tier 2 does not reuse tier 1's samples. Equal seeds raise sf.CascadeSeedWarning.`
</script>

<template>
  <DocLayout
    title="Cascades & gates"
    description="Decide, after an answer exists, whether to keep it or escalate, with one branch construct, sf.Gate, and its shorthand sf.Cascade."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A cascade tries one approach, then moves to the next only when a condition on the current answer
      says it should. You pick what each tier is and what counts as good enough. One use is to escalate
      from a smaller model to a larger one, but a tier can be anything: a single model, a panel, or a
      different method. For example, keep a panel vote when the models agree, and escalate to another
      model when they do not.
    </p>

    <p>
      The decision behind each step is a gate. After a
      <RouterLink to="/sf-client/api/fusions">fanout</RouterLink>, a gate reads one number from the
      answers, such as how far the models agreed, and either keeps that answer (<code>then</code>) or
      runs a fallback (<code>otherwise</code>). <code>sf.Gate</code> is the only branch construct in the
      toolkit, and <code>sf.Cascade</code> is shorthand for stacking a few gates in a row. See
      <RouterLink to="/sf-client/api/reducers#gate">Gate</RouterLink> for the gate on its own.
    </p>

    <Note>
      Whichever branch a gate skips makes zero model calls and costs nothing; the report shows it as
      not selected. Branching needs an engine that serves it, or the run raises
      <code>sf.EngineCapabilityError</code> before anything is spent. Deciding from the
      <em>question itself</em>, before any model answers (routing), is coming soon. To cap what a case
      may spend, see <RouterLink to="/sf-client/api/budgeted-runs">budgeted runs</RouterLink>.
    </Note>

    <h2>Cascades</h2>

    <p>
      Write the tiers in order, with an <code>sf.escalate_if(...)</code> line between each pair that says
      when to move on. Each tier answers the original question from scratch, not the previous tier's
      answer. A tier before a line is a <code>sf.Fanout</code> block that ends in a reducer such as
      <code>sf.Vote()</code>; the last tier can be any recipe.
    </p>

    <p>
      <code>sf.Cascade</code> is only a shortcut: it builds the same nested <code>sf.Gate</code> values
      you could write by hand, down to the same <RouterLink to="/sf-client/api/url4">url4</RouterLink>,
      so <code>repr</code> and <code>==</code> show the gate form.
    </p>

    <CodeBlock :code="cascade" language="python" />

    <p>
      You write the condition as the reason to <em>escalate</em>.
      <code>sf.escalate_if(sf.agreement() &lt; 0.8)</code> means &ldquo;move on when agreement is below
      0.8&rdquo;, so the gate keeps the current tier's answer when agreement is 0.8 or higher. A
      condition can read how far the members agreed (<code>sf.agreement()</code>), the chosen member's
      signal
      (<code>sf.signal(name).chosen()</code>) or the average across members
      (<code>sf.signal(name).mean()</code>).
    </p>

    <p>A tier moves on only when a line tells it to. Anything else ends the cascade:</p>

    <ul>
      <li>If a tier fails, the case fails with that tier's error code.</li>
      <li>If a tier abstains, the case abstains with that reason.</li>
      <li>
        If the number a line needs is missing (for example a reply with no log-probability), the case
        fails with <code>signal_missing</code>.
      </li>
      <li>
        The one exception is <code>sf.escalate_if(sf.unanswered())</code>, which moves on when a tier
        fails or abstains. This is the &ldquo;try the next model until one answers&rdquo; pattern, also
        called first success.
      </li>
    </ul>

    <CodeBlock :code="firstSuccess" language="python" />

    <h2>Gate outcomes</h2>

    <p>
      A gate's <code>then</code> and <code>otherwise</code> can each be a reducer step (after a
      <code>sf.Fanout</code>), a full recipe (a route, an <code>sf.Model</code>, a chain, or another
      <code>sf.Gate</code>), or a typed outcome (<code>sf.abstain()</code> or <code>sf.fail()</code>). A
      recipe only runs on the cases that reach it, so keeping the cheap answer costs nothing extra. In a
      cascade, an outcome can close the chain after a line.
    </p>

    <table>
      <thead>
        <tr>
          <th>Outcome</th>
          <th>What it does</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>sf.abstain()</code></td>
          <td>
            The case abstains with <code>gate_not_met</code>: a scored decline, counted with the other
            abstains. The default when <code>otherwise</code> is omitted. The string
            <code>"abstain"</code> (the pre-E4c spelling) still works.
          </td>
        </tr>
        <tr>
          <td><code>sf.fail()</code></td>
          <td>
            The case fails with the code <code>fail_closed</code>, and no model runs after the gate. It
            is a failure, not an abstain. The string <code>"fail_closed"</code> is refused; write
            <code>sf.fail()</code>.
          </td>
        </tr>
      </tbody>
    </table>

    <CodeBlock :code="closing" language="python" />

    <Note>
      A tier followed directly by an outcome with no <code>sf.escalate_if(...)</code> line between them
      is refused, because that second part could never run. For a plain &ldquo;vote, else abstain&rdquo;
      you do not need a cascade at all: a single <code>sf.Gate</code> is shorter and compiles to the
      same bytes.
    </Note>

    <CodeBlock :code="gotcha" language="python" />

    <h2>Adaptive sampling</h2>

    <p>
      Adaptive sampling is a cascade over sample panels: take a few samples first, and draw more only
      when they disagree. Tier 2 does not reuse tier 1's samples, so give it fresh <code>seeds=</code>;
      reusing seeds raises <RouterLink to="/sf-client/api/errors">CascadeSeedWarning</RouterLink>.
    </p>

    <CodeBlock :code="adaptive" language="python" />

    <h2>Outcomes and codes</h2>

    <table>
      <thead>
        <tr>
          <th>Code</th>
          <th>Kind</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>gate_not_met</code></td>
          <td>abstain</td>
          <td><code>sf.abstain()</code> (or the default <code>otherwise</code>): a scored decline.</td>
        </tr>
        <tr>
          <td><code>fail_closed</code></td>
          <td>failure</td>
          <td><code>sf.fail()</code>: the case fails and no model runs after the gate.</td>
        </tr>
        <tr>
          <td><code>signal_missing</code></td>
          <td>failure</td>
          <td>A gate condition, or a cascade tier, had no number to compare.</td>
        </tr>
        <tr>
          <td><code>not_selected</code></td>
          <td>status</td>
          <td>A branch that was not taken, so it made zero calls.</td>
        </tr>
      </tbody>
    </table>

    <p>
      Each <code>sf.Gate</code> shows in a &ldquo;Branches&rdquo; section of the report: the condition,
      the number it read, the branch it took, and each branch that did not run, with its reason. See
      <RouterLink to="/sf-client/api/candidate-result">CandidateResult</RouterLink>.
    </p>
  </DocLayout>
</template>
