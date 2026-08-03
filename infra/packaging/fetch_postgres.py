#!/usr/bin/env python3
"""Download the PostgreSQL server that Atlas installers bundle.

Atlas ships its own database so that installing Atlas installs nothing else.
This fetches an official PostgreSQL build, repackaged by the Zonky project as
a Maven artifact, and lays it out where the Tauri bundler expects it:

    apps/desktop/src-tauri/resources/postgres/{bin,lib,share}

Usage:

    python3 infra/packaging/fetch_postgres.py                # host platform
    python3 infra/packaging/fetch_postgres.py --platform windows-amd64

Licensing: the binaries are PostgreSQL under the PostgreSQL License; the Zonky
packaging is Apache-2.0. Both are recorded in NOTICE.

A note on macOS: the darwin artifacts are universal binaries containing both
x86_64 and arm64, so one download serves Intel and Apple Silicon.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DESTINATION = REPO / "apps" / "desktop" / "src-tauri" / "resources" / "postgres"

#: Pinned. A packaging change must be a deliberate edit, not whatever is
#: newest on the day CI happens to run.
POSTGRES_VERSION = "16.14.0"

BASE_URL = "https://repo1.maven.org/maven2/io/zonky/test/postgres"

#: Zonky's platform names, keyed by the names we use. The value is also the
#: prefix of the .txz inside the jar.
PLATFORMS: dict[str, str] = {
    "darwin-arm64": "darwin-arm64v8",
    "darwin-amd64": "darwin-amd64",
    "windows-amd64": "windows-amd64",
    "linux-amd64": "linux-amd64",
    "linux-arm64": "linux-arm64v8",
}

#: Only these are needed to initialise and run a server. Client tools such as
#: psql are deliberately absent -- Atlas connects through psycopg.
REQUIRED_BINARIES = ("initdb", "pg_ctl", "postgres")

#: PostgreSQL's procedural-language extensions link against language runtimes
#: that Atlas does not bundle: plpython3 needs libpython3.6m.so.1.0, plperl
#: needs libperl, pltcl needs libtcl. Atlas runs no in-database Python, Perl or
#: Tcl -- it talks to the server through psycopg -- so these are unusable here
#: for the same reason psql is absent above.
#:
#: They are not merely dead weight, they broke the Linux installer. linuxdeploy
#: walks every ELF file in the AppDir to resolve shared-library dependencies.
#: It reached lib/postgresql/hstore_plpython3.so, could not find
#: libpython3.6m.so.1.0 -- Python 3.6 is end-of-life and ships on no current
#: distribution -- and aborted the entire bundle with:
#:
#:     ERROR: Could not find dependency: libpython3.6m.so.1.0
#:     ERROR: Failed to deploy dependencies for existing files
#:
#: Tauri reported only `failed to run linuxdeploy`, because it discards the
#: tool's output unless the build runs with --verbose. See docs/PACKAGING.md.
#:
#: Matched against the whole tree, so this covers the loadable modules
#: (.so/.dll/.dylib) and the .control/.sql files that advertise the extensions.
UNUSABLE_EXTENSION_PATTERNS = ("*plpython3*", "*plperl*", "*pltcl*")


def host_platform() -> str:
    import platform

    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "darwin":
        return "darwin-arm64" if arm else "darwin-amd64"
    if sys.platform.startswith("linux"):
        return "linux-arm64" if arm else "linux-amd64"
    if sys.platform in ("win32", "cygwin"):
        return "windows-amd64"
    raise SystemExit(f"unsupported host platform: {sys.platform} / {machine}")


def artifact_url(platform_key: str) -> str:
    zonky = PLATFORMS[platform_key]
    name = f"embedded-postgres-binaries-{zonky}-{POSTGRES_VERSION}.jar"
    return f"{BASE_URL}/embedded-postgres-binaries-{zonky}/{POSTGRES_VERSION}/{name}"


def _ssl_context() -> ssl.SSLContext:
    """Trust certifi's roots.

    Python installed from python.org does not use the system keychain, so a
    plain urlopen fails with CERTIFICATE_VERIFY_FAILED on a clean machine.
    certifi is already a dependency, so use its bundle rather than asking
    every builder to fix their trust store.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def download(url: str, target: Path) -> str:
    """Download and return the SHA-256, so the build is auditable."""
    print(f"  fetching {url}")
    with urllib.request.urlopen(url, context=_ssl_context()) as response:
        with target.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f"  sha256 {digest}")
    return digest


def extract(jar: Path, workdir: Path) -> Path:
    """Unwrap jar -> .txz -> tree. Returns the extracted PostgreSQL root."""
    with zipfile.ZipFile(jar) as archive:
        members = [n for n in archive.namelist() if n.endswith(".txz")]
        if not members:
            raise SystemExit(f"no .txz inside {jar.name} -- artifact layout changed")
        archive.extract(members[0], workdir)
        inner = workdir / members[0]

    root = workdir / "postgres"
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(inner, "r:xz") as tar:
        # filter="data" refuses absolute paths and traversal outside the
        # destination. Available from Python 3.12.
        tar.extractall(root, filter="data")
    return root


def prune(root: Path) -> None:
    """Drop what an embedded server never uses, to keep installers smaller."""
    for relative in ("include", "share/doc", "share/man", "pgsql/include"):
        path = root / relative
        if path.is_dir():
            shutil.rmtree(path)

    removed = []
    for pattern in UNUSABLE_EXTENSION_PATTERNS:
        for path in sorted(root.rglob(pattern)):
            if path.is_symlink() or path.is_file():
                path.unlink()
                removed.append(path.relative_to(root).as_posix())
    if removed:
        print(f"  dropped {len(removed)} procedural-language extension files")
        for name in removed:
            print(f"    - {name}")


def verify(root: Path, platform_key: str) -> None:
    suffix = ".exe" if platform_key.startswith("windows") else ""
    missing = [n for n in REQUIRED_BINARIES if not (root / "bin" / f"{n}{suffix}").exists()]
    if missing:
        raise SystemExit(f"bundle is missing required binaries: {', '.join(missing)}")

    # On the host platform the binary can actually be run, which catches a
    # wrong-architecture download that a file listing would not.
    if platform_key == host_platform() and not platform_key.startswith("windows"):
        result = subprocess.run(
            [str(root / "bin" / "postgres"), "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit(f"bundled postgres will not run: {result.stderr.strip()}")
        print(f"  verified: {result.stdout.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=sorted(PLATFORMS), default=None)
    parser.add_argument("--destination", type=Path, default=DESTINATION)
    parser.add_argument("--force", action="store_true", help="Re-download even if present.")
    args = parser.parse_args()

    platform_key = args.platform or host_platform()
    destination = args.destination

    if destination.exists() and not args.force:
        suffix = ".exe" if platform_key.startswith("windows") else ""
        if (destination / "bin" / f"pg_ctl{suffix}").exists():
            print(f"PostgreSQL already present at {destination} (use --force to replace)")
            return 0
        shutil.rmtree(destination)

    print(f"PostgreSQL {POSTGRES_VERSION} for {platform_key}")
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        jar = workdir / "postgres.jar"
        download(artifact_url(platform_key), jar)
        root = extract(jar, workdir)
        prune(root)
        verify(root, platform_key)

        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(root), str(destination))

    # Skip symlinks: stat() follows them, so counting both the link and its
    # target reported roughly double the real size.
    size = sum(
        f.stat().st_size for f in destination.rglob("*") if f.is_file() and not f.is_symlink()
    )
    print(f"  installed to {destination} ({size / 1_048_576:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
