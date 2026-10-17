<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const catchAll = `import screamingface as sf

try:
    report = sf.evaluate(recipe, benchmark="ifeval", limit=1)
except sf.ScreamingFaceError as exc:
    print(exc.code, exc.retryable, exc.hint)`

const attrs = `e = sf.PlanningError("boom", code="model_unavailable", permanent=True)
e.code, e.retryable, e.permanent, e.hint`
const attrsOut = `('model_unavailable', False, True, None)`

const real = `client.models.get("antigravity/gemini-3-flash")`
const realOut = `ProviderConnectionError: Antigravity profile 'default' is not connected`

const warn = `import warnings

with warnings.catch_warnings():
    warnings.simplefilter("error", sf.EvaluationWarning)
    report = sf.evaluate(recipe, benchmark="draco", limit=1)`
</script>

<template>
  <DocLayout
    title="Errors"
    description="What the Client raises, and the warnings it emits when a run completes with a caveat."
    :navigation="navigation"
    :version="version"
  >
    <p>
      Everything the Client raises on purpose inherits from <code>ScreamingFaceError</code>, so one
      <code>except</code> catches the lot. Six subclasses say where the failure happened, and each
      carries a machine-readable code alongside its message.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="catchAll" />
    </div>

    <h2>The hierarchy</h2>

    <CodeBlock
      code="Exception
└── ScreamingFaceError
    ├── AuthenticationError
    ├── CachePullError           (sf.cache)
    ├── EngineUnavailableError
    ├── ExecutionError
    ├── LeaderboardError
    ├── PlanningError
    └── ProviderConnectionError

Warning
└── UserWarning
    └── EvaluationWarning"
      language="text"
    />

    <h2>Errors</h2>

    <table>
      <thead>
        <tr>
          <th>Class</th>
          <th>Raised when</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>ScreamingFaceError</code></td>
          <td>
            Never directly. It is the base for expected failures at the public interface, and the
            one to catch when you do not care which.
          </td>
        </tr>
        <tr>
          <td><code>PlanningError</code></td>
          <td>
            An evaluation could not be resolved or validated safely, so nothing ran and nothing was
            charged. A route the engine does not carry, or a benchmark id that does not exist.
          </td>
        </tr>
        <tr>
          <td><code>ExecutionError</code></td>
          <td>A run reached the engine and ended without a valid report.</td>
        </tr>
        <tr>
          <td><code>EngineUnavailableError</code></td>
          <td>The configured engine could not be reached at all.</td>
        </tr>
        <tr>
          <td><code>AuthenticationError</code></td>
          <td>
            The engine rejected caller authentication. On a hosted engine this usually means
            <code>login()</code> is needed.
          </td>
        </tr>
        <tr>
          <td><code>ProviderConnectionError</code></td>
          <td>
            A provider connection could not be read or updated safely, including a key the provider
            refuses.
          </td>
        </tr>
        <tr>
          <td><code>LeaderboardError</code></td>
          <td>
            A <RouterLink to="/sf-client/api/leaderboards">leaderboard</RouterLink> operation could
            not be completed safely.
          </td>
        </tr>
        <tr>
          <td><code>CachePullError</code></td>
          <td>
            A <RouterLink to="/learn/caching">community-cache pull</RouterLink> stopped before its
            last page. It lives in <code>sf.cache</code>. Its <code>result</code> says how far the
            pull got, and the rows already loaded stay. Its <code>code</code> names the reason:
            <code>runtime_missing</code> (install the <code>[runtime]</code> extra),
            <code>local_gateway_missing</code> or <code>local_gateway_outdated</code> (start
            <code>screamingface up</code> once), <code>revision_mismatch</code> (upgrade
            <code>screamingface</code> to match the hosted engine), or
            <code>community_cache_unavailable</code> (the hosted engine kept failing; call the pull
            again in the same process to continue).
          </td>
        </tr>
      </tbody>
    </table>

    <p>
      <code>PlanningError</code> is the one worth distinguishing: it means the run never started, so
      the fix is to change the candidate, benchmark or configuration and try again at no cost.
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="real"><NbTextOut :text="realOut" /></NbCell>
    </div>

    <h2>What an error carries</h2>

    <p>
      The six subclasses share a diagnostic shape, so you can branch on a stable value rather than
      on message text.
    </p>

    <table>
      <thead>
        <tr>
          <th>Attribute</th>
          <th>Type</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>code</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>
            Stable identifier such as <code>model_unavailable</code>. Match on this, never on
            <code>message</code>.
          </td>
        </tr>
        <tr>
          <td><code>message</code> · <code>user_message</code></td>
          <td><code>str</code></td>
          <td>What went wrong, and the form intended for display.</td>
        </tr>
        <tr>
          <td><code>retryable</code></td>
          <td><code>bool</code></td>
          <td>
            Whether the same call could plausibly succeed again. The inverse of
            <code>permanent</code>.
          </td>
        </tr>
        <tr>
          <td><code>permanent</code></td>
          <td><code>bool&nbsp;|&nbsp;None</code></td>
          <td>Whether retrying is pointless.</td>
        </tr>
        <tr>
          <td><code>hint</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>A suggested next step, where one applies.</td>
        </tr>
        <tr>
          <td><code>status</code></td>
          <td><code>int&nbsp;|&nbsp;None</code></td>
          <td>The HTTP status behind the failure, when there was one.</td>
        </tr>
        <tr>
          <td><code>details</code></td>
          <td><code>object</code></td>
          <td>Structured context, such as which model routes were missing.</td>
        </tr>
      </tbody>
    </table>

    <div class="not-prose">
      <NbCell :count="3" :code="attrs"><NbTextOut :text="attrsOut" /></NbCell>
    </div>

    <h2>Warnings</h2>

    <p>
      A warning means the run <em>completed</em>. It produced a report you can read, but something
      about its quality needs attention. <code>EvaluationWarning</code> is the one the Client emits,
      and it subclasses <code>UserWarning</code>, so it appears in normal warning output and
      <code>warnings.simplefilter</code> controls it.
    </p>

    <Note>
      A warning does not invalidate a report. It means the score is less well supported than the
      same benchmark would normally give. Promote it to an error if that matters to you.
    </Note>

    <div class="not-prose">
      <NbCell :count="4" :code="warn" />
    </div>
  </DocLayout>
</template>
