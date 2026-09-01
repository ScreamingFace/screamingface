<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import NbCell from '@/components/nb/NbCell.vue'
import NbTextOut from '@/components/nb/NbTextOut.vue'
import Note from '@/components/ui/Note.vue'
import { SF_ENGINE_URL } from '@/lib/engine'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const shortcut = `import screamingface as sf

report = sf.evaluate(
    sf.Model("openrouter/anthropic/claude-haiku-4.5"),
    benchmark="ifeval",
    limit=1,
)
sf.close()`

const explicit = `import screamingface as sf

with sf.Client(engine_url="${SF_ENGINE_URL}") as client:
    report = client.evaluate(
        sf.Model("openrouter/anthropic/claude-haiku-4.5"),
        benchmark="ifeval",
        limit=1,
    )`

const lazy = `import screamingface as sf

client = sf.Client(engine_url="${SF_ENGINE_URL}")
client.engine_url, client.closed, client.authenticated`
const lazyOut = `('${SF_ENGINE_URL}', False, False)`

const env = `export SCREAMINGFACE_ENGINE_URL=http://127.0.0.1:9108
export SCREAMINGFACE_SCOREBOARD_URL=http://127.0.0.1:9106`

const configure = `import screamingface as sf

sf.configure(
    engine_url="http://127.0.0.1:9108",
    scoreboard_url="http://127.0.0.1:9106",
)
report = sf.evaluate(candidates, benchmark="draco", limit=1)
sf.close()`

const multi = `import screamingface as sf

candidate = sf.Model("openrouter/anthropic/claude-haiku-4.5")

with (
    sf.Client(engine_url="${SF_ENGINE_URL}") as hosted,
    sf.Client(engine_url="http://127.0.0.1:9108") as local,
):
    hosted_report = hosted.evaluate(candidate, benchmark="ifeval", limit=1)
    local_report = local.evaluate(candidate, benchmark="ifeval", limit=1)`

const asyncCode = `import asyncio
import screamingface as sf

async def main():
    async with sf.AsyncClient(engine_url="${SF_ENGINE_URL}") as client:
        return await client.evaluate(
            sf.Model("openrouter/anthropic/claude-haiku-4.5"),
            benchmark="ifeval",
            limit=1,
        )

report = asyncio.run(main())`

const transport = `import screamingface as sf

client = sf.Client(
    engine_url="${SF_ENGINE_URL}",
    http_transport=my_transport,          # any httpx.BaseTransport
)`
</script>

