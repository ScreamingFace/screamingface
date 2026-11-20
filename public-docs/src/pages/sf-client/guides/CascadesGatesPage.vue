<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import ThemedDiagram from '@/components/ui/ThemedDiagram.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const panel = `import screamingface as sf

# A cheap panel and one strong model to fall back on.
panel = [
    "openrouter/deepseek/deepseek-v4-flash",
    "openrouter/google/gemini-3.5-flash-lite",
    "openrouter/anthropic/claude-haiku-4.5",
]
large = "openrouter/anthropic/claude-opus-4.8"

VOTE = dict(over="last_number", normalize="numeric")`

const splitGate = `# Keep the panel's vote. Call the large model only when the panel splits.
recipe = sf.Cascade(
    sf.Fanout(panel) >> sf.Vote(**VOTE),
    sf.escalate_if(sf.agreement() < 0.66),
    large,
)`

const confidence = `# Each member states how sure it is on its first line; escalate when the
# chosen member's confidence is below 70.
STATED = (
    "Start your reply with one line 'Confidence: <0-100>'. Then solve the problem. "
    "The last line must be only the final number."
)
conf = sf.Verbalized(r"Confidence:\\s*([0-9]+)", ignore_case=True)
recipe = sf.Cascade(
    sf.Fanout([sf.Model("openrouter/google/gemini-3.5-flash-lite", prompt=STATED)],
              signals={"conf": conf}) >> sf.Vote(**VOTE),
    sf.escalate_if(sf.signal("conf").chosen() < 70),
    large,
)`

const logprob = `# Escalate when the small model's own token probability is low (OpenRouter models).
recipe = sf.Cascade(
    sf.Fanout(["openrouter/openai/gpt-4o-mini"], signals={"lp": sf.Logprob("prob")})
    >> sf.Vote(**VOTE),
    sf.escalate_if(sf.signal("lp").chosen() < 0.7),
    "openrouter/openai/gpt-4.1",
)`

const firstSuccess = `# Try each model in order. The next one runs only when the one before gives no answer.
recipe = sf.Cascade(
    "openrouter/openai/gpt-4o-mini",
    sf.escalate_if(sf.unanswered()),
    "openrouter/google/gemini-3.5-flash-lite",
    sf.escalate_if(sf.unanswered()),
    "openrouter/openai/gpt-4.1",
)`

const lazyJudge = `# Keep the vote when the panel agrees; pay for a judge only when it splits.
judge = "openrouter/google/gemini-3.5-flash-lite"
recipe = sf.Fanout(panel) >> sf.Gate(
    when=sf.agreement() >= 0.66,
    then=sf.Vote(**VOTE),
    otherwise=sf.JudgePick(judge, rubric="Pick the member whose final answer is correct."),
)`

const adaptive = `# Take two samples first. Draw five more only when the two disagree.
small = "openrouter/google/gemini-3.5-flash-lite"
recipe = sf.Cascade(
    sf.Fanout(sf.samples(small, 2)) >> sf.Vote(**VOTE),
    sf.escalate_if(sf.agreement() < 1.0),
    sf.Fanout(sf.samples(small, 5, seeds=range(2, 7))) >> sf.Vote(**VOTE),
)`

const decline = `# Decline instead of guessing: abstain when the panel never reaches full agreement.
abstaining = sf.Cascade(
    sf.Fanout(panel) >> sf.Vote(**VOTE),
    sf.escalate_if(sf.agreement() < 1.0),
    sf.abstain(),            # scored as a decline (gate_not_met)
)

