# aigateway-ui Guardrails

@AGENTS.md

- **BFF only.** Every call to aigateway's `/v1/admin` surface happens server-side — a server
  action or a route handler. `next.config.ts` is `output: "standalone"` and must stay that way;
  a static export has no server and cannot do this. Modules that reach aigateway carry
  `import "server-only"` so a client-component import fails the build rather than shipping the
  admin API's address to the browser.
- **The allowlist is not here.** `AIGATEWAY_ADMIN_EMAILS` lives in aigateway, which is the sole
  authority. This app never keeps a copy, never gates on an email itself, and renders whatever
  the API returns — a 403 becomes the not-an-admin page.
- **API keys are write-only.** Submitted, never rendered back, never logged, never round-tripped
  through a form's default value. aigateway returns nothing derived from the key: the
  pair-addressed credential API's `masked_key_hint` is always `null`.
- **`X-User-Email` is read from the incoming request, never constructed.** It arrives from Envoy
  after Cloudflare Access verified it. Do not accept it as a query parameter, a cookie, or user
  input of any kind.
- **No OAuth sign-in.** Credentials attached here are static provider API keys. An OAuth
  connection made elsewhere is listed and can be detached, but this console never starts a flow.
- **Design law is the `screamingface-design` skill — SFDS v2**, vendored at
  `src/brand/tokens/tokens.css` from `brand.screamingface.ai`. (This replaced the OpenMined Design
  System in OME-716; an owner decision reversed by an owner decision. Do not reintroduce OMDS.)
- **This console is the `app` register, and that is the whole design brief.** v2 ships two:
  `[data-brand="marketing"]` swaps the accent family to gold, and everything else — the default —
  takes **blue**. So `--accent-*` (blue) carries every interaction, `--success-*` marks a healthy
  account, `--danger-*` marks destructive actions, and **`--brand-*`/`--gain-*` (gold) appear
  nowhere**: gold is "rationed to the win", and an admin console has no win. `design-system.test.ts`
  asserts this; do not weaken it to land a change.
- **`--gain` is a trap.** The v1→v2 bridge keeps it resolving, but it now resolves to **gold**
  where v1 had it green. A surface using it to mean "success" silently changed meaning. Use
  `--success-*`.
- **No serif, no radius, no shadow, no gradient.** Parastoo is display/marketing-only and is not
  loaded; radius is `0` everywhere (`--radius-window` is terminal chrome, which this app lacks);
  v2 spends its one shadow on the terminal window, so elevation here reads from the seam between
  `--bg` / `--surface` / `--surface-2`.
- **Never hardcode a color.** Literal palette values live only in `src/brand/tokens/tokens.css`;
  every other file references a token via `var(--…)`. `npm run lint:css` makes this a merge
  blocker, not a suggestion. If a color you need does not exist, the fix goes **upstream into the
  system**, not into the vendored copy — that is v2's own round-trip rule.
- **Never hardcode a font stack either.** It is invisible to the colour gate, which is how
  `Consolas, Monaco, "Andale Mono"…` survived in two files under the previous system. Use
  `--f-sans` / `--f-mono`; `design-system.test.ts` enforces it.
- **The vendored file carries one documented divergence** (four font families aliased to
  `next/font` CSS variables). Re-syncing means re-applying it and bumping the version string in
  `src/brand/README.md`.
- **`npm ci`, never `npm install`,** in gates and CI — it installs from the lockfile and fails on
  drift. `npm install` would silently rewrite the lock and hide it.
