---
title: A dev checkout's local stack always runs the live url4 and apps
ticket: OME-1335
status: approved
date: 2026-09-25
---

# A dev checkout's local stack always runs the live url4 and apps

## Outcome

Inside the ScreamingFace monorepo, `screamingface up` serves the checkout's live
`packages/url4` and `apps/*` code, whether or not the dev venv was synced since the last
url4 change. If an outdated installed copy is ever imported anyway, boot stops at once and
names the stale module and the reinstall command. It no longer crashes minutes into
startup with `No module named 'url4.cli._config'`.

## Why the current guard fails

OME-1001 made checkout mode work by reordering `sys.path` (`activate()`) so the live
source directories come before `site-packages`. Two gaps defeat it:

1. **The copy exists at all.** `scripts/runtime_build_hook.py` force-includes url4 and the
   three apps into every wheel, including the **editable** wheel `uv sync` builds for the
   dev venv. Those copies are frozen at build time, and `uv sync` does not rebuild the
   editable install when url4 changes. Seen on 2026-09-25: a Sep 18 url4 copy, while
   `url4.cli._config` landed on Sep 22 (`cba47c0f`).
2. **Activation runs too late for url4.** `import screamingface` loads the SDK, which
   imports url4 (`_evaluation/model.py`). That runs before `cli.main()` can activate, and
   Python never re-resolves a module already in `sys.modules`.
3. **Verification can't see it.** `verify_live_modules` accepts any file under the
   checkout root. The dev venv lives under the root (`packages/screamingface/.venv`), so
   the stale copy passes, and the boot log claims "runtime source: checkout".

## Contracts

### Editable build contract

For an editable build, the hook ships **no copies**. It ships one `.pth` file listing the
four live source directories (the same list `source._SOURCE_DIRECTORIES` names). Python
then resolves url4 and the apps to the checkout from the first import, the SDK's
included. Checkout resources (`url4.toml`, the scoreboard portal and artifacts) already
fall back to the checkout in `_runtime/config.py`, so they need no copy either.

Wheel and sdist builds are unchanged: they still vendor everything (`check_distribution.py`
keeps pinning that).

### Rebuild contract

`[tool.uv] cache-keys` includes `scripts/runtime_build_hook.py`, so a hook change rebuilds
existing dev venvs on the next `uv sync`, with no manual reinstall.

### Verification contract

In checkout mode, a runtime module counts as live only if its file sits under one of the
four source directories. A file anywhere else, including a venv inside the checkout,
fails boot with an error naming the module, its file, and
`uv sync --reinstall-package screamingface`.

### Studio sidecar contract

The Studio desktop sidecar (`apps/screamingface-studio/runtime`) is the one editable
install that is not a dev venv. Its PyInstaller spec used to read `url4.toml` and the
scoreboard portal and artifacts from the editable install's site-packages copies, which
no longer exist. It now gets them from `bundled_runner_config()` and `scoreboard_assets()`,
the same lookups the runtime uses, which resolve to the checkout. The frozen bundle must
be the same as main's: the same modules and the same `_runtime` data files.

### Partial-checkout contract

An editable build refuses a checkout that is missing any of the four source directories,
with the release build's `runtime distribution sources are missing` error. Python skips a
`.pth` entry that does not exist, so without this check a partial checkout would install
cleanly and then fail on the first `import url4`.

## Boundaries

- No change to the published wheel or sdist, the public API, or app code. The Studio
  sidecar spec is the one file outside `packages/screamingface` that changes.
- One new dev-only dependency: `hatchling` (already the build backend), so a test can
  build a real editable wheel.
- `activate()` and `child_environment()` stay as they are. They still order the path
  correctly for any other install layout.
