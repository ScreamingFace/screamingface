<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'
</script>

<template>
  <DocLayout
    title="Routers"
    description="Decide which models run from the question itself, before any member answers. Coming soon."
    :navigation="navigation"
    :version="version"
  >
    <Note> Routing is in progress and not yet available. This page describes what is coming. </Note>

    <p>
      A router decides which models run from the <em>input</em>, before any member answers, using the
      same <RouterLink to="/sf-client/api/reducers#gate">sf.Gate</RouterLink> construct that powers
      <RouterLink to="/sf-client/api/cascades-gates">cascades and gates</RouterLink> today. Where a
      cascade reads a number on an answer, a router reads a label of the question.
    </p>

    <h2>What is coming</h2>

    <ul>
      <li>
        Keyword routing with <code>sf.RegexClassifier</code>, which labels the question by the first
        matching pattern, with no model call, so a gate can send it to the right branch.
      </li>
      <li>
        Classifier routing with <code>sf.LLMClassifier</code>, which asks one small model for a label
        from a fixed list. Nested gates give an N-way choice.
      </li>
      <li>
        Guards: an outer gate that overrides the router's choice. It can refuse a case with
        <code>sf.fail()</code> or force a stronger branch, and the selector's original label is still
        recorded.
      </li>
      <li>
        Set-valued routing, where a skipped gate inside a <code>sf.Fanout</code> picks a subset of
        experts. An expert that is not picked makes no call.
      </li>
    </ul>

    <p>
      Until then, you can decide <em>after</em> an answer exists with
      <RouterLink to="/sf-client/api/cascades-gates">cascades and gates</RouterLink>, and cap the spend
      of a case with a <RouterLink to="/sf-client/api/budgeted-runs">budgeted run</RouterLink>.
    </p>
  </DocLayout>
</template>
