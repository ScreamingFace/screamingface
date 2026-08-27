# ScreamingFace Studio sidecar

This directory freezes the published `screamingface[runtime]` distribution for inclusion in the
Tauri desktop app. Runtime composition, migrations, configuration, lifecycle behavior, and service
APIs belong to the `screamingface` package; Studio does not maintain a separate implementation.

The resulting `onedir` bundle contains one executable that runs:

| Service | Address |
| --- | --- |
| AI Gateway | `http://127.0.0.1:9105` |
| Scoreboard | `http://127.0.0.1:9106` |
| ScreamingFace Engine | `http://127.0.0.1:9108` |

All services bind to loopback and store writable state below the data directory supplied by Tauri.

## What lives here

- `pyproject.toml` and `uv.lock` define the reproducible build environment.
- `sidecar.py` is a minimal PyInstaller bootstrap for the packaged runtime CLI. It only translates
  the frozen Scoreboard child marker into the CLI's private `_scoreboard` command.
- `screamingface-runtime.spec` collects lazy imports, package data, metadata, and native libraries
  that PyInstaller cannot discover statically.
- `build-sidecar.sh` builds the frozen `onedir` artifact.
- `sign-sidecar.sh` signs nested Mach-O files and then the sidecar executable for macOS.
- `verify-sidecar.sh` checks frozen startup, the three health endpoints, Engine model discovery,
  graceful shutdown, and port release.

## Requirements

- Python 3.12 or 3.13
- [`uv`](https://docs.astral.sh/uv/)
- macOS arm64 for the currently verified frozen target

## Run the packaged CLI during development

```sh
cd apps/screamingface-studio/runtime
uv sync --frozen
.venv/bin/screamingface --data-dir /tmp/screamingface-studio up --foreground
```

The source-mode command and the frozen sidecar use the same runtime implementation. The frozen
executable takes the same arguments:

```sh
dist/screamingface-runtime/screamingface-runtime \
  --data-dir /tmp/screamingface-studio up --foreground
```

Successful startup emits a timestamped log line containing the shared runtime readiness record:

```text
SCREAMINGFACE_RUNTIME_READY {"services":{"engine":"http://127.0.0.1:9108","gateway":"http://127.0.0.1:9105","scoreboard":"http://127.0.0.1:9106"}}
```

## Build and verify

```sh
cd apps/screamingface-studio/runtime
./build-sidecar.sh
./verify-sidecar.sh
```

The build output is:

```text
dist/screamingface-runtime/
├── screamingface-runtime
└── _internal/
```

`onedir` avoids extracting an archive on every launch and lets release tooling sign nested native
libraries before signing the executable. The verifier launches this artifact from a temporary
working directory so it cannot accidentally rely on the repository checkout.

## Tauri integration

Tauri starts the sidecar with its application data directory and `up --foreground`, waits for the
readiness record, forwards output to the application log, monitors unexpected exits, and terminates
the complete process group when the app exits.

During development, Tauri uses the frozen artifact when present and otherwise falls back to the
environment's `screamingface` console script. Set `SCREAMINGFACE_RUNTIME_EXECUTABLE` to exercise a
specific executable.

For application builds, `src-tauri/before_build.sh` builds the sidecar and copies the complete
`onedir` directory into `src-tauri/resources/screamingface-runtime`. Tauri then includes that
directory as an application resource. On macOS, the script signs every nested Mach-O artifact
before signing the main sidecar executable. Local builds use an ad-hoc identity; release builds use
`APPLE_SIGNING_IDENTITY` from the imported Developer ID Application certificate.

The desktop release workflow passes the same identity to Tauri. Tauri signs the containing app and
uses the configured Apple ID credentials to notarize the final macOS artifacts. Signing proceeds
from the innermost PyInstaller libraries outward so later bundle steps do not invalidate signatures.

## Current limitations

- Only the macOS arm64 frozen artifact has been verified.
- Studio currently uses the default runtime ports.
- Provider credentials and downloaded benchmark assets remain user data and are never bundled.
- Target-triple naming and additional platform validation remain release-pipeline work.
