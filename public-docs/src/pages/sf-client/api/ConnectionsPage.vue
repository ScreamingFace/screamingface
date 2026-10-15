<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import NbCell from '@/components/nb/NbCell.vue'
import {
  sfClientReferenceNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const panel = `panel = sf.connect()
panel.connections`
</script>

<template>
  <DocLayout
    title="Connections"
    description="The provider-connection values: Connection, the OAuth flows, and the interactive panel."
    :navigation="navigation"
    :version="version"
  >
    <p>
      The values the connections API hands back — from <code>sf.connections</code> /
      <code>client.connections</code> and
      <RouterLink to="/sf-client/api/modules">sf.connect() / sf.disconnect()</RouterLink>. For the
      walkthrough, see the
      <RouterLink to="/sf-client/guides/connections">Connections guide</RouterLink>.
    </p>

    <p>
      A hosted engine takes no provider keys of its own: <code>connect(provider, api_key=…)</code>
      and <code>disconnect(provider)</code> raise <code>ProviderConnectionError</code> with the code
      <code>connection_method_unsupported</code>, and <code>list()</code> reports the providers the
      OpenMined team has enabled for your account. On a local engine
      <code>login()</code> raises <code>AuthenticationError</code>.
    </p>

    <h2>Connection</h2>

    <p>Sanitized provider state as the engine reports it.</p>

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
          <td>The provider id.</td>
        </tr>
        <tr>
          <td><code>display_name</code></td>
          <td><code>str</code></td>
          <td>Its human-readable name.</td>
        </tr>
        <tr>
          <td><code>auth_methods</code></td>
          <td><code>tuple[str, ...]</code></td>
          <td>The methods it offers: <code>api_key</code>, <code>oauth</code>, or both.</td>
        </tr>
        <tr>
          <td><code>status</code></td>
          <td><code>str</code></td>
          <td>
            One of <code>not_connected</code>, <code>pending</code>, <code>connected</code>,
            <code>needs_reauth</code>, <code>error</code>.
          </td>
        </tr>
        <tr>
          <td><code>auth_method</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>The method currently in use, when connected.</td>
        </tr>
        <tr>
          <td><code>account_label</code></td>
          <td><code>str&nbsp;|&nbsp;None</code></td>
          <td>The connected account, where the provider reports one.</td>
        </tr>
      </tbody>
    </table>

    <h2>OAuthFlow</h2>

    <p>
      The pending browser authorization returned by
      <code>connect(provider, method="oauth")</code>.
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
          <td><code>provider</code></td>
          <td><code>str</code></td>
          <td>Which provider is being authorized.</td>
        </tr>
        <tr>
          <td><code>authorize_url</code></td>
          <td><code>str</code></td>
          <td>Open this to authorize.</td>
        </tr>
        <tr>
          <td><code>expires_in</code></td>
          <td><code>int</code></td>
          <td>Seconds the flow stays valid.</td>
        </tr>
        <tr>
          <td><code>status</code></td>
          <td><code>str</code></td>
          <td><code>pending</code> until it resolves.</td>
        </tr>
        <tr>
          <td><code>wait(*, poll_interval=0.5, timeout=None)</code></td>
          <td><code>Connection</code></td>
          <td>Block until the browser flow completes, then return the <code>Connection</code>.</td>
        </tr>
        <tr>
          <td><code>cancel()</code></td>
          <td><code>Connection</code></td>
          <td>Abandon the flow.</td>
        </tr>
        <tr>
          <td><code>expired</code></td>
          <td><code>bool</code></td>
          <td>Whether the authorization window has passed.</td>
        </tr>
      </tbody>
    </table>

    <h2>AsyncOAuthFlow</h2>

    <p>
      The async form of <code>OAuthFlow</code>: <code>await flow.wait(...)</code> and
      <code>await flow.cancel(...)</code>; the same fields and the same <code>expired</code> check.
    </p>

    <h2>ConnectionPanel</h2>

    <p>
      An engine-scoped connection view with optional notebook controls, returned by
      <code>connect()</code> with no arguments.
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
          <td><code>engine</code></td>
          <td><code>str</code></td>
          <td>The engine origin the panel is bound to.</td>
        </tr>
        <tr>
          <td><code>connections</code></td>
          <td><code>tuple[Connection, ...]</code></td>
          <td>Every provider the engine advertises, connected or not.</td>
        </tr>
        <tr>
          <td><code>authenticated</code></td>
          <td><code>bool</code></td>
          <td>Whether a hosted-engine login is in effect.</td>
        </tr>
        <tr>
          <td><code>authenticating</code></td>
          <td><code>bool</code></td>
          <td>Whether a login is in progress.</td>
        </tr>
        <tr>
          <td><code>refresh()</code></td>
          <td><code>tuple[Connection, ...]</code></td>
          <td>Re-read connections from the engine and return them.</td>
        </tr>
        <tr>
          <td><code>widget()</code></td>
          <td></td>
          <td>The notebook widget for interactive connect/disconnect.</td>
        </tr>
      </tbody>
    </table>

    <div class="not-prose">
      <NbCell :count="1" :code="panel" />
    </div>
  </DocLayout>
</template>
