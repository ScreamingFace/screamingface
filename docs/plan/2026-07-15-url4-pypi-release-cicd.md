# Plan — url4 SDK PyPI release CI/CD (OME-465)

Spec: `docs/spec/2026-07-15-url4-pypi-release-cicd-spec.md`. Already on `main` (not this
unit): release-please registration of `packages/url4`, the `url4-v*` tag, `url4-tests.yml`.

## Step 1 — Package metadata (`packages/url4/`)

- **`pyproject.toml`** — extend `[project]`:
  - `readme = "README.md"`, `license = "Apache-2.0"`, `license-files = ["LICENSE"]`
  - `authors = [{ name = "OpenMined" }]`
  - `keywords = ["ai", "llm", "ensemble", "dag", "expression-protocol", "url4"]`
  - `classifiers`: Development Status :: 3 - Alpha; Intended Audience :: Developers;
    Programming Language :: Python :: 3 / 3.12 / 3.13; Operating System :: OS Independent;
    Typing :: Typed
  - `[project.urls]`: Homepage `https://screamingface.ai`, Repository
    `https://github.com/ScreamingFace/screamingface`, Issues `.../issues`
  - Do **not** add a `License ::` classifier (PEP 639 SPDX field supersedes it).
- **`README.md`** (new) — title, one-liner, install (`pip install url4`), a runnable
  quickstart (from `src/url4/__init__.py`'s docstring), a short feature list, license line.
- **`LICENSE`** (new) — copy of the repo-root Apache-2.0 file.
- **`src/url4/py.typed`** (new, empty) — PEP 561 marker.

## Step 2 — Publish workflow `.github/workflows/release-url4.yml` (new)

- `on: push: tags: ["url4-v*"]` + `workflow_dispatch` (input `tag`).
- `permissions: contents: read` at top.
- `verify` job → outputs `version`; asserts tag version == pyproject version
  (awk the version, mirror `release-aigateway.yml`).
- `build` job (`needs: verify`, `working-directory: packages/url4`) → `uv build --out-dir
  dist` + `uvx twine check --strict dist/*` → `actions/upload-artifact` (`if-no-files-found:
  error`).
- `publish-pypi` job (`needs: [verify, build]`) → `environment: {name: pypi, url:
  https://pypi.org/p/url4}`, `permissions: {id-token: write}`, download artifact to `dist/`,
  `pypa/gh-action-pypi-publish@release/v1` (attestations default-on).

## Step 3 — Harden `.github/workflows/url4-tests.yml`

- `test` job: add `strategy.matrix.python-version: ["3.12", "3.13"]`,
  `fail-fast: false`; parametrize `setup-python` + the test-report name.
- New `build` job: checkout → setup-uv → `uv build --out-dir dist` (in `packages/url4`) →
  `uvx twine check --strict dist/*`.
- Leave coverage gate at 95% and the `cost` job unchanged.

## Step 4 — Dependabot `.github/dependabot.yml`

- Add a `uv` `updates` entry: `directory: "/packages/url4"`, weekly,
  `open-pull-requests-limit: 5`, group `url4-python: patterns ["*"]`.

## Verification (Step 5)

Run in `packages/url4`:
- `uv sync`
- `uv run ruff check` · `uv run ruff format --check` · `uv run pyright`
- `uv run pytest --cov=url4 --cov-fail-under=95 -q`
- `uv build --out-dir dist` → `uvx twine check --strict dist/*` → `unzip -l` the wheel and
  confirm `url4/py.typed` is present.
- Validate JSON/YAML: parse `release-please-config.json`, `.release-please-manifest.json`,
  `.github/dependabot.yml`; `actionlint` on both workflows if available.

## Step 6 — Commit / PR

- Conventional commits, body `Refs: OME-465`; never commit to `main`.
- Suggested split: `feat(url4): PyPI metadata + py.typed`; `ci(url4): PyPI publish
  workflow + packaging gate + dependabot`.
- Open PR; body: summary, test plan, the owner-action checklist (PyPI trusted publisher +
  `pypi` Environment), CODEOWNERS reviewers (`@sergio-bershadsky @HupBaHa`).
- Fill ledger Outcome; set OME-465 → In Review; update tasks mirror.

## Owner actions (post-merge, pre-publish)

1. PyPI: reserve `url4`, add Trusted Publisher (repo `ScreamingFace/screamingface`, workflow
   `release-url4.yml`, environment `pypi`).
2. GitHub: create `pypi` Environment.
