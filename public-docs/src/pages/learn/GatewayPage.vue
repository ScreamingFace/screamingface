<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import { learnNavigation as navigation } from '@/navigation/learn'
</script>

<template>
  <DocLayout
    title="AI gateway"
    description="Where your provider keys live, encrypted, and the one endpoint the engine calls to reach every model provider."
    :navigation="navigation"
  >
    <p>
      The <strong>AI gateway</strong> is the component that actually reaches model providers, and
      the place your provider credentials are stored. The
      <RouterLink to="/learn/engine">engine</RouterLink> never calls a provider directly and never
      holds a raw key: it calls the gateway, and the gateway reaches OpenRouter, Anthropic, and the
      rest.
    </p>

    <h2>One endpoint, every provider</h2>

    <p>
      It is a LiteLLM-based gateway that exposes a single, OpenAI-shaped endpoint. The engine sends
      one request shape and the gateway routes it to the right provider, so adding a provider does
      not change how the engine calls out.
    </p>

    <h2>Where your keys live</h2>

    <p>
      A key you connect is handed to the gateway once, validated, and stored
      <strong>encrypted at rest</strong> (AES-256-GCM) as credential blobs. It is never returned to
      the engine or the Client, and never written into your notebook. The master key that unlocks
      them, <code>AIGATEWAY_SECRET_KEY</code>, is never stored alongside the data and never logged,
      and no OS keychain is involved.
    </p>

    <p>
      This is why the gateway is the system's credential boundary: everything above it reasons about
      a <RouterLink to="/sf-client/guides/connections">connection</RouterLink>, its provider and
      status, without ever seeing the secret behind it.
    </p>

    <h2>Providers are plugins</h2>

    <p>
      Every provider the gateway can reach is a <strong>plugin</strong>. Each one adapts a provider,
      OpenRouter, Anthropic, the Codex and Gemini CLIs, Hugging Face, and so on, to the gateway's
      single OpenAI-shaped interface, so supporting a new provider means adding a plugin, not
      changing the engine or the Client.
    </p>

    <p>
      Plugins are enabled per deployment, and the set that is turned on is exactly what the engine
      advertises: it is the list you see when you call <code>sf.connect()</code> or
      <RouterLink to="/sf-client/guides/connections">read your connections</RouterLink>. A route
      whose plugin is off never appears, so a missing provider is usually a disabled plugin rather
      than a bad key.
    </p>

    <p>
      A provider's plugin can be switched off. <code>screamingface up</code> enables the OpenRouter
      plugin for you. If you set <code>AIGW_OPENROUTER_ENABLED=false</code>, OpenRouter no longer
      appears among the providers a local engine advertises,
      <code>sf.connect("openrouter", …)</code> raises <code>unknown_provider</code>, and an
      evaluation of an OpenRouter route raises <code>model_not_found</code>.
    </p>

    <h2>Running it</h2>

    <p>
      On a hosted engine the gateway runs for you. If you run the engine yourself,
      <code>screamingface up</code> starts the gateway too, with its own SQLite database in the data
      directory, and needs no migration step. The
      <RouterLink to="/sf-client/installation">Installation</RouterLink> guide has the commands.
    </p>
  </DocLayout>
</template>
