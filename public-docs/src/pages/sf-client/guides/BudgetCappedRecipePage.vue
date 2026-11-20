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

const cap = `import screamingface as sf

panel = [
    "openrouter/deepseek/deepseek-v4-flash",
    "openrouter/google/gemini-3.5-flash-lite",
    "openrouter/anthropic/claude-haiku-4.5",
]
large = "openrouter/anthropic/claude-opus-4.8"
VOTE = dict(over="last_number", normalize="numeric")

# A cascade that escalates to the large model when the panel splits.
cope = sf.Cascade(
    sf.Fanout(panel) >> sf.Vote(**VOTE),
    sf.escalate_if(sf.agreement() < 0.8),
    large,
)

# Cap what one case may spend across the whole cascade.
recipe = sf.WithBudget(cope, budget_usd=0.05)`

const refuse = `# Tell the budget what the optional branch costs, so it can refuse before sending.
recipe = sf.WithBudget(
    sf.Fanout(panel) >> sf.Gate(
        when=sf.agreement() >= 1.0,
        then=sf.Vote(**VOTE),
        otherwise=sf.Estimate(large, usd=0.01),
    ),
    budget_usd=0.002,   # tight: the escalation to large is refused, and large never runs
)`

const remaining = `# Choose the model you can still afford from what the cap has left.
recipe = sf.WithBudget(
    sf.Gate(
        when=sf.budget.remaining() >= 0.02,
        then=large,
        otherwise="openrouter/google/gemini-3.5-flash-lite",
    ),
    budget_usd=0.05,
)`
</script>

<template>
  <DocLayout
    title="Budget capped recipe"
    description="Give one case a spend cap the recipe can see, so an optional call is refused before it is sent."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A <RouterLink to="/sf-client/guides/cascades-gates">cascade or gate</RouterLink> can run an
      expensive branch on the hard cases. A budget puts a ceiling on what one case may spend, and lets
      the recipe see how much is left before it makes an optional call. Wrap the whole candidate once
      with <code>sf.WithBudget</code>, and set a dollar cap, a token cap, or both.
    </p>

    <CodeBlock :code="cap" language="python" />

    <p>
      The cap applies to a single case. Before each call a gate could skip, the engine adds what the case
      has already spent to the branch's estimated cost. If the total is over the cap, the branch is not
      sent, and the report records it as <code>budget_refused</code>. A call that always runs is never
      refused.
    </p>

    <ThemedDiagram
      bare
      name="sf-client-budget-check"
      alt="Before an optional call, the spend so far plus the branch estimate is compared to the cap. Under the cap, the call is sent. Over the cap, the branch is skipped and recorded as budget_refused."
      caption="A budget checks an optional call before it is sent: under the cap it runs, over the cap it is skipped."
    />

    <h2>Refuse an escalation before it is sent</h2>

    <p>
      For the budget to refuse a branch, it needs to know what the branch will cost before the call
      happens. Wrap that branch in <code>sf.Estimate</code>. With a tight cap, the escalation is refused
      and the stronger model never runs.
    </p>

    <CodeBlock :code="refuse" language="python" />

    <Note>
      The cap is a budget, not a hard ceiling. Calls that always run can take a case over it, and the
      report then shows the overspend. A call whose cost is unknown counts as $0 against a dollar cap,
      and the report warns.
    </Note>

    <h2>Pick the model you can still afford</h2>

    <p>
      A gate can read <code>sf.budget.remaining()</code>, which is what the cap has left after the calls
      that already ran. Use it to choose a stronger branch while there is room, and a cheaper one once
      the budget runs low. Reading it without a <code>sf.WithBudget</code> at the root raises an error
      before any call.
    </p>

    <CodeBlock :code="remaining" language="python" />

    <h2>Replays take the same branch</h2>

    <p>
      When you replay a run, its calls come from the gateway cache and cost nothing live. The budget
      still charges each call its original reference price, so the case sees the same spend and takes the
      same branch as the live run. A budgeted recipe reproduces exactly.
    </p>

    <ThemedDiagram
      bare
      name="sf-client-budget-replay"
      alt="A live run charges each call's real cost and a replay charges the reference price. The budget sees the same spend both times, so the same branch is taken."
      caption="A live run and a replay charge the same reference price, so the budget takes the same branch both times."
    />

    <p>
      The <RouterLink to="/sf-client/api/budgeted-runs">Budgeted runs</RouterLink> reference covers
      <code>sf.WithBudget</code>, <code>sf.Estimate</code>, and the charge rules in full.
    </p>
  </DocLayout>
</template>
