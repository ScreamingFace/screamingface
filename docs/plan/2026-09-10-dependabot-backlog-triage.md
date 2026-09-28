# Dependabot backlog triage — 2026-09-10

**Work item:** OME-1171 · **Ledger:** `docs/work/2026-09-10-OME-1171-dependabot-backlog.md`

18 Dependabot PRs were open, the oldest from 2026-09-01. Ten have been merged. **Eight remain, and
each one needs a decision from its CODEOWNER.** Find your section below; you only need to read
yours.

Two of the remaining PRs carry unauthenticated-RCE advisories and are marked **URGENT**.

## How the split was made

| Bucket | Count | Rule |
|---|---|---|
| Merged | 10 | Lockfile-only transitive bump, no manifest edit, green CI |
| Awaiting owner | 7 | Edits a manifest, moves a framework version, or ships a native binary |
| Needs a replacement PR | 1 | `#803` is red against a deliberate runtime guard |

Nothing platform-side enforces this split. `reviewDecision` is empty and no ruleset or branch
protection requires review, so **`.github/CODEOWNERS` is advisory in this repo** — any of us can
squash any of these today. The split is a choice, not a constraint.

## Why the remaining eight were not simply closed

Closing does not stick. Dependabot recreates a closed PR on its next weekly run unless
`.github/dependabot.yml` gains a matching `ignore:`, and every ignore needs a 1:1 rationale entry
in `.github/dependabot-ignores.yml` whose `blocker.kind` is one of exactly two machine-checkable
kinds — `npm_peer` or `ci_matrix` — audited by the "Dependabot ignore audit" job in
`.github/workflows/repo-checks.yml`.

None of these eight has a blocker that fits that schema. They are not blocked on upstream; they are
waiting on a human. So the options are merge or replace, and there is no third door.

---

## @HupBaHa — aigateway, aigateway-ui, scoreboard, co-owner of `/.github/`

| PR | Change | Why it needs you |
|---|---|---|
| **#862** | **URGENT.** `next` 16.3.2 → 16.3.3, plus js-yaml, fast-uri, nanoid. Edits `package.json` | Fixes two unauthenticated-RCE advisories: GHSA-p293-qw3h-jr36 (Windows-hosted servers) and GHSA-2xp9-vwfh-vxw4 (Image Optimization API, AVIF) |
| #857 | `next` 16.3.2 → 16.3.4, `@testing-library/react`, `@vitejs/plugin-react`, `stylelint`. Edits `package.json` | Moves the build and test toolchain, not just the lock. **Merge after #862** — it supersedes #862's `next` bump |
| #881 | `azure/setup-helm` 4.3.1 → 5.0.1 across 8 workflows | See the note below — lower risk than "major" suggests |

**On #881.** `main` already runs the floating `@v5` in 7 of 8 workflows; only
`analytics-tests.yml:57` is still on `@v4.3.1`. The PR converts all of them to an exact `@v5.0.1`,
so it is mostly a *tightening*. v5's sole breaking change is the node20 → node24 runtime, and
`Render the Helm chart`, `Lint and verify chart wiring` and `chart` all pass on the PR — v5 is
already exercised green.

**Also yours:** OME-1172, the replacement for `#803` (see the `#803` section below). It touches
security logic, so it needs your review specifically.

**Already merged, for your awareness:** `#798` (scoreboard: pydantic 2.13.4 → 2.13.5,
ruff 0.16.4 → 0.16.6, `uv.lock` only).

## @itstauq — screamingface-studio

| PR | Change | Why it needs you |
|---|---|---|
| **#861** | **URGENT.** `next` 16.3.0 → 16.3.3. Edits `package.json` | Same two RCE advisories as #862. Studio sits two patches further behind than aigateway-ui did |
| #863 | `sharp` 0.35.3 → 0.35.4 | Native binary in the image pipeline, with platform-specific optional dependencies — not a pure lock bump in practice |

**Worth knowing about your tree.** Studio's `frontend` (npm) and `src-tauri` (cargo) are
deliberately absent from `.github/dependabot.yml`, pending OME-739. The PRs above reached studio
anyway because Dependabot *security* updates ignore the `directory:` scoping (noted in the
dependabot.yml header under OME-733). Net effect until OME-739 lands: studio receives security PRs
but no routine version PRs, so routine drift accumulates silently.

**Already merged, for your awareness:** `#809` (nltk 3.10.2 → 3.10.3), `#864` (js-yaml 4.3.1 →
4.3.2), `#807` (browserslist 4.28.6 → 4.28.8). All security patches, all lockfile-only.

## @IonesioJunior @keelancj — packages/screamingface

| PR | Change | Why it needs you |
|---|---|---|
| #858 | `litellm` 1.98.0 → 1.100.0, plus cryptography, pydantic, ruff, websockets. Edits `pyproject.toml` | **Highest-risk merge in the backlog** — it changes a hard `==` pin on the *distributed* package |

