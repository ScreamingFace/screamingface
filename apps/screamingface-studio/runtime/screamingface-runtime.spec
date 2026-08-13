"""Build one standalone ScreamingFace desktop runtime executable."""

from pathlib import Path
from importlib.metadata import distribution

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

root = Path(SPECPATH)
screamingface_root = Path(distribution("screamingface").locate_file("screamingface"))

LAZY_IMPORTS = (
    "aigateway",
    "litellm",
    "scoreboard",
    "screamingface",
    "tiktoken",
    "tiktoken_ext",
    "tortoise",
    "url4",
    "url4_cloud",
)

PACKAGES_WITH_DATA = (
    "litellm",
    "tiktoken",
    "screamingface_runtime",
    "screamingface",
    "scoreboard",
    "url4_cloud",
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
    [str(root / "src" / "screamingface_runtime" / "__main__.py")],
    pathex=[str(root / "src")],
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
        (str(screamingface_root / "_runtime" / "resources"), "screamingface/_runtime/resources"),
        (
            str(screamingface_root / "_runtime" / "scoreboard_portal"),
            "screamingface/_runtime/scoreboard_portal",
        ),
        (
            str(screamingface_root / "_runtime" / "scoreboard_artifacts"),
            "screamingface/_runtime/scoreboard_artifacts",
        ),
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
