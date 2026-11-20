<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const cap = `import screamingface as sf

panel = [
    "openrouter/deepseek/deepseek-v4-flash",
    "openrouter/google/gemini-3.5-flash-lite",
    "openrouter/anthropic/claude-haiku-4.5",
]

# A cheap-first cascade: the large model answers only when the panel disagrees.
cope = sf.Cascade(
    sf.Fanout(panel) >> sf.Vote(),
    sf.escalate_if(sf.agreement() < 0.8),
    "openrouter/anthropic/claude-opus-4.8",
)

# Wrap the whole candidate once, at the root, with a per-case spend cap.
capped = sf.WithBudget(cope, budget_usd=0.05, max_tokens=20000)`

const remaining = `# Choose the branch from what the cap has left (willingness to pay).
by_budget = sf.WithBudget(
    sf.Gate(
        when=sf.budget.remaining() >= 0.02,
        then="openrouter/anthropic/claude-opus-4.8",
        otherwise="openrouter/google/gemini-3.5-flash-lite",
    ),
    budget_usd=0.05,
)`

const estimate = `# Wrap a gate's optional branch to say what it is expected to cost, so the budget
# can refuse it before the call is sent.
gated = sf.Fanout(panel) >> sf.Gate(
    when=sf.agreement() >= 0.8,
    then=sf.Vote(),
    otherwise=sf.Estimate("openrouter/anthropic/claude-opus-4.8", usd=0.03),
)
capped = sf.WithBudget(gated, budget_usd=0.05)`
</script>

<template>
  <DocLayout
    title="Budgeted runs"
    description="Give each case a spend cap the decision can see, so optional calls are refused before they are sent."
    :navigation="navigation"
    :version="version"
  >
    <p>
      A budget caps what a single case may spend, and the decision can see how much is left before it
      makes an optional call. It works together with
      <RouterLink to="/sf-client/api/cascades-gates">cascades and gates</RouterLink>: when a gate branch
      would push the case over the cap, that branch is skipped.
    </p>

    <p>
      Wrap the whole candidate once with
      <code>sf.WithBudget(recipe, *, budget_usd=None, max_tokens=None)</code>. Set a dollar cap, a token
      cap, or both.
    </p>

    <CodeBlock :code="cap" language="python" />

    <h2>How the cap is spent</h2>

    <ul>
      <li>
        Before an optional call (one a gate could skip), the engine adds what the case has already spent
        to the branch's estimated cost (<code>sf.Estimate(branch, usd=...)</code>). If that total is
        over the cap, the branch is not sent, and the report shows <code>budget_refused</code>. A call
        that always runs is never refused.
      </li>
      <li>
        The cap is a budget, not a hard ceiling. The calls that always run can take a case over it, and
        the report then shows the overspend.
      </li>
      <li>A call with an unknown cost counts as $0 against a USD cap, and the report warns.</li>
      <li>
        On a cache hit, the branch is charged at the original call's cost, so a replay takes the same
        branch as the live run.
      </li>
    </ul>

    <h2>Reading what is left</h2>

    <p>
      <code>sf.budget.remaining()</code> is what the cap has left after the calls that already ran. A
      gate can read it to choose a branch. Reading it with no <code>sf.WithBudget</code> at the root
      raises <code>ValueError</code> before any call.
    </p>

    <CodeBlock :code="remaining" language="python" />

    <h2>Estimating a branch</h2>

    <p>
      <code>sf.Estimate(branch, *, usd=..., tokens=...)</code> tells the engine what an optional branch
      is expected to cost, so a budget can refuse it before the call is sent rather than after.
    </p>

    <CodeBlock :code="estimate" language="python" />

    <Note>
      A refused optional call with no answer left to keep makes the case abstain with
      <code>budget_refused</code>. It appears in the report's &ldquo;Branches&rdquo; section alongside
      the cap, the spend and the estimate. See
      <RouterLink to="/sf-client/api/candidate-result">CandidateResult</RouterLink>.
    </Note>
  </DocLayout>
</template>
