# PRD: user documentation for the chat endpoint

**Source:** ans:Q1, ans:Q2, ans:Q13, ans:Q14 · **Priority:** P2
**Lifecycle:** planned · **Owner:** unassigned

## 1. Summary

No user flow in the product drives this unit. It makes the feature usable: a page in
`public-docs` and a section in the Engine README.

## 2. Content that the page must have

- The base URL (`https://<engine>/v1` and `http://127.0.0.1:9108/v1`) `[stated ans:Q7]`.
- The two forms of `model`, with a way to get the Candidate URL4 of a recipe from the SDK
  `[stated ans:Q16]`.
- Hosted access: send the header `Cf-Access-Token`, and get the token with
  `cloudflared access token -app=<engine url>` `[stated ans:Q2]`
  `[existing packages/screamingface/README.md:1626]`
  `[existing packages/screamingface/README.md:1638]`. The token has a limited life.
- One example for each: the OpenAI Python SDK (`default_headers`), pi (`headers` with a command),
  and opencode (`headers`) `[stated ans:Q1]`.
- The limits, in plain words:
  - Sampling fields and `tool_choice` are ignored. Set them in the recipe `[stated ans:Q14]`.
  - `usage` is the sum of the whole ensemble, so a context meter in an agent reads high. The real
    context size is `screamingface.final_step.usage` `[stated ans:Q13]`.
  - With tools, the recipe must end in a model step (a model, a synthesizer or a writer). A
    static reducer at the end, such as Vote, is refused `[stated ans:Q9]` `[stated ans:Q18]`.
  - With tools, each `sf.Cascade` and each Gate that ends in a reducer step is refused. Add a
    final model stage (`cascade >> model`), or use a Gate with recipe branches. With
    `cascade >> model`, the final model answers also when the Cascade abstains
    `[stated ans:Q27]`.
  - A call served from the shared cache counts 0 tokens in `usage` `[stated ans:Q26]`.
  - `cost_usd` is null when one call of the run has no price. A recipe with a classifier step
    has no price today.
  - Evaluation runs and chat requests share the limit of 24 runs in flight for each user. An
    agent can get "too many requests" while a large evaluation of the same user runs
    `[stated ans:Q25]`.
  - The OpenAI SDK needs an `api_key` value. Any text works, because the Engine ignores it.
  - The stream is buffered `[stated ans:Q4]`.
  - Each turn runs the full ensemble, so the cost of a turn is the cost of the ensemble.
  - Web search is on by default for each step whose model route can search: an OpenRouter route
    always, another route only when the Engine has a search key. The conversation text of that
    step then goes to the search provider. Set `web_search=false` on a model in the recipe to
    turn it off `[stated ans:Q30]`. With tools, the final step searches only when the provider
    does the search itself.
  - A step that searches with the Engine tools can try to call one of your tools by name. It
    cannot, and the step can then fail. Set `web_search=false` on the members when you use
    tools.
  - Claude Code and Codex need other formats, which are not available yet `[stated ans:Q12]`.

## 3. Acceptance criteria

**DOC-S1** Each code example on the page runs against a local stack in the docs test lane
`[proposed]`.
**DOC-S2** The page states each limit above `[proposed]`.
**DOC-S3** The page is in STE and follows the docs style of the repo `[proposed]`.

## 4. Out of scope

An SDK helper that writes client config files.

## 5. TDD plan

| # | Test | Level | Source | Risk | Note |
|---|---|---|---|---|---|
| DOC-1 | `openai_sdk_example_runs_on_local_stack` | E2E | [proposed] | M×M | shares the CC-22 fixture |
| DOC-2 | `page_lists_every_documented_limit` | unit | [proposed] | L×M | text check in `public-docs` tests |
