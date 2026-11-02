<script setup lang="ts">
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import Note from '@/components/ui/Note.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const statusCode = `import screamingface as sf

sf.analytics.status()`
const statusOut = `{'choice': 'unknown', 'enabled': False, 'scope': 'installation', 'installation_id': None}`

const enableCode = `sf.analytics.enable()
sf.analytics.status()`
const enableOut = `Analytics enabled.
{'choice': 'accepted', 'enabled': True, 'scope': 'installation',
 'installation_id': 'ddc5b9cd-1be2-4bfe-92c7-406e6188823d'}`

const resetCode = `sf.analytics.reset_identifier()['installation_id']`
const resetOut = `'0e71bc42-0e66-406d-9689-ed76e309524f'`

const disableCode = `sf.analytics.disable()
sf.analytics.status()`
const disableOut = `Analytics disabled.
{'choice': 'declined', 'enabled': False, 'scope': 'installation', 'installation_id': None}`

const sessionCode = `sf.analytics.enable(persist=False)
sf.analytics.status()`
const sessionOut = `Analytics enabled.
{'choice': 'accepted', 'enabled': True, 'scope': 'session', 'installation_id': None}`

const processCode = `sf.analytics.disable(process_only=True)`
const processOut = `Analytics disabled for this process.`

const shell = `screamingface analytics status
screamingface analytics enable
screamingface analytics reset-id
screamingface analytics disable`
const shellOut = `{"choice": "accepted", "enabled": true, "scope": "installation", "installation_id": "16e3dd46-093e-4070-b583-6533f73c4267"}`

const doNotTrack = `DO_NOT_TRACK=1 python -c "import screamingface as sf; sf.analytics.enable(); print(sf.analytics.status())"`
const doNotTrackOut = `Couldn't enable analytics; tracking remains off.
{'choice': 'unknown', 'enabled': False, 'scope': 'installation', 'installation_id': None}`
</script>

<template>
  <DocLayout
    title="Analytics"
    description="Opt-in usage analytics: what they are, the four calls that control them, and what turns them off."
    :navigation="navigation"
    :version="version"
  >
    <p>
      <code>sf.analytics</code> controls the Client's optional analytics. Analytics are off until
      you opt in. No account identity or login is involved: events carry a random installation ID
      and a random session ID. The setup notice lists what an event holds: the start and outcome of
      an evaluation or a submission, coarse timing, the SDK version, and whether the run was local
      or hosted. It states that no prompt, response, score, credential or email is sent.
    </p>

    <Note>
      Opting out or resetting the identifier does not delete past events. The events follow the
      retention of the analytics provider, and no fixed deletion deadline is promised.
    </Note>

    <h2>The setup notice</h2>

    <p>
      When the choice is <code>unknown</code>, the Client prints a one-time notice in an interactive
      terminal or a Jupyter notebook. The notice names <code>sf.analytics.enable()</code> and
      <code>sf.analytics.disable()</code>. It never waits for input. A process that continues
      without choosing leaves analytics off, and the notice does not record a choice.
    </p>

    <h2>Functions</h2>

    <table>
      <thead>
        <tr>
          <th>Signature</th>
          <th>What it does</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>sf.analytics.status()</code></td>
          <td>
            Returns a <code>dict</code> with the saved choice and the effective state. It creates no
            file and no identifier.
          </td>
        </tr>
        <tr>
          <td><code>sf.analytics.enable(*, persist=True)</code></td>
          <td>
            Opts in and prints <code>Analytics enabled.</code>. With <code>persist=False</code>, the
            opt-in lasts for this process only. When <code>DO_NOT_TRACK</code> is set, it prints
            <code>Couldn't enable analytics; tracking remains off.</code>
          </td>
        </tr>
        <tr>
          <td><code>sf.analytics.disable(*, process_only=False)</code></td>
          <td>
            Stops tracking, saves the choice <code>declined</code>, discards the installation ID and
            prints <code>Analytics disabled.</code>. With <code>process_only=True</code>, it stops
            tracking in this process and saves nothing.
          </td>
        </tr>
        <tr>
          <td><code>sf.analytics.reset_identifier()</code></td>
          <td>
            Rotates the installation ID of an accepted installation, so old and new activity do not
            join, and returns the status. It changes nothing when analytics are off or session-only.
          </td>
        </tr>
      </tbody>
    </table>

    <h2>Status</h2>

    <table>
      <thead>
        <tr>
          <th>Key</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>choice</code></td>
          <td>
            <code>'unknown'</code> before a choice, <code>'accepted'</code> or
            <code>'declined'</code>. An opt-in with <code>persist=False</code> reads
            <code>'accepted'</code>.
          </td>
        </tr>
        <tr>
          <td><code>enabled</code></td>
          <td>
            <code>True</code> only when the choice is <code>'accepted'</code> and neither
            <code>DO_NOT_TRACK</code> nor <code>disable(process_only=True)</code> is in effect.
          </td>
        </tr>
        <tr>
          <td><code>scope</code></td>
          <td>
            <code>'installation'</code> for a saved choice, <code>'session'</code> for
            <code>persist=False</code>, <code>'browser'</code> in Colab.
          </td>
        </tr>
        <tr>
          <td><code>installation_id</code></td>
          <td>
            The random installation ID while analytics are enabled, otherwise <code>None</code>.
            Always <code>None</code> in Colab and in a session-only opt-in.
          </td>
        </tr>
      </tbody>
    </table>

    <div class="not-prose">
      <NbCell :count="1" :code="statusCode"><NbTextOut :text="statusOut" /></NbCell>
      <NbCell :count="2" :code="enableCode"><NbTextOut :text="enableOut" /></NbCell>
      <NbCell :count="3" :code="resetCode"><NbTextOut :text="resetOut" /></NbCell>
      <NbCell :count="4" :code="disableCode"><NbTextOut :text="disableOut" /></NbCell>
      <NbCell :count="5" :code="sessionCode"><NbTextOut :text="sessionOut" /></NbCell>
      <NbCell :count="6" :code="processCode"><NbTextOut :text="processOut" /></NbCell>
    </div>

    <h2>Where the choice is saved</h2>

    <p>
      A saved choice lives in <code>~/.screamingface/analytics.json</code>, independent of the
      runtime data directory. <code>SCREAMINGFACE_ANALYTICS_CONFIG</code> names another path. The
      file is replaced atomically, so a reader sees the old or the new document, never a partial
      write. A missing, unreadable or invalid file reads as <code>unknown</code>.
    </p>

    <h2>screamingface analytics</h2>

    <p>
      The shell command runs the same controls and prints the resulting status as one line of JSON.
      <code>reset-id</code> is <code>reset_identifier()</code>.
    </p>

    <CodeBlock :code="shell" language="bash" />

    <div class="not-prose">
      <NbCell count="out" :code="'screamingface analytics enable'"
        ><NbTextOut :text="shellOut"
      /></NbCell>
    </div>

    <h2>DO_NOT_TRACK</h2>

    <p>
      Analytics are off while <code>DO_NOT_TRACK</code> has any value other than an empty string,
      <code>0</code>, <code>false</code>, <code>no</code> or <code>off</code>. The variable wins
      over a saved opt-in: <code>status()['enabled']</code> is <code>False</code> and
      <code>enable()</code> does not turn analytics on.
    </p>

    <div class="not-prose">
      <NbCell count="shell" :code="doNotTrack" lang="bash"
        ><NbTextOut :text="doNotTrackOut"
      /></NbCell>
    </div>

    <h2>Colab</h2>

    <p>
      In Google Colab the choice lives in the browser, not on disk. The Client reads and writes it
      through a bridge to the notebook page.
    </p>

    <ul>
      <li>
        <strong>Status:</strong> <code>scope</code> is <code>'browser'</code>,
        <code>installation_id</code> is <code>None</code>, and the dict adds
        <code>persistent_id</code> (the browser's saved ID) and <code>pending</code> (a browser
        round trip is in flight).
      </li>
      <li>
        <strong><code>enable()</code>:</strong> Waits up to 3 seconds for the browser to confirm. A
        timeout leaves analytics off. <code>enable(persist=False)</code> raises
        <code>ValueError</code>, because a Colab opt-in needs browser consent.
      </li>
      <li>
        <strong><code>disable()</code>:</strong> Saves the decline in the browser. The printed
        message says when the browser is still saving or could not save.
      </li>
      <li>
        <strong>Setup notice:</strong> The browser reports its saved state when the notice would
        appear.
      </li>
    </ul>
  </DocLayout>
</template>
