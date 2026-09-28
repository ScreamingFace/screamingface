"""Build one standalone ScreamingFace desktop runtime executable."""

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)
from screamingface._runtime.config import bundled_runner_config, scoreboard_assets

root = Path(SPECPATH)
# WHY the runtime's own lookups, not the installed distribution's directory: an editable
# screamingface install ships no copies of these resources (only a .pth to the live
# sources), so they exist only where these functions resolve them — the checkout.
runner_config = bundled_runner_config()
scoreboard_portal, scoreboard_artifacts = scoreboard_assets()

LAZY_IMPORTS = (
    "aigateway",
    "litellm",
    "scoreboard",
    "screamingface",
    "screamingface_engine",
    "tiktoken",
    "tiktoken_ext",
    "tortoise",
    "url4",
)

PACKAGES_WITH_DATA = (
    "litellm",
    "tiktoken",
    "screamingface",
    "screamingface_engine",
    "scoreboard",
)

PACKAGES_WITH_METADATA = (
    "litellm",
    "screamingface",
)

PACKAGES_WITH_BINARIES = (
    "bcrypt",
    "cryptography",
    "httptools",
    "uvloop",
    "watchfiles",
    "websockets",
)

analysis = Analysis(
    [str(root / "sidecar.py")],
    pathex=[str(root)],
    binaries=[
        binary
        for package in PACKAGES_WITH_BINARIES
        for binary in collect_dynamic_libs(package)
    ],
    datas=[
        data
        for package in PACKAGES_WITH_DATA
        for data in collect_data_files(package)
    ]
    + [
        (str(runner_config), "screamingface/_runtime/resources"),
        (str(scoreboard_portal), "screamingface/_runtime/scoreboard_portal"),
        (str(scoreboard_artifacts), "screamingface/_runtime/scoreboard_artifacts"),
    ]
    + [
        metadata
        for distribution in PACKAGES_WITH_METADATA
        for metadata in copy_metadata(distribution)
    ],
    hiddenimports=sorted(
        {
            module
            for package in LAZY_IMPORTS
            for module in collect_submodules(package)
        }
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="screamingface-runtime",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="screamingface-runtime",
)
