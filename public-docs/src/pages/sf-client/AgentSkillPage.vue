<script setup lang="ts">
import DocLayout from '@/components/layout/DocLayout.vue'
import CodeBlock from '@/components/ui/CodeBlock.vue'
import Tabs from '@/components/ui/Tabs.vue'
import ThemedDiagram from '@/components/ui/ThemedDiagram.vue'
import {
  sfClientNavigation as navigation,
  sfClientVersion as version,
} from '@/navigation/sf-client'

const prompt = `Install the ScreamingFace skill for this project.
In Claude Code, run:
  claude plugin marketplace add ScreamingFace/screamingface
  claude plugin install docs@screamingface
In other agents, run:
  npx skills add ScreamingFace/screamingface --skill screamingface
Use one installation method. Then use the screamingface skill when writing code with the screamingface Python package.`

const claudeCode = `claude plugin marketplace add ScreamingFace/screamingface
claude plugin install docs@screamingface`

const otherAgents = `npx skills add ScreamingFace/screamingface --skill screamingface`

const updateClaudeCode = `claude plugin marketplace update screamingface
claude plugin update docs@screamingface`

const updateOtherAgents = `npx skills update`
</script>

<template>
  <DocLayout
    title="Install the agent skill"
    description="Give a coding agent the ScreamingFace Client docs as a skill."
    :navigation="navigation"
    :version="version"
  >
    <p>
      The ScreamingFace skill gives a coding agent the ScreamingFace Client docs: a
      <code>SKILL.md</code> with the rules for writing <code>screamingface</code> code and an index,
      and one Markdown reference for each docs page. It is generated from this site, and its version
      is the docs version, <code>{{ version.label }}</code
      >.
    </p>

    <h2>Copy to your agent</h2>

    <p>Paste this prompt into your coding agent:</p>

    <CodeBlock :code="prompt" language="text" />

    <h2>Install the skill</h2>

    <Tabs :labels="['Claude Code', 'Other agents', 'Manual copy']">
      <template #tab-0>
        <p>Run these commands in a terminal:</p>
        <CodeBlock :code="claudeCode" language="bash" />
        <p>
          The first command adds the marketplace <code>screamingface</code>. The second installs the
          plugin <code>docs</code> from it, which holds the skill <code>screamingface</code>.
        </p>
      </template>
      <template #tab-1>
        <p>Run this command in the project:</p>
        <CodeBlock :code="otherAgents" language="bash" />
        <p>
          The installer asks which agent to install for. It installs into the current project, and
          <code>-g</code> installs for all projects. Without <code>--skill screamingface</code> it
          lists the skills of the repository, which are the repository's own skills and not this
          one.
        </p>
      </template>
      <template #tab-2>
        <p>
          Copy the folder <code>public-docs/agent-skill/skills/screamingface</code> from the
          <a href="https://github.com/ScreamingFace/screamingface" target="_blank" rel="noopener"
            >ScreamingFace repository</a
          >
          into the skills directory of your agent. In Claude Code, that is
          <code>.claude/skills/screamingface</code> in a project.
        </p>
      </template>
    </Tabs>

    <h2>Update the skill</h2>

    <p>In Claude Code, run:</p>
    <CodeBlock :code="updateClaudeCode" language="bash" />
    <p>Claude Code applies the update after a restart. For other agents, run:</p>
    <CodeBlock :code="updateOtherAgents" language="bash" />

    <h2>Read the docs as Markdown</h2>

    <p>
      Every docs page is also served as Markdown at its route with <code>.md</code> added, for
      example <code>/sf-client/installation.md</code>.
      <a href="https://docs.screamingface.ai/llms.txt" target="_blank" rel="noopener"
        ><code>llms.txt</code></a
      >
      lists every page with its description, and
      <a href="https://docs.screamingface.ai/llms-full.txt" target="_blank" rel="noopener"
        ><code>llms-full.txt</code></a
      >
      holds all pages in one file.
    </p>

    <h2>How it is built</h2>

    <ThemedDiagram
      name="agent-skill-docs-to-agent"
      alt="Flow: the docs pages go through a generator that writes the agent skill folder, committed to the repository, and the Markdown endpoints on the docs site. Claude Code installs the skill with claude plugin install, other agents with npx skills add, and any agent can read the Markdown endpoints."
      caption="From docs to agent: the generator writes the skill and the Markdown endpoints from the same pages."
    />

    <p>
      A build reads each page, converts it to Markdown, writes the skill into
      <code>public-docs/agent-skill</code> and writes the endpoints into <code>dist</code>. CI
      regenerates the skill on every change and fails when the committed copy differs.
    </p>

    <h2>Troubleshooting</h2>

    <table>
      <thead>
        <tr>
          <th>Symptom</th>
          <th>Cause</th>
          <th>Fix</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>The installer lists skills that are not ScreamingFace.</td>
          <td><code>--skill</code> is missing.</td>
          <td>Add <code>--skill screamingface</code>.</td>
        </tr>
        <tr>
          <td>The agent does not use the skill.</td>
          <td>The skill is not installed for this agent or project.</td>
          <td>
            Run <code>claude plugin list</code> in Claude Code or <code>npx skills list</code> for
            other agents, then install again.
          </td>
        </tr>
        <tr>
          <td>The agent writes calls that do not exist.</td>
          <td>The skill is older than your <code>screamingface</code> version.</td>
          <td>
            Update the skill. Compare the docs version in <code>SKILL.md</code> with the output of
            <code>pip show screamingface</code>.
          </td>
        </tr>
        <tr>
          <td>A <code>.md</code> address returns the home page.</td>
          <td>The route has no Markdown file.</td>
          <td>Use a route listed in <code>llms.txt</code>.</td>
        </tr>
      </tbody>
    </table>
  </DocLayout>
</template>
