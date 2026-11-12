---
ticket: OME-1853
stack: repo
status: done
started: 2026-11-09
finished: 2026-11-12
---

# security-tab-burndown — bump every live lock file's security alerts in one PR, re-seal the three Benchmarks the bumps change

## Intent

On 2026-11-06 the Security tab showed 392 Dependabot and 14 CodeQL alerts. 131 are ghosts on
two deleted trees, 67 repeat Engine pins in the Studio runtime lock, and the rest spread over
11 live lock files. The owner asked for one PR, not four (2026-11-09): every fixable alert on a
live manifest moves in this unit, the three Benchmarks whose Cases change are re-sealed, and the
two tracked build artifacts that carry 4 CodeQL alerts go.

Owner rulings (2026-11-09, this session): bump Pillow and pypdf for security and re-seal the
three Case Digests while keeping the three published revisions (no official leaderboard runs on
them yet); one PR for the whole sweep.

## Planned changes

- Engine: Dependabot #1566 cherry-picked (`pypdf` 6.21.4, `certifi`, `filelock` 4.2.1, `pillow`
  13.0.0), then `nltk` 3.10.4, `nbconvert` 7.17.2, `opentelemetry-api`, `tornado` 6.6; the three
  rows in `screamingface_engine_inspect/prepare.py` re-sealed; the three fingerprint literals.
- aigateway: `PyJWT==2.15.0` in `pyproject.toml`; `certifi`, `filelock` 4.2.9,
  `opentelemetry-api` in the lock. LiteLLM stays 1.102.1: the runtime-guard tripwire pins it
  and moving it is its own unit under `OME-1320`.
- SDK (`packages/screamingface`): `filelock`, `nltk`, `tornado`; `nltk` and `langdetect` pinned
  exactly, as the Engine pins them. url4: nothing left to move once the branch was re-locked on
  main (main already had `tornado` 6.6).
- scoreboard, report-intake, analytics: `certifi` (and `opentelemetry-api` on scoreboard).
- Studio runtime lock: re-locked with `aiohttp`, `certifi`, `filelock`, `nltk`,
  `opentelemetry-api`, `pillow`, `setuptools`; the re-lock also catches the lock up with the
  SDK's own exact pins (`litellm==1.104.2`, `datasets==5.1.0`), which the stale lock had not.
- Studio frontend: `next` 16.4.2 (package.json pin moved), `undici`, `vite`; aigateway-ui and
  public-docs: `vite` and the audit-fixable transitives. Studio Tauri: `zip` 9.0.5 via
  `tauri-plugin-updater` 2.14.1, `rustls` 0.23.46.
- `apps/desktop/out/main/index.js` and `apps/desktop/out/preload/index.js` deleted: legacy
  build artifacts nothing imports, source of 4 CodeQL "certificate validation disabled" alerts.
- `docs/tasks/2026-11-09-OME-1853-security-tab-burndown.md` mirror.

## Test plan

- Engine seals: re-seal inside a linux/amd64 Engine image built from this branch; each
  `case_digest` must equal the value CI printed on #1566; CI's strict image build is the judge.
- Per touched tree, its own lane: Engine `tests/unit/inspect` with the inspect extra; aigateway
  `tests/unit`; SDK `tests` with the notebook extra; url4 and scoreboard through the pre-push
  gates; Studio frontend `tsc --noEmit` + `next build`; Studio Tauri `cargo check --locked`;
  public-docs `vite build`; `uv lock --check` on every uv lock.