The pin at `pyproject.toml:51` is `litellm==1.98.0`, inside the `runtime` optional-dependency group.
Moving it changes what every consumer of the published package resolves.

See also **OME-1173**: `apps/aigateway` guards its litellm version explicitly, while this tree pins
a different one with no guard, so the packaged runtime can ship a litellm that aigateway's
hardening was never verified against. Merging #858 helps by coincidence; OME-1173 proposes making
the agreement checkable.

**Already merged, for your awareness:** `#810` (tornado 6.5.7 → 6.5.8 security patch,
`uv.lock` only).

## @IrinaMBejan — public-docs

| PR | Change | Why it needs you |
|---|---|---|
| #879 | `vue-router` 5.2.0 → 5.3.1, `markdown-it` 15.0.0 → 15.0.1, `eslint` 10.9.1 → 10.10.0, `eslint-plugin-vue`, `eslint-plugin-oxlint`, `oxlint` 1.80 → 1.81, `@types/node`, `vue` 3.5.41 → 3.5.42. Edits `package.json` | A router minor plus a linter bump on the public docs site — 8 updates in one group |

**Already merged, for your awareness:** `#860` (nanoid 3.3.17 → 3.3.18 security patch,
`package-lock.json` only).

---

## #803 — do not merge this one; it is being replaced

`#803` bumps `litellm` 1.97.0 → 1.100.0 in `apps/aigateway`. It is the only red PR in the backlog,
and it is red for a good reason: it trips three deliberate tripwires. **The guard is working as
designed.**

**1. The version pin lives in the tests, not the manifest.**
`tests/unit/openai/test_openai_runtime_guard.py:256` and `:342` each assert
`importlib.metadata.version("litellm") == "1.97.0"`. `apps/aigateway/pyproject.toml:12` declares
only `litellm>=1.55`, so the resolver is otherwise free to move — those two asserts are what stops
it. Their failure message says it outright: "re-verify the tuple against the new release before
moving this pin."

**2. Three new callback parameters appeared upstream.**
`tests/unit/core/test_request_hardening.py:210`
`test_litellm_dynamic_callback_parameter_set_is_covered` reads litellm's private
`_supported_callback_params` and found `newrelic_region`, `newrelic_api_key` and
`langfuse_environment` missing from our allowlist.

That allowlist is security logic, not a dependency list. From `request_hardening.py:55-58`:

> every name in litellm's `_supported_callback_params` must appear here, so a client can never turn
> a chat request into a telemetry redirect.

There is **no live vulnerability today** — those three parameters do not exist on the pinned
1.97.0. The guard is precisely what prevents the upgrade from introducing one silently.

Moving the pin properly requires re-verifying 12 guarded globals against 1.100.0 and hand-mirroring
the result into a second list that is deliberately maintained separately (the two sides must be
able to disagree, or the comparison proves nothing), then running the full local gates including
live tests, which CI skips. That is a unit of work, not a rubber stamp — filed as **OME-1172**,
owner @HupBaHa. `#803` closes as superseded once OME-1172 lands.

## Follow-ups filed

| Issue | Owner | What |
|---|---|---|
| OME-1172 | @HupBaHa | Re-verify the LiteLLM runtime guard against 1.100.0, replacing `#803` |
| OME-1173 | @IonesioJunior @keelancj | Make the packaged litellm pin and aigateway's guarded version checkably equal |
| OME-1174 | @sergio-bershadsky @HupBaHa | Pin the helm version in CI — chart rendering currently resolves `latest`, which is already helm v4.2.4 |

## Merged in OME-1171

Ten PRs, all lockfile-only with no manifest edit and green CI at merge time.

| PR | Change | Path |
|---|---|---|
| #811 | tornado 6.5.7 → 6.5.8 (security) | `apps/screamingface-engine/uv.lock` |
| #804 | pydantic, ruff, websockets | `apps/screamingface-engine/uv.lock` |
| #802 | pydantic, ruff | `apps/report-intake/uv.lock` |
| #799 | pydantic, ruff | `packages/url4/uv.lock` |
| #798 | pydantic, ruff | `apps/scoreboard/uv.lock` |
| #810 | tornado 6.5.7 → 6.5.8 (security) | `packages/screamingface/uv.lock` |
| #809 | nltk 3.10.2 → 3.10.3 (security) | `apps/screamingface-studio/runtime/uv.lock` |
| #864 | js-yaml 4.3.1 → 4.3.2 (security) | `apps/screamingface-studio/frontend/package-lock.json` |
| #807 | browserslist 4.28.6 → 4.28.8 (security) | `apps/screamingface-studio/frontend/package-lock.json` |
| #860 | nanoid 3.3.17 → 3.3.18 (security) | `public-docs/package-lock.json` |

Six of those ten sit in trees owned by someone other than the merger. They are listed under each
owner's section above so nobody discovers a merge after the fact.
