# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the packaged Atlas kernel.

Produces a single self-contained ``atlas-kernel`` executable that the Tauri
shell launches as a sidecar. It embeds the Python runtime, so an installed
Atlas needs no Python on the machine.

    python3 -m PyInstaller infra/packaging/atlas-kernel.spec --distpath ...

Two things are easy to get wrong here and both are handled below:

* **Hidden imports.** uvicorn and the kernel resolve several modules by string
  at runtime, so static analysis cannot see them. Missing one produces a binary
  that builds cleanly and then fails at startup.
* **Console mode.** The kernel must keep a console subsystem on Windows even
  though the app is windowed, because the shell reads its stdout for progress.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

REPO = Path(SPECPATH).resolve().parents[1]
KERNEL = REPO / "packages" / "kernel"

# uvicorn loads its protocol and lifespan implementations by name.
hidden = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    # psycopg picks its implementation at import time; the binary build is the
    # one that carries libpq, so it must be present or the kernel cannot
    # reach the database it just started.
    "psycopg",
    "psycopg_binary",
    "psycopg.pq",
    "psycopg_pool",
]

# The kernel itself is imported through a string by uvicorn
# ("atlas_kernel.api:app"), so PyInstaller cannot follow it from the entry
# point. Collecting the package wholesale is the reliable answer, and also
# picks up the domain modules the event bus imports dynamically.
hidden += collect_submodules("atlas_kernel")

# Package *metadata*, not just the modules. Without this the modules import
# and serve perfectly but importlib.metadata cannot see them, so
# /health/report declares every dependency "missing" and a freshly installed
# Atlas reports itself degraded. The diagnostics were telling the truth about
# what they could observe; the bundle was incomplete.
metadata = []
for distribution in (
    "fastapi",
    "sqlalchemy",
    "uvicorn",
    "httpx",
    "pydantic",
    "psycopg",
    "starlette",
    "python-multipart",
):
    try:
        metadata += copy_metadata(distribution)
    except Exception:  # noqa: BLE001 - an absent optional dist is not fatal
        pass

analysis = Analysis(
    [str(KERNEL / "atlas_kernel" / "launcher.py")],
    pathex=[str(KERNEL)],
    binaries=[],
    datas=metadata,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # Nothing in the kernel needs these, and they are large.
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "PIL",
        "pytest",
        "black",
        "mypy",
        "ruff",
        "IPython",
    ],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="atlas-kernel",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # Keep the console subsystem: the desktop shell parses stdout for
    # bootstrap progress. On Windows the parent app is windowed, so no
    # console window is shown to the user.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
