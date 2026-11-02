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

const replayError = `import screamingface as sf

try:
    replay = sf.evaluate(pinned_cache="<pinned-cache-id>")
except sf.ReproductionError as exc:
    print(exc.code, exc.reproduction.outcome, exc.reproduction.reason)
else:
    reproduction = replay.candidates.only.reproduction
    if reproduction is not None:
        print(reproduction.outcome, reproduction.reason)`
</script>

<template>
  <DocLayout
    title="Errors"
    description="What the Client raises, and the warnings it emits when a run completes with a caveat."
    :navigation="navigation"
    :version="version"
  >
    <p>
      Service and evaluation failures inherit from <code>ScreamingFaceError</code>. Its subclasses
      say where the failure happened and carry a machine-readable code alongside the message.
      Invalid argument types and values can instead raise <code>TypeError</code> or
      <code>ValueError</code>.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="catchAll" />
    </div>

    <h2>The hierarchy</h2>

    <CodeBlock
      code="Exception
└── ScreamingFaceError
    ├── AuthenticationError
    ├── EngineUnavailableError
    ├── ExecutionError
    ├── LeaderboardError
    ├── PlanningError
    ├── ProviderConnectionError
    └── ReproductionError

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
          <td><code>ReproductionError</code></td>
          <td>
            A published capture cannot be replayed, or the Engine did not confirm replay mode.
            <code>.reproduction</code> carries the refusal or failure verdict. No report is
            returned.
          </td>
        </tr>
        <tr>
          <td><code>LeaderboardError</code></td>
          <td>
            A <RouterLink to="/sf-client/api/leaderboards">leaderboard</RouterLink> operation could
            not be completed safely.
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
      The subclasses share a diagnostic shape, so you can branch on a stable value rather than on
      message text.
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

    <h2>Replay errors and verdicts</h2>

    <CodeBlock :code="replayError" language="python" />
    <table>
      <thead>
        <tr>
          <th>Exception and code</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>ReproductionError: not_reproducible</code></td>
          <td>
            No run starts. <code>exc.reproduction.outcome</code> is <code>"not_reproducible"</code>;
            its reason is <code>"partial"</code> or <code>"unknown"</code> for a missing capture
            status, pinned cache id or benchmark revision.
          </td>
        </tr>
        <tr>
          <td><code>ReproductionError: replay_unsupported</code></td>
          <td>
            The Engine did not confirm replay mode. <code>exc.reproduction.outcome</code> is
            <code>"failed"</code> and its reason is <code>"replay_unsupported"</code>. The Client
            tries to stop an unacknowledged run; if that stop fails, it also emits an
            <code>EvaluationWarning</code>.
          </td>
        </tr>
        <tr>
          <td><code>PlanningError: partial_replay_unavailable</code></td>
          <td>
            The Engine cannot rebuild the published recipe and a compatible subset for
            <code>limit=n</code>. No run starts; use a full replay.
          </td>
        </tr>
        <tr>
          <td><code>LeaderboardError: invalid_leaderboard</code></td>
          <td>
            The board returned a malformed response, including a score id that differs from the
            requested one. No replay starts.
          </td>
        </tr>
      </tbody>
    </table>
    <p>
      A completed replay that differs from the published score returns
      <code>result.reproduction.outcome == "failed"</code>. Read <code>.reason</code> and
      <code>.missed_cases</code>; this verdict does not itself raise an exception. Partial replays
      and captures with no public score return <code>reproduction=None</code>. Wrong seed, recipe or
      id combinations raise <code>ValueError</code> before execution. Other service and execution
      errors still propagate.
    </p>

    <h2>Warnings</h2>

    <p>
      A warning usually accompanies a completed run whose quality needs attention. Replay can also
      warn when every case misses an unsubmitted capture, or when an unacknowledged run could not be
      stopped. <code>EvaluationWarning</code> is the one the Client emits, and it subclasses
      <code>UserWarning</code>, so it appears in normal warning output and
      <code>warnings.simplefilter</code> controls it.
    </p>

    <Note>
      Read the warning alongside the report or exception. Promote warnings to errors if your
      workflow must stop on these caveats.
    </Note>

    <div class="not-prose">
      <NbCell :count="4" :code="warn" />
    </div>
  </DocLayout>
</template>