# Or fail the case outright, so nothing downstream uses a weak answer.
failing = sf.Cascade(
    sf.Fanout(panel) >> sf.Vote(**VOTE),
    sf.escalate_if(sf.agreement() < 1.0),
    sf.fail(),               # the case fails (fail_closed)
)`

const equivalence = `# sf.Cascade is shorthand. These two are equal, byte for byte.
cascade = sf.Cascade(
    sf.Fanout(panel) >> sf.Vote(**VOTE),
    sf.escalate_if(sf.agreement() < 0.66),
    large,
)
gate = sf.Fanout(panel) >> sf.Gate(
    when=sf.agreement() >= 0.66, then=sf.Vote(**VOTE), otherwise=large
)
assert cascade == gate`
</script>

<template>
  <DocLayout
    title="Cascades & gates"
    description="Let a recipe decide, per case, whether to do more: keep the cheap answer, or escalate to a stronger one."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A plain <RouterLink to="/sf-client/guides/fusions">fusion</RouterLink> runs every model on every
      case. A gate lets the recipe decide, case by case, whether the current answer is good enough or
      whether to spend more on a stronger one. This guide walks through the situations where that helps
      and the block to reach for in each.
    </p>

    <p>
      A gate reads one number from a panel's answers and either keeps that answer or runs a fallback.
      Whichever branch it does not take makes zero model calls.
    </p>

    <ThemedDiagram
      bare
      name="sf-client-cascade-gate"
      alt="A sf.Fanout feeds a sf.Gate. When agreement is at least 0.66 the gate keeps the vote and makes no extra call; when the panel splits it runs the larger model."
      caption="A gate keeps the panel's answer when the models agree, and falls back to a stronger model when they split."
    />

    <p>
      Every example below builds a single recipe. Set up a panel and a fallback model once, then try the
      patterns against it. The <RouterLink to="/sf-client/api/cascades-gates">Cascades &amp; gates</RouterLink>
      reference has the full rules.
    </p>

    <CodeBlock :code="panel" language="python" />

    <h2>Keep the cheap answer, escalate when the panel splits</h2>

    <p>
      A small panel votes. When enough of its members agree, you keep that answer and make no further
      call. When they split, the larger model answers the original question. Write the escalation as the
      reason to go on (<code>agreement() &lt; 0.66</code>), and the gate keeps the vote on the opposite
      side.
    </p>

    <CodeBlock :code="splitGate" language="python" />

    <h2>Escalate when the model itself is unsure</h2>

    <p>
      Agreement across a panel is one signal. Another is a model's own confidence. Ask each member to
      state how sure it is, then escalate when the chosen member's number is low.
    </p>

    <CodeBlock :code="confidence" language="python" />

    <p>
      If the model runs on OpenRouter, you can read its token probability instead of asking it, with
      <code>sf.Logprob</code>. A condition must name <code>.chosen()</code> or <code>.mean()</code>; a
      bare <code>sf.signal("lp")</code> is refused.
    </p>

    <CodeBlock :code="logprob" language="python" />

    <h2>Try models in order until one answers</h2>

    <p>
      Sometimes a tier can fail or abstain rather than give a weak answer, and you just want the first
      model that succeeds. <code>sf.escalate_if(sf.unanswered())</code> moves on only when a tier gives
      no answer. Its members become optional, so a failure escalates instead of failing the case.
    </p>

    <ThemedDiagram
      bare
      name="sf-client-cascade-first-success"
      alt="Three models in a row. Each runs only when the previous one gave no answer; a model that answers stops the chain. The last model always answers."
      caption="First success: each tier runs only when the one before gave no answer."
    />

    <CodeBlock :code="firstSuccess" language="python" />

    <h2>Run an expensive step only when needed</h2>

    <p>
      A gate's fallback can be any recipe, including a judge or a writer. It runs only on the cases that
      take it, so a judge that would be costly on every case becomes cheap: it reads the panel only when
      the panel splits.
    </p>

    <CodeBlock :code="lazyJudge" language="python" />

    <h2>Sample a little, then more</h2>

    <p>
      When you vote over several samples of one model, you can start small and draw more only when the
      first samples disagree. This is a cascade over sample panels. Give the second tier fresh
      <code>seeds=</code> so it does not reuse the first tier's samples.
    </p>

    <CodeBlock :code="adaptive" language="python" />

    <h2>Decline or fail instead of guessing</h2>

    <p>
      When no tier is good enough, you do not have to return a weak answer. End a cascade with
      <code>sf.abstain()</code> to record a scored decline, or <code>sf.fail()</code> to fail the case so
      nothing downstream uses the answer.
    </p>

    <CodeBlock :code="decline" language="python" />

    <h2>A cascade is nested gates</h2>

    <p>
      <code>sf.Cascade</code> is shorthand. It builds the same nested <code>sf.Gate</code> values you
      could write by hand, so a two-tier cascade and a single gate are equal, byte for byte. A longer
      cascade is just more tiers, each joined to the next by an <code>sf.escalate_if(...)</code> line.
    </p>

    <ThemedDiagram
      bare
      name="sf-client-cascade-chain"
      alt="Three tiers in a row joined by escalate_if lines. Tier 1 is kept when good enough; each later tier runs only when the escalate_if before it holds; the last tier answers unconditionally."
      caption="A cascade is tiers joined by escalate_if lines. The last tier always answers."
    />

    <CodeBlock :code="equivalence" language="python" />

    <Note>
      Put an <code>sf.escalate_if(...)</code> line between every pair of parts. A tier followed straight
      by another tier, or by <code>sf.abstain()</code> with no line between them, is refused, because
      that second part could never run. For a plain "vote, else abstain" you do not need a cascade at
      all: a single <code>sf.Gate</code> is shorter.
    </Note>

    <p>
      To cap what one case may spend across these tiers, see
      <RouterLink to="/sf-client/guides/budget-capped-recipe">Budget capped recipe</RouterLink>.
    </p>
  </DocLayout>
</template>
