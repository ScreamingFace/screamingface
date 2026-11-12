# screamingface-docs

The ScreamingFace docs site, a Vue 3 + TypeScript + Vite single-page app served at
[https://docs.screamingface.ai](https://docs.screamingface.ai). It covers the ScreamingFace
Client (install, quickstart, and guides) alongside the url4, Engine, AI gateway, and caching
concepts.

## Stack

- Vue 3 + Vue Router + Pinia
- Vite (dev/build) with `@tailwindcss/vite` (Tailwind CSS v4); theme tokens in `src/style.css`
- `prismjs` for code highlighting, `lucide-vue-next` for icons
- ESLint (with oxlint) + Prettier
- Path alias `@/` → `src/`

## Setup

```sh
npm install
```

## Development

```sh
npm run dev          # start the Vite dev server (hot reload)
```

## Build

```sh
npm run build        # type-check (vue-tsc) + production build
npm run preview      # preview the production build locally
```

## Quality

```sh
npm run type-check   # vue-tsc --noEmit
npm run lint         # oxlint + eslint (auto-fix)
npm run format       # prettier --write src/
```

## Project layout

- `src/App.vue` — shell (`<TheNavbar />` + `<RouterView />`)
- `src/pages/` — route components; `src/router/index.ts` — routes
- `src/components/layout/` — navbar + doc layout; `src/components/ui/` — reusable content components
- `src/composables/` — reusable logic (copy, highlight, doc navigation, carousel)
- `src/stores/` — Pinia stores (theme, code-tab language)
- `src/navigation/` — data files that drive the sidebar + prev/next per section
- `src/lib/` — framework-agnostic helpers
- `src/style.css` — Tailwind import + light/dark theme tokens + prose styling

Type checking uses a single `tsconfig.json` (extends `@vue/tsconfig`), covering `src/**`
and the config files.

## Deployment

`public-docs` is served as a static site from a shared docs VM at
**https://docs.screamingface.ai**. On merge to
`main` touching `public-docs/**`, the GitHub Action
[`deploy-public-docs.yml`](../.github/workflows/deploy-public-docs.yml) builds the site
and `rsync`s `dist/` to the VM, where Caddy serves it (`file_server`). Later merges
redeploy automatically; a manual run is available via the Action's **Run workflow** button.

> **Infra values are not committed** (this repo may be made public). The VM host, user,
> and SSH key are the repo Actions secrets **`DOCS_VM_HOST`** / **`DOCS_VM_USER`** /
> **`DOCS_VM_SSH_KEY`**; the deploy login is shared with the team privately. Fill the
> placeholders below — `<vm-host>`, `<vm-user>`, `<vm-key>` — from those.

- **Served from (on the VM):** `~/screamingface/public-docs/dist`

### SSH access

You need the VM's private key (shared out-of-band). Either pass `-i ~/.ssh/<vm-key>.pem`
on each command, or add a portable alias to your `~/.ssh/config` and use `docs-vm`:

```
Host docs-vm
    HostName <vm-host>
    User <vm-user>
    IdentityFile ~/.ssh/<vm-key>.pem
```

### Manual deploy (one-off, from your machine)

Run in `public-docs/`:

```sh
npm run build
rsync -az --delete -e "ssh -i ~/.ssh/<vm-key>.pem" \
  dist/ <vm-user>@<vm-host>:~/screamingface/public-docs/dist/

# verify it landed
ssh -i ~/.ssh/<vm-key>.pem <vm-user>@<vm-host> 'ls ~/screamingface/public-docs/dist'
```

### Dev preview (the exact prod app, locally)

The VM's Caddy config also serves the same `dist/` on a **loopback-only**
`http://localhost:8080` block — a shared snippet, so it is byte-for-byte the prod app
(same files), just private. Reach it with an SSH tunnel (nothing is
exposed publicly):

```sh
ssh -i ~/.ssh/<vm-key>.pem -N -L 8080:localhost:8080 <vm-user>@<vm-host>
# then open http://localhost:8080
```

### Caddy config (on the VM, `/etc/caddy/Caddyfile`)

A shared snippet imported by both the prod domain and the dev loopback block:

```
(screamingface_docs) {
	root * /home/<vm-user>/screamingface/public-docs/dist
	file_server
	try_files {path} /index.html
	encode gzip
	basicauth {
		<login-email>  <bcrypt-hash>   # caddy hash-password --plaintext '<password>'
	}
}
docs.screamingface.ai { import screamingface_docs }
http://localhost:8080  { import screamingface_docs }
```

Apply with `sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy`.
This VM runs Caddy < 2.8, so the directive is **`basicauth`** (one word), not `basic_auth`.

### Remaining for go-live

- **DNS:** point `docs.screamingface.ai` at the VM (A record → the `DOCS_VM_HOST` value).
  Caddy is already configured (and retrying ACME), so it auto-provisions TLS the moment
  DNS resolves — then `https://docs.screamingface.ai` serves the app.
