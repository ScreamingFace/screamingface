<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const read = `status = sf.credits()        # a fresh read of the connection you run against
status.account.amount_usd    # a Decimal, or None when it's unavailable`

const cached = `sf.credits(refresh=False)    # reuse the last read, up to five minutes old`

const manage = `client = sf.Client()
client.set_credit_management_key("openrouter", api_key="sk-or-v1-…")
client.clear_credit_management_key("openrouter")`
</script>

<template>
  <DocLayout
    title="Credits"
    description="Read how much provider credit you have left: the credits() call and the values it returns."
    :navigation="navigation"
    :version="version"
  >
    <p>
      <code>sf.credits()</code> tells you how much credit you have left with a provider. It reads the
      one connection the engine runs your evaluations against, and <code>client.credits()</code> and
      <code>await async_client.credits()</code> do the same from a Client you hold. In a notebook you
      can also just open the connection card with <code>sf.connect()</code> and read it off each
      provider. It only ever reads, so a low or missing balance won't stop a run. For a walkthrough,
      see
      <RouterLink to="/sf-client/guides/connections#see-your-provider-credit"
        >See your provider credit</RouterLink
      >
      in the Connections guide.
    </p>

    <p>
      Today this works for OpenRouter only. Ask about any other provider and every amount comes back
      <code>unavailable</code>. You need an open Client talking to the engine over a secure
      connection; when a read can't complete, you get <code>unavailable</code> back instead of an
      error.
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="read" />
    </div>

    <h2>credits()</h2>

    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Type</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>provider</code></td>
          <td><code>str</code></td>
          <td>The provider to read. Defaults to <code>"openrouter"</code>.</td>
        </tr>
        <tr>
          <td><code>refresh</code></td>
          <td><code>bool</code></td>
          <td>
            Keyword-only. Leave it <code>True</code> (the default) for a fresh read, or pass
            <code>False</code> to reuse the last read from the five-minute cache.
          </td>
        </tr>
      </tbody>
    </table>

    <p>You can call it as the module function <code>sf.credits()</code> or on either client:</p>

    <ul>
      <li><code>Client.credits(provider="openrouter", *, refresh=True)</code></li>
      <li><code>AsyncClient.credits(provider="openrouter", *, refresh=True)</code></li>
    </ul>

    <div class="not-prose">
      <NbCell :count="2" :code="cached" />
    </div>

    <h2>CreditStatus</h2>

    <p>What one call gives you back: a balance and the allowances for a single connection.</p>

    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Type</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>provider</code></td>
          <td><code>str</code></td>
          <td>The provider this status describes.</td>
        </tr>
        <tr>
          <td><code>account</code></td>
          <td><code>CreditAmount</code></td>
          <td>
            Your OpenRouter account balance. It needs a verified management key; without one it comes
            back <code>unavailable</code> with the reason <code>management_key_required</code>.
          </td>
        </tr>
        <tr>
          <td><code>key</code></td>
          <td><code>CreditAmount</code></td>
          <td>
            The spending cap on the key you run with. It's a limit, not extra credit on top of the
            balance.
          </td>
        </tr>
        <tr>
          <td><code>hosted</code></td>
          <td><code>CreditAmount</code></td>
          <td>
            On the platform this mirrors <code>key</code>, since they're the same limited key. Don't
            add the two together, and note the platform's own account total is never shown.
          </td>
        </tr>
        <tr>
          <td><code>connection_token</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>An opaque 64-character token for the connection the read looked at.</td>
        </tr>
        <tr>
          <td><code>management_key_configured</code></td>
          <td><code>bool</code></td>
          <td>Whether you have a management key stored for this provider.</td>
        </tr>
      </tbody>
    </table>

    <h2>CreditAmount</h2>

    <p>
      One figure in US dollars and when it was read. <code>unlimited</code> means the key sets no
      limit, not that usage is free.
    </p>

    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Type</th>
          <th>Meaning</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><code>status</code></td>
          <td><code>str</code></td>
          <td>
            One of <code>available</code>, <code>stale</code>, <code>unavailable</code>,
            <code>unlimited</code>.
          </td>
        </tr>
        <tr>
          <td><code>amount_usd</code></td>
          <td><code>Decimal&nbsp;|&nbsp;None</code></td>
          <td>
            The dollar figure. It's set for <code>available</code> and <code>stale</code>, and
            <code>None</code> otherwise.
          </td>
        </tr>
        <tr>
          <td><code>as_of</code></td>
          <td><code>datetime&nbsp;|&nbsp;None</code></td>
          <td>When the figure was read. It's <code>None</code> only when <code>unavailable</code>.</td>
        </tr>
        <tr>
          <td><code>reason</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>Why a figure is missing or unlimited. The values are listed below.</td>
        </tr>
      </tbody>
    </table>

    <h3>Status</h3>

    <ul>
      <li>
        <code>available</code>: a fresh figure, with <code>amount_usd</code> and <code>as_of</code>
        set.
      </li>
      <li><code>stale</code>: the last good figure, kept after a read briefly failed.</li>
      <li><code>unavailable</code>: no figure. Check <code>reason</code> for why.</li>
      <li><code>unlimited</code>: the key sets no limit (which isn't the same as free).</li>
    </ul>

    <h3>Reason</h3>

    <ul>
      <li><code>unsupported</code>: the provider doesn't expose credits.</li>
      <li><code>hosted_unavailable</code>: the hosted allowance can't be read here.</li>
      <li><code>not_connected</code>: there's no connection for the provider.</li>
      <li><code>management_key_required</code>: the account balance needs a management key.</li>
      <li><code>account_unverified</code>: the management key isn't verified yet.</li>
      <li><code>credential_rejected</code>: the stored credential was rejected upstream.</li>
      <li><code>lookup_failed</code>: the read didn't complete.</li>
      <li><code>invalid_response</code>: the provider sent back something we couldn't use.</li>
    </ul>

    <h2>Management key</h2>

    <p>
      Reading your OpenRouter <strong>account balance</strong> takes a management key. The engine
      stores it encrypted and never hands it back or logs it. You set and clear it on the Client (not
      through <code>sf</code>), and the notebook connection card offers the same setup. A hosted
      engine turns both down, since all it shows you is the key allowance.
    </p>

    <ul>
      <li>
        <code>Client.set_credit_management_key(provider, *, api_key)</code> verifies the key and
        stores it.
      </li>
      <li><code>Client.clear_credit_management_key(provider)</code> removes it again.</li>
    </ul>

    <div class="not-prose">
      <NbCell :count="3" :code="manage" />
    </div>

    <h2>Links</h2>

    <ul>
      <li>
        <RouterLink to="/sf-client/guides/connections#see-your-provider-credit"
          >Guide: See your provider credit</RouterLink
        >
      </li>
      <li><RouterLink to="/sf-client/api/connections">Connections (API reference)</RouterLink></li>
    </ul>
  </DocLayout>
</template>