<template>
  <DocLayout
    title="Clients"
    description="The default Client behind sf.*, and when to build your own."
    :navigation="navigation"
    :version="version"
  >
    <p>There are two ways to call the SDK, and both use the same interface.</p>

    <p>
      Most of the time you'll reach for the <strong>module-level shortcuts</strong>:
      <code>sf.evaluate(...)</code>, <code>sf.connect(...)</code>, and the rest. They're the
      shortest to write, which is why the
      <RouterLink to="/sf-client/first-fusion">Quickstart</RouterLink> and every notebook use
      them.
    </p>

    <p>
      When a script grows into something you ship, construct an explicit
      <strong><code>Client</code></strong> instead. It takes a little more code, but it hands you
      the Client's lifecycle, lets you point at a second engine, and works with your own event loop.
    </p>

    <p>
      These aren't two different SDKs. Every shortcut runs against a single <code>Client</code> the
      package creates and holds for you. The only real question this page answers is
      <em>who owns that Client: you, or the package</em>.
    </p>

    <h2>What you can do with it</h2>

    <ul>
      <li>Call the SDK with no setup through the process-wide default Client.</li>
      <li>Point that default at a local or alternate engine, by environment or in code.</li>
      <li>Construct your own <code>Client</code> when you need to own its lifecycle.</li>
      <li>Run against more than one engine at once, or over <code>await</code>.</li>
    </ul>

    <h2>The two forms, side by side</h2>

    <p>The same evaluation, written both ways. The shortcut lets the package hold the Client:</p>

    <CodeBlock :code="shortcut" language="python" />

    <p>The explicit form hands the Client to a <code>with</code> block that closes it for you:</p>

    <CodeBlock :code="explicit" language="python" />

    <table>
      <thead>
        <tr>
          <th>Concern</th>
          <th><code>sf.*</code> shortcuts</th>
          <th><code>sf.Client</code> / <code>sf.AsyncClient</code></th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Construction</td>
          <td>Implicit, on the first call that needs it</td>
          <td>You call the constructor</td>
        </tr>
        <tr>
          <td>How many</td>
          <td>One, shared across the process</td>
          <td>As many as you build</td>
        </tr>
        <tr>
          <td>Configuration</td>
          <td>
            <code>SCREAMINGFACE_ENGINE_URL</code> / <code>SCREAMINGFACE_SCOREBOARD_URL</code>, or
            <code>sf.configure(...)</code>
          </td>
          <td>Constructor keyword arguments</td>
        </tr>
        <tr>
          <td>Lifecycle</td>
          <td><code>sf.close()</code> (or <code>sf.configure()</code> swaps it)</td>
          <td>
            <code>with</code> / <code>close()</code>; async <code>async with</code> /
            <code>await aclose()</code>
          </td>
        </tr>
        <tr>
          <td>Async</td>
          <td>Synchronous only</td>
          <td><code>AsyncClient</code></td>
        </tr>
        <tr>
          <td>Custom transports</td>
          <td>Not available</td>
          <td>
            <code>http_transport</code> / <code>scoreboard_transport</code> /
            <code>run_transport</code>
          </td>
        </tr>
        <tr>
          <td>Login state</td>
          <td>Shared by the whole process</td>
          <td>Held per Client</td>
        </tr>
      </tbody>
    </table>

    <h2>The default Client</h2>

    <p>
      <code>sf.evaluate()</code>, <code>sf.connect()</code> and <code>sf.disconnect()</code> all run
      against one <code>Client</code> the package builds
      <strong>the first time you call one of them</strong>, and reuses forever after. Nothing is
      created at <code>import</code>, and constructing a Client opens no connection either. The
      first call that needs the engine is the first one that talks to it:
    </p>

    <div class="not-prose">
      <NbCell :count="1" :code="lazy"><NbTextOut :text="lazyOut" /></NbCell>
    </div>

    <p>
      Left alone, that default points at the hosted development engine. Point it somewhere else in
      one of two ways. Set the environment before the first call, which suits a local engine you
      already export elsewhere:
    </p>

    <div class="not-prose">
      <NbCell :count="2" :code="env" />
    </div>

    <p>Or configure it in code, which also closes and replaces any default already built:</p>

    <div class="not-prose">
      <NbCell :count="3" :code="configure" />
    </div>

    <p>
      <code>sf.configure(...)</code> takes only <code>engine_url</code> and
      <code>scoreboard_url</code>. For anything more, construct a <code>Client</code> yourself.
      <code>sf.close()</code> closes the default and forgets it, so the next shortcut builds a fresh
      one; it is the tidy end to a script.
    </p>

    <Note>
      Because the default is one object for the whole process, its login state is shared too: one
      <RouterLink to="/sf-client/guides/connections">login</RouterLink> covers every later
      <code>sf.*</code> call. That is convenient in a notebook and surprising in a server handling
      several users, which is the reason to build your own Client below.
    </Note>

    <h2>Build your own Client</h2>

    <p>
      Constructing a <code>Client</code> gives you the object directly. Prefer a
      <code>with</code> block so it closes on the way out, which is the form to reach for in a
      script or a service:
    </p>

    <CodeBlock :code="explicit" language="python" />

    <p>
      Owning the Client is what lets you hold <strong>more than one at a time</strong>: a hosted
      engine and a local one, each with its own address, login and connections:
    </p>

    <CodeBlock :code="multi" language="python" />

    <p>
      The full surface (properties, <code>login()</code> / <code>logout()</code>, the catalogue
      accessors) lives on the
      <RouterLink to="/sf-client/api/clients">Clients API reference</RouterLink>. A closed Client
      raises rather than reconnecting silently, so a <code>with</code> block is safer than a bare
      constructor when the Client is short-lived.
    </p>

    <h2>Async</h2>

    <p>
      <code>AsyncClient</code> offers the same interface over <code>await</code> and returns the
      same value types. <code>evaluate()</code>, <code>connect()</code>, <code>login()</code> and
      the rest are awaited; the properties are not, and cleanup is <code>async with</code> or
      <code>await client.aclose()</code>:
    </p>

    <CodeBlock :code="asyncCode" language="python" />

    <Note>
      There is deliberately <strong>no <code>await sf.evaluate(...)</code></strong
      >. A single process-wide async Client would bind its connection pool to one event loop. That
      is a footgun the moment a second loop, a notebook re-run, or a server worker appears. So the
      async path has no module-level shortcut: you construct an <code>AsyncClient</code> and own its
      lifecycle, every time.
    </Note>

    <h2>Custom transports</h2>

    <p>
      The constructor accepts <code>http_transport</code>, <code>scoreboard_transport</code> and
      <code>run_transport</code>: the seam for tests and proxies. A mock transport lets a test drive
      the Client with no network at all. These are constructor-only: there is no way to reach them
      through the <code>sf.*</code> path, which is another reason a test suite builds its own
      Client.
    </p>

    <CodeBlock :code="transport" language="python" />

    <h2>One process, one shared Client</h2>

    <p>
      The default is a single instance, built once behind a lock and reused, so
      <code>sf.*</code> calls that happen to overlap share it rather than racing to create two. That
      sharing is exactly what makes it a poor fit for isolation: separate work that must not share a
      login, a connection pool, or an engine wants a separate <code>Client</code>. Give each thread,
      each event loop, or each tenant its own, and close it when that work is done.
    </p>

    <h2>When to use each</h2>

    <table>
      <thead>
        <tr>
          <th>Reach for <code>sf.*</code></th>
          <th>Build a <code>Client</code></th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Notebooks, the REPL, one-off scripts</td>
          <td>Libraries and services you ship</td>
        </tr>
        <tr>
          <td>One engine for the whole process</td>
          <td>More than one engine at once</td>
        </tr>
        <tr>
          <td>Straight-line synchronous code</td>
          <td>Async code, or concurrency that needs isolation</td>
        </tr>
        <tr>
          <td>Configuration by environment</td>
          <td>Tests that inject a transport</td>
        </tr>
      </tbody>
    </table>

    <h2>See also</h2>

    <ul>
      <li>
        <RouterLink to="/sf-client/api/clients"
          ><code>Client</code>, <code>AsyncClient</code> and connections: API reference</RouterLink
        >
      </li>
      <li>
        <RouterLink to="/sf-client/guides/connections">Connections</RouterLink> — logging in and
        connecting a provider through whichever Client you chose
      </li>
      <li>
        <a
          href="https://github.com/ScreamingFace/screamingface/blob/main/packages/screamingface/examples/01_client_tour.ipynb"
          target="_blank"
          rel="noopener"
          >Companion notebook: <code>01_client_tour.ipynb</code></a
        >
      </li>
    </ul>
  </DocLayout>
</template>