- The 9 url4 "polynomial regex" CodeQL alerts: time each flagged pattern on a 16 KiB
  pathological input (uvicorn's request-line cap) to decide whether they are real.

## Acceptance

- Every high or critical Dependabot alert on a live manifest has its fix version in the lock,
  except the three with a named reason (LiteLLM guard pin, filelock capped below 4 by
  litellm 1.104.2's own `filelock<4.0` requirement in the SDK and Studio runtime, glib 0.20 is
  a major in the Tauri lock).
- The strict image build confirms all three re-sealed Benchmarks; the published ids hold.
- The desktop build artifacts are gone from `main`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, minus the url4 lock (main already had its one bump); 13 lock or
  manifest files, 2 Python files, 2 deletions, `CLAUDE.md` and the `working-in-this-repo` skill
  (the `apps/desktop` paragraphs), ledger and mirror.
- **Commits:** `c9a084ff6` chore(deps): bump the screamingface-engine-python-security group
  (Dependabot's `8efd60b74`, cherry-picked unchanged); `4c0b2f918` fix(screamingface-engine):
  re-seal MMMU, MathVista and cyse4 after the security bumps; then the sweep commit
  `fix(repo): bump every live lock file's security alerts`.
- **Gates:** re-seal inside a linux/amd64 Engine image (OrbStack, Rosetta): cyse4 587 Cases
  `096a744d…` in 317 s, mathvista 1000 `9a4a85c3…` in 100 s, mmmu_multiple_choice 847
  `419ddea2…` in 689 s, every case_digest equal to CI's printed value; CI's strict image build
  green on `4c0b2f918` (run 42568527013 attempt 2; attempt 1 failed only on WorldSense's source
  download, an external HTTP error). Engine `tests/unit/inspect` with the inspect extra:
  2,936 passed before the nltk/nbconvert/tornado bumps, 2,936 passed after. aigateway
  `tests/unit`: 7,772 passed, 2 skipped. SDK `tests` with the notebook extra: 4,374 passed, 35 skipped, 1 failed (`test_notebook_display_failure_cannot_hide_an_already_saved_score`, which fails identically on main's own lock in this environment, so pre-existing and not the bumps). Studio frontend: tsc
  clean, `next build` static export OK on 16.4.2. Studio Tauri: `cargo check --locked` 0 errors
  (295 crates). public-docs: `vite build` OK. `uv lock --check` clean on all 8 uv locks. ruff,
  ruff format, pyright clean on the two touched Python files. url4 regex timing at 16 KiB:
  slowest 0.48 ms (`PATH_RE` on 16,384 slashes), the rest under 0.2 ms.
- **Deviations:** LiteLLM not bumped in aigateway (tripwire, `OME-1320`); filelock stays 3.32.7
  in the SDK and Studio runtime (litellm 1.104.2 requires `filelock<4.0`; huggingface-hub only
  asks for `>=3.10`, my first wording blamed the wrong package); npm moderates left where the
  fix is a major of a parent (minimatch, postcss-selector-parser, @vitest/mocker): aigateway-ui
  8, Studio frontend 11, public-docs 13; glib 0.20 skipped. The Studio runtime lock now follows
  the SDK's `litellm==1.104.2`, which main's SDK already pinned (`d61550b3e`).
- **Review round 1 (Sergey, Dmitry, 2026-11-10):** (1) OpenTelemetry had only moved on
  scoreboard: `--upgrade-package opentelemetry-api` alone cannot move it because sdk, exporter
  and proto pin each other; re-locked the family together to 1.45.2 in Engine, aigateway and
  Studio runtime. (2) `next` pinned exact `16.4.2`. (3) Tauri: zip 9.0.5 declares Rust 1.88 and
  tauri-plugin-updater 2.14.1 declares 1.90 while `Cargo.toml` said 1.77.2; raised
  `rust-version` to 1.90 (owner's call; release builds already use stable). (4) Under litellm
  1.104.2 the gateway strip list missed `arize_error_sampling_rate` and
  `arize_success_sampling_rate`; added both with a behaviour test, RED (3 failures) then GREEN
  (32 passed). (5) IFEval's grader imports nltk without declaring it: added
  `scorer_dependencies=("nltk",)`, fingerprint `ada07458…` → `a2159cda…`, published id held.
  (6) Corrected the filelock wording above. Lanes after the round: Engine inspect 2,936 passed,
  gateway unit 7,773 passed, 2 skipped; `cargo check --locked` 0 errors at rust-version 1.90.
- **Review round 2 (Tauquir, Sergey, 2026-11-12):** merged main (91 commits) and re-locked every
  lock from main's copy with uv 0.13.7, the version main's locks carry (`revision = 5`; the first
  push had re-written them with 0.12.21's `revision = 3`), so each uv lock now differs from main
  only in the bumped rows; the url4 lock is untouched. (1) ZeroBench, added on main under Pillow
  12.3.0, replayed inside the linux/amd64 image on Pillow 13.0.0: `case_digest` 7b1b680a… and
  `case_set_digest` 4f5c4adb… came back EQUAL to the declared values (100 Cases, 29 s), so no
  re-seal and no fingerprint move; its pictures are 101 JPEGs and 7 PNGs that Pillow 13 writes
  byte-identically. (2) Pillow pinned exactly in the Engine's `benchmarks` extra beside pypdf;
  nltk and langdetect pinned exactly in the Engine base dependencies and the SDK's runtime extra.
  (3) IFEval declares langdetect too (`scorer_dependencies=("nltk", "langdetect")`), fingerprint
  a2159cda… → 29daaba0…, published id 1cba769e… held; the `scorer_dependencies` field doc now
  describes the alarm, not the id. (4) The fingerprint test's held block now holds all four moved
  rows with "published id HELD at <id> (fingerprint was <old>)" wording. (5) Studio sidecar on
  litellm 1.104.2: the gateway's `tests/unit/core/test_request_hardening.py` (strip-list coverage
  against litellm's `_supported_callback_params`) and `tests/unit/openai/test_openai_runtime_guard.py`
  ran inside the Studio runtime's frozen env: 78 passed; the only two failures are the 1.102.1
  version tripwires themselves, and with that one assertion bypassed both inventory sweeps pass
  (every guarded global exists on 1.104.2). (6) Found while re-running the Engine inspect lane:
  Dependabot's minor group (#1736, merged 2026-11-11) moved `antlr4-python3-runtime` to 4.13.2,
  which sympy 1.14's `parse_latex` refuses (`ImportError … version 4.11`), so MATH's symbolic scorer
  fails on every Case on main and MATH's fingerprint moved; main's inspect lane shows the failing
  test but the step pipes through `tee` and reports success. Restored 4.11.1 with a WHY comment;
  MATH's fingerprint is back at its literal. (7) Four Fidelity Records are stale by fingerprint
  (ifeval, inspect-mmmu_multiple_choice, inspect-mathvista, inspect-cyse4_threat_intelligence):
  not re-audited here, listed for the owner below. (8) `CLAUDE.md` and the routing skill no
  longer describe `apps/desktop` as present. Lanes after the round: see Gates below.
- **Owner-verify:** (1) dismiss the 131 ghost alerts on `apps/server` and `apps/url4-cloud`
  with reason "manifest removed from main"; (2) dismiss the 9 url4 regex CodeQL alerts as
  tolerable, citing the timing above; (3) read the HuggingFace runtime-guard log line CodeQL
  flags and decide; (4) Dependabot closes its superseded PRs (#1566, #1563, #1565, #1567, #1601,
  #1562, #1496, #1543, #1564, #1474, #1503) once these versions reach `main`; (5) decide alert
  #1180 (litellm proxy salt key, fixed in 1.102.2): dismiss as unreachable (the gateway never runs
  LiteLLM Proxy) or move the guard tripwire to 1.102.2; (6) one signed-update plus launch smoke
  test on a built Studio before release, since the Cargo re-lock moves the Tauri core a minor
  (tauri 2.11.5→2.12.5, wry, tao, minisign-verify 0.3.0) with no CI lane; (7) re-audit the four
  stale Fidelity Records (`just engine fidelity-check` names them) or file the re-audit; (8) the
  Engine inspect lane's `| tee` masks a red pytest (main's run on 2d9c18632 failed MATH's sympy
  test and reported success): CI wiring, owner's; (9) whether OME-1853 gets per-component
  sub-issues (repo rule 8) is the owner's call.
