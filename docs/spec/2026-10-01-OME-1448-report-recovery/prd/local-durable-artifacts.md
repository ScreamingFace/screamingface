# PRD: Keep local result artifacts across a reboot

**Source:** ans:Q1 · **Priority:** P1
**Lifecycle:** existing (characterize + delta) · **Owner:** @ionesio

## 1. Summary and user story

As a researcher on the local stack, I want spilled results to stay on disk after a reboot, so
that a recovery record still points at real bytes for the full 48 hours. `[stated ans:Q1]`
The ticket's F3 says "Ubuntu wipes TMPDIR on reboot". `[stated prompt]`

## 2. Background and constraints

- "A + D + local dir … a durable local artifact folder (~/.screamingface/artifacts), so a reboot
  does not delete results (F3)." `[stated ans:Q1]`
- "The 1 MiB inline cap … and the 48 h local sweep are unchanged." `[stated prompt]` The real
  default inline cap is 512 KiB (`job_env.py:430`, OME-949). This PRD keeps both values unchanged.
- OME-929 lesson: the writer (runner) and the reader (App) must read the same folder, or a
  redemption returns 404 after the money is spent.
  `[existing apps/screamingface-engine/src/screamingface_engine/job_env.py:359]`

### 2.1 Current behavior

- `screamingface up` builds the Engine with `EngineSettings(aigateway_base_url=…)` and a
  `run_env` copied from `os.environ`, plus the runner config, the gateway URL, and the asset
  folder. It does not set the artifact folder.
  `[existing packages/screamingface/src/screamingface/_runtime/server.py:246]`
- So both sides fall back to `$TMPDIR/screamingface-engine/artifacts`.
  `[existing apps/screamingface-engine/src/screamingface_engine/job_env.py:370]`
- The App reads `settings.artifacts_dir`.
  `[existing apps/screamingface-engine/src/screamingface_engine/app.py:282]`
  The run side reads `URL4_CLOUD_ARTIFACTS_DIR` from its env.
  `[existing apps/screamingface-engine/src/screamingface_engine/job_env.py:359]`
- TTL is 48 h, swept at App start and every hour.
  `[existing apps/screamingface-engine/src/screamingface_engine/config.py:124]`

**Delta:** this PRD changes only `packages/screamingface` (`_runtime/config.py`, `_runtime/server.py`).
No Engine code changes.
1. `RuntimeConfig.artifacts_dir` returns `<data_dir>/artifacts`. `[proposed]`
2. `_build_apps` sets both `EngineSettings(artifacts_dir=…)` and
   `run_env[job_env.ARTIFACTS_DIR]` to that one value, **unless** `URL4_CLOUD_ARTIFACTS_DIR` is
   already in `os.environ`. When it is, both sides use the user's value, as today. `[proposed]`
3. The folder is created with mode `0700`, because it holds prompts and answers. `[proposed]`

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**LA-H1. Durable folder.** `[stated ans:Q1]`
Given `screamingface up` with no `URL4_CLOUD_ARTIFACTS_DIR`,
When a run spills a result,
Then the file is in `<data_dir>/artifacts/<sha256>`, and `GET /artifacts/<sha256>` returns it.

**LA-H2. Survives a restart.** `[stated ans:Q1]`
Given a spilled result, and `screamingface down` then `screamingface up` within 48 h,
When the SDK fetches it, Then it is served.

### 3.2 Error paths

**LA-E1. The folder cannot be created.** `[proposed]` · M × L
Given `<data_dir>` is not writable,
Then `screamingface up` fails with the existing start-up error path and names the folder. It does
not fall back to `$TMPDIR` silently.

### 3.3 Derived scenarios (risk order)

**LA-D1. Writer and reader agree.** `[existing apps/screamingface-engine/src/screamingface_engine/job_env.py:359]` · H × M
Given the built apps,
Then `EngineSettings.artifacts_dir` equals `run_env["URL4_CLOUD_ARTIFACTS_DIR"]`.

**LA-D2. A user override wins on both sides.** `[proposed]` · M × L
Given `URL4_CLOUD_ARTIFACTS_DIR=/fast/disk`,
Then both sides use `/fast/disk`.

**LA-D3. TTL is unchanged.** `[stated prompt]` · M × L
Given a file older than 48 h in the new folder,
When the App starts, Then it is swept, as in `$TMPDIR` today.

**LA-D4. `SCREAMINGFACE_DATA_DIR` moves the folder.** `[existing packages/screamingface/src/screamingface/_runtime/config.py:12]` · L × L
Given `SCREAMINGFACE_DATA_DIR=/x`, Then the folder is `/x/artifacts`.

**LA-D5. Old `$TMPDIR` files.** `[implied]` · L × L
The SDK does not move or read them. No record points at them (records start with this release).

## 4. Non-functional requirements

- Disk: up to the sum of results from the last 48 h in the home folder (2.7 GB in the incident).
  `screamingface status` shows the folder path and its size. `[proposed]` (Should)

## 5. Out of scope

- Hosted retention (`[stated ans:Q8]`), and a longer local TTL (`[stated prompt]`).

## 6. Open questions

None.

## 7. TDD plan

Updated after the PR B design review (2026-10-01). LA-4 and LA-8 are removed: they could only
exercise the Engine's own `FilesystemArtifactStore`, never this change. LA-1 is the SDK-side
guarantee for LA-H2 and LA-D3, and the Engine's tests own the store and the sweep.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| LA-0 | `user_override_reaches_both_sides` | unit | LA-D2 | M×L | one value, set in two places |
| LA-0b | `artifacts_env_name_is_the_engines_own` (pins `ARTIFACTS_DIR_ENV` to `job_env.ARTIFACTS_DIR`) | unit | LA-D1 | H×L | constant in `_runtime/config.py` |
| LA-0c | `artifacts_override_treats_blank_as_unset` | unit | LA-D1 | M×M | `RuntimeConfig.artifacts_override` |
| LA-1 | `default_is_the_same_data_dir_folder_on_both_sides`, `blank_override_counts_as_unset` | unit | LA-D1 | H×M | `effective_artifacts_dir` |
| LA-2 | `default_folder_is_created_private`, `existing_default_folder_is_made_private_again`, `user_override_folder_is_left_to_the_engine_store` | unit | LA-H1 | M×H | mkdir + chmod 0700 only for the default |
| LA-5 | `unwritable_data_dir_raises_an_error_naming_the_folder` | unit | LA-E1 | M×L | the error propagates |
| LA-6 | `data_dir_override_moves_the_folder` | unit | LA-D4 | L×L | — |
| LA-7 | `status_shows_the_artifacts_folder_and_its_size`, `…_reports_zero_bytes_for_a_missing_folder`, `…_survives_a_file_swept_between_listing_and_stat`, `…_reports_the_folder_the_server_recorded`, `…_marks_an_unreadable_folder_size_unknown` | unit | §4 | M×M | the state record carries the effective folder (OME-1169 pattern) |

LA-H2, LA-D3 and LA-D5 have no SDK test: the bytes live on a non-temp disk path (LA-1), and the
48 h sweep and the store are Engine behavior that this change does not touch.
