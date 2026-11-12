# Install the agent skill

Source: https://docs.screamingface.ai/sf-client/agent-skill

Give a coding agent the ScreamingFace Client docs as a skill.

The ScreamingFace skill gives a coding agent the ScreamingFace Client docs: a `SKILL.md` with the rules for writing `screamingface` code and an index, and one Markdown reference for each docs page. It is generated from this site, and its version is the docs version, `0.1.12`.

## Copy to your agent

Paste this prompt into your coding agent:

```
Install the ScreamingFace skill for this project.
In Claude Code, run:
  claude plugin marketplace add ScreamingFace/screamingface
  claude plugin install docs@screamingface
In other agents, run:
  npx skills add ScreamingFace/screamingface --skill screamingface
Use one installation method. Then use the screamingface skill when writing code with the screamingface Python package.
```

## Install the skill

**Claude Code**

Run these commands in a terminal:

```bash
claude plugin marketplace add ScreamingFace/screamingface
claude plugin install docs@screamingface
```

The first command adds the marketplace `screamingface`. The second installs the plugin `docs` from it, which holds the skill `screamingface`.

**Other agents**

Run this command in the project:

```bash
npx skills add ScreamingFace/screamingface --skill screamingface
```

The installer asks which agent to install for. It installs into the current project, and `-g` installs for all projects. Without `--skill screamingface` it lists the skills of the repository, which are the repository's own skills and not this one.

**Manual copy**

Copy the folder `public-docs/agent-skill/skills/screamingface` from the [ScreamingFace repository](https://github.com/ScreamingFace/screamingface) into the skills directory of your agent. In Claude Code, that is `.claude/skills/screamingface` in a project.

## Update the skill

In Claude Code, run:

```bash
claude plugin marketplace update screamingface
claude plugin update docs@screamingface
```

Claude Code applies the update after a restart. For other agents, run:

```bash
npx skills update
```

## Read the docs as Markdown

Every docs page is also served as Markdown at its route with `.md` added, for example `/sf-client/installation.md`. [`llms.txt`](https://docs.screamingface.ai/llms.txt) lists every page with its description, and [`llms-full.txt`](https://docs.screamingface.ai/llms-full.txt) holds all pages in one file.

## How it is built

[Diagram: Flow: the docs pages go through a generator that writes the agent skill folder, committed to the repository, and the Markdown endpoints on the docs site. Claude Code installs the skill with claude plugin install, other agents with npx skills add, and any agent can read the Markdown endpoints.]

From docs to agent: the generator writes the skill and the Markdown endpoints from the same pages.

A build reads each page, converts it to Markdown, writes the skill into `public-docs/agent-skill` and writes the endpoints into `dist`. CI regenerates the skill on every change and fails when the committed copy differs.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| The installer lists skills that are not ScreamingFace. | `--skill` is missing. | Add `--skill screamingface`. |
| The agent does not use the skill. | The skill is not installed for this agent or project. | Run `claude plugin list` in Claude Code or `npx skills list` for other agents, then install again. |
| The agent writes calls that do not exist. | The skill is older than your `screamingface` version. | Update the skill. Compare the docs version in `SKILL.md` with the output of `pip show screamingface`. |
| A `.md` address returns the home page. | The route has no Markdown file. | Use a route listed in `llms.txt`. |
