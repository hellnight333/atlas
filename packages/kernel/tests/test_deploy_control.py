"""Drive the real `infra/deploy_control.sh` end to end against a fake host.

The invariant these tests exist for is ADR-0010 Step 1: what a deploy ships is
one immutable commit, never the working tree. That cannot be proved by reading
the script — the old script also *looked* like it copied the right thing — so
the script is executed for real, with `ssh`, `rsync`, `systemctl`, `curl` and
friends shimmed onto `PATH` and the host paths pointed at directories under
`tmp_path`. Every negative case below fails against a tree-reading deploy.

Two safety layers, because a test that drives a deploy script is one mistake
away from driving a deploy: every run passes an explicit `qevik-test@127.0.0.1`
target rather than the production default, and `HOME` is a directory inside
`tmp_path` where the deploy key does not exist — so a shim that failed to take
effect reaches nothing. One test asserts exactly that.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "infra" / "deploy_control.sh"
TARGET = "qevik-test@127.0.0.1"

# `cp` and `rsync` are resolved once, here, because the shims must call the real
# ones by absolute path: the shim directory is first on PATH and `rsync` would
# otherwise re-enter itself.
_TOOLS = {name: shutil.which(name) for name in ("git", "rsync", "bash", "shasum", "cp")}
_MISSING = sorted(name for name, found in _TOOLS.items() if not found)

pytestmark = pytest.mark.skipif(
    bool(_MISSING),
    reason=(
        f"deploy_control.sh cannot be driven without {_MISSING}; "
        "nothing below is being asserted"
    ),
)

# What the commit under test carries, and what a later commit changes it to. The
# two must differ in every shipped prefix, or "the tree did not leak in" is not
# actually being observed.
S_FILES = {
    "packages/kernel/atlas_kernel/__init__.py": "# kernel package\n",
    "packages/kernel/atlas_kernel/qevik/app.py": "APP = 'S'\n",
    "infra/mission_worker.py": "WORKER = 'S'\n",
    "infra/qevik-worker.service": "[Unit]\nDescription=qevik worker S\n",
    "apps/control/src/index.html": "<h1>console S</h1>\n",
}
DRIFT_FILES = {
    "packages/kernel/atlas_kernel/qevik/app.py": "APP = 'DRIFT'\n",
    "infra/mission_worker.py": "WORKER = 'DRIFT'\n",
    "infra/qevik-worker.service": "[Unit]\nDescription=qevik worker DRIFT\n",
    "apps/control/src/index.html": "<h1>console DRIFT</h1>\n",
}
OLD_HOST = {
    "opt/qevik/atlas/packages/kernel/atlas_kernel/qevik/app.py": "APP = 'old'\n",
    "opt/qevik/atlas/packages/kernel/atlas_kernel/gone.py": "# deleted by --delete\n",
    "opt/qevik/atlas/infra/mission_worker.py": "WORKER = 'old'\n",
    "srv/qevik-control/index.html": "<h1>console old</h1>\n",
    "etc/systemd/system/qevik-worker.service": "[Unit]\nDescription=old\n",
}


def _write(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(0o755)


@dataclass
class World:
    repo: Path
    fake: Path
    ctl: Path
    shims: Path
    home: Path
    scratch: Path
    sha: str

    @property
    def app(self) -> Path:
        return self.fake / "opt/qevik/atlas"

    @property
    def console(self) -> Path:
        return self.fake / "srv/qevik-control"

    @property
    def units(self) -> Path:
        return self.fake / "etc/systemd/system"

    def seams(self) -> dict[str, str]:
        return {
            "QEVIK_REMOTE_APP": str(self.app),
            "QEVIK_CONSOLE_DIR": str(self.console),
            "QEVIK_UNIT_DIR": str(self.units),
            "QEVIK_ENV_FILE": str(self.fake / "opt/qevik/atlas.env"),
            "QEVIK_HEALTH_URL": "http://127.0.0.1:8081/api/health",
            "QEVIK_ROLLBACK_DIR": str(self.fake / "opt/qevik/rollback"),
        }

    def log(self) -> list[str]:
        path = self.ctl / "log"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def remote_commands(self) -> list[str]:
        return [line[4:] for line in self.log() if line.startswith("ssh ")]


def _git(repo: Path, *args: str, home: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({"HOME": str(home), "XDG_CONFIG_HOME": str(home),
                "GIT_CONFIG_NOSYSTEM": "1"})
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True, env=env)


def snapshot(fake: Path) -> dict[str, str]:
    """Every path under the fake host: sha256 for files, link text, or "dir".

    `ctl/` is the shims' own scratch and log; it changes on every run by
    construction and says nothing about whether the host was written to.
    """
    seen: dict[str, str] = {}
    for path in sorted(fake.rglob("*")):
        rel = path.relative_to(fake).as_posix()
        if rel == "ctl" or rel.startswith("ctl/"):
            continue
        if path.is_symlink():
            seen[rel] = "link:" + os.readlink(path)
        elif path.is_dir():
            seen[rel] = "dir"
        else:
            seen[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return seen


def fingerprint(text: str) -> str:
    """The worker fingerprint the script computes: sha256, first twelve chars."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


# --- provenance: the marker and the manifest ---------------------------------

# The four areas a deploy writes and a rollback restores, as snapshot() keys.
TARGET_PREFIXES = ("opt/qevik/atlas/packages/", "opt/qevik/atlas/infra",
                   "srv/qevik-control", "etc/systemd/system")


def read_marker(world: World) -> dict[str, str]:
    text = (world.app / "DEPLOYED_SHA").read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            out[key] = value
    return out


def targets_only(snap: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in snap.items() if k.startswith(TARGET_PREFIXES)}


def _commit_blobs(world: World, sha: str) -> dict[str, bytes]:
    """Every shipped regular file in a commit, as the export would hold it."""
    env = dict(os.environ)
    env.update({"HOME": str(world.home), "XDG_CONFIG_HOME": str(world.home),
                "GIT_CONFIG_NOSYSTEM": "1"})
    listing = subprocess.run(
        ["git", "-C", str(world.repo), "-c", "core.quotepath=false",
         "ls-tree", "-r", sha],
        check=True, capture_output=True, text=True, env=env).stdout
    blobs: dict[str, bytes] = {}
    for line in listing.splitlines():
        meta, _, name = line.partition("\t")
        if meta.split()[0] == "120000":  # a symlink is not a regular file
            continue
        if not name.startswith(("packages/kernel/atlas_kernel/", "infra/",
                                "apps/control/src/")):
            continue
        blobs[name] = subprocess.run(
            ["git", "-C", str(world.repo), "show", f"{sha}:{name}"],
            check=True, capture_output=True, env=env).stdout
    return blobs


def expected_manifest(world: World, sha: str) -> list[str]:
    """The manifest the script must build: the commit's files at host paths."""
    lines = []
    for name, blob in _commit_blobs(world, sha).items():
        digest = hashlib.sha256(blob).hexdigest()
        if name.startswith("apps/control/src/"):
            host = f"{world.console}/{name[len('apps/control/src/'):]}"
        else:
            host = f"{world.app}/{name}"
        lines.append(f"{digest}  {host}")
        if name.startswith("infra/qevik-") and name.endswith(".service"):
            lines.append(f"{digest}  {world.units}/{name[len('infra/'):]}")
    return sorted(lines)


def manifest_digest(lines: list[str]) -> str:
    return hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()


def host_manifest(world: World) -> list[str]:
    """A manifest of whatever the fake host holds right now."""
    lines = []
    for root in (world.app / "packages/kernel/atlas_kernel", world.app / "infra",
                 world.console):
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.is_symlink():
                lines.append(
                    f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path}")
    for path in sorted(world.units.glob("qevik-*.service")):
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path}")
    return sorted(lines)


def write_previous_provenance(world: World, *, manifest: bool = True) -> str:
    """Give the fake host the marker (and manifest) of an earlier deploy."""
    digest = "0" * 64
    if manifest:
        lines = host_manifest(world)
        _write(world.app / "DEPLOYED_MANIFEST", "\n".join(lines) + "\n")
        digest = manifest_digest(lines)
    text = (f"sha={'1' * 40}\n"
            "installed_at=2026-01-01T00:00:00Z\n"
            f"manifest_sha256={digest}\n"
            "state=installed\n")
    _write(world.app / "DEPLOYED_SHA", text)
    return text


def _write_shims(shims: Path, ctl: Path) -> None:
    real_rsync = _TOOLS["rsync"]
    common = f'CTL="{ctl}"\nmkdir -p "$CTL"\n'

    _write(shims / "ssh", f"""#!/usr/bin/env bash
# Stand in for ssh: drop the options and the target, run the rest here, so the
# remote commands operate on the fake host the seams point at.
{common}
while [ $# -gt 0 ]; do
  case "$1" in
    -o|-i) shift 2 ;;
    -*) shift ;;
    *) break ;;
  esac
done
shift
CMD="$*"
# One log line per remote command even when the command is a small script: the
# log is read line by line, and a multi-line entry would look like several.
printf 'ssh %s\\n' "$(printf '%s' "$CMD" | tr '\\n' ' ')" >> "$CTL/log"
DROP=0
[ -f "$CTL/ssh_drop" ] && DROP="$(cat "$CTL/ssh_drop")"
CALLS=0
[ -f "$CTL/ssh_calls" ] && CALLS="$(cat "$CTL/ssh_calls")"
CALLS=$((CALLS + 1))
printf '%s\\n' "$CALLS" > "$CTL/ssh_calls"
if [ "$CALLS" -le "$DROP" ]; then
  echo "ssh: connect to host: Connection refused" >&2
  exit 255
fi
if [ -f "$CTL/ssh_fail_match" ]; then
  MATCH="$(cat "$CTL/ssh_fail_match")"
  case "$CMD" in *"$MATCH"*) exit 1 ;; esac
fi
exec bash -c "$CMD"
""", executable=True)

    _write(shims / "rsync", f"""#!/usr/bin/env bash
# Stand in for rsync only as far as the transport: -e and --timeout go, the
# "target:" prefix goes, and every other flag -- -n, -i, --delete, --exclude --
# reaches the real rsync, so a dry run really is a dry run.
{common}
printf 'rsync %s\\n' "$*" >> "$CTL/log"
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -e) shift 2 ;;
    --timeout=*) shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
LAST_IDX=$((${{#ARGS[@]}} - 1))
LAST="${{ARGS[$LAST_IDX]}}"
case "$LAST" in
  *:*) ARGS[$LAST_IDX]="${{LAST#*:}}" ;;
esac
if [ -x "$CTL/hook" ]; then "$CTL/hook"; fi
# A transfer that never succeeds, so `rsync_` spends its whole retry budget.
if [ -f "$CTL/rsync_fail" ]; then
  echo "rsync: refused by the test" >&2
  exit 1
fi
# `after_hook` runs once the bytes have landed, which is the only place a test
# can corrupt what the host holds *after* a copy reported success.
if [ -x "$CTL/after_hook" ]; then
  "{real_rsync}" "${{ARGS[@]}}"; RC=$?
  "$CTL/after_hook"
  exit $RC
fi
exec "{real_rsync}" "${{ARGS[@]}}"
""", executable=True)

    _write(shims / "cp", f"""#!/usr/bin/env bash
# The real cp, except when the test names a destination it must fail on. This is
# how "a rollback copy could not be taken" and "a restore could not be made" are
# exercised without making the whole host read-only.
{common}
printf 'cp %s\\n' "$*" >> "$CTL/log"
if [ -f "$CTL/fail_cp_dest" ]; then
  MATCH="$(cat "$CTL/fail_cp_dest")"
  DEST=""
  for a in "$@"; do DEST="$a"; done
  case "$DEST" in *"$MATCH"*) echo "cp: refused by the test" >&2; exit 1 ;; esac
fi
exec "{_TOOLS['cp']}" "$@"
""", executable=True)

    _write(shims / "sleep", f"""#!/usr/bin/env bash
# Every sleep in the script is a pure wait; the test does not need to serve it.
{common}
printf 'sleep %s\\n' "$*" >> "$CTL/log"
exit 0
""", executable=True)

    _write(shims / "curl", f"""#!/usr/bin/env bash
{common}
printf 'curl %s\\n' "$*" >> "$CTL/log"
CODE=200
[ -f "$CTL/health_code" ] && CODE="$(cat "$CTL/health_code")"
printf '%s' "$CODE"
exit 0
""", executable=True)

    _write(shims / "sudo", f"""#!/usr/bin/env bash
# The worker registry query. The DISTINCT read answers with whatever version the
# test says the workers report; the count read answers one.
{common}
printf 'sudo %s\\n' "$*" >> "$CTL/log"
case "$*" in
  *"SELECT DISTINCT"*)
    [ -f "$CTL/worker_version" ] && cat "$CTL/worker_version" ;;
  *"count(*)"*) printf '1' ;;
esac
exit 0
""", executable=True)

    _write(shims / "systemctl", f"""#!/usr/bin/env bash
{common}
printf 'systemctl %s\\n' "$*" >> "$CTL/log"
case "$1" in is-active) echo active ;; esac
exit 0
""", executable=True)

    for name in ("chown", "journalctl"):
        _write(shims / name, f"""#!/usr/bin/env bash
{common}
printf '{name} %s\\n' "$*" >> "$CTL/log"
exit 0
""", executable=True)

    _write(shims / "sha256sum", f"""#!/usr/bin/env bash
# macOS has /sbin/sha256sum too, so leaving the tool off PATH cannot prove the
# absent case; this shim answers exactly as a host without the tool would.
{common}
printf 'sha256sum %s\\n' "$*" >> "$CTL/log"
if [ -f "$CTL/no_sha256sum" ]; then
  echo "sha256sum: command not found" >&2
  exit 127
fi
exec shasum -a 256 "$@"
""", executable=True)


@pytest.fixture
def world(tmp_path: Path) -> World:
    home = tmp_path / "home"
    home.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    fake = tmp_path / "fake"
    ctl = fake / "ctl"
    ctl.mkdir(parents=True)
    shims = tmp_path / "shims"
    shims.mkdir()
    _write_shims(shims, ctl)

    for rel, text in OLD_HOST.items():
        _write(fake / rel, text)
    _write(fake / "opt/qevik/atlas.env", "")
    _write(fake / "opt/qevik/atlas/.venv/bin/python",
           f'#!/usr/bin/env bash\n'
           f'if [ -f "{ctl}/schema_fail" ]; then\n'
           f'  echo "init_db: refused by the test" >&2\n'
           f'  exit 1\n'
           f'fi\n'
           f'echo "schema applied"\n', executable=True)
    _write(ctl / "health_code", "200")

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main", home=home)
    _git(repo, "config", "user.email", "tests@example.invalid", home=home)
    _git(repo, "config", "user.name", "deploy tests", home=home)
    _git(repo, "config", "commit.gpgsign", "false", home=home)
    for rel, text in S_FILES.items():
        _write(repo / rel, text)
    # The real script, copied rather than symlinked: a symlink is an untracked
    # path inside the repository and the export check would count it.
    shutil.copy2(SCRIPT, repo / "infra" / "deploy_control.sh")
    (repo / "infra" / "deploy_control.sh").chmod(0o755)
    _git(repo, "add", "-A", home=home)
    _git(repo, "commit", "-q", "-m", "S", home=home)
    sha = _git(repo, "rev-parse", "HEAD", home=home).stdout.strip()

    _write(ctl / "worker_version", fingerprint(S_FILES["infra/mission_worker.py"]))
    return World(repo=repo, fake=fake, ctl=ctl, shims=shims, home=home,
                 scratch=scratch, sha=sha)


def commit(world: World, files: dict[str, str] | None = None,
           symlinks: dict[str, str] | None = None, message: str = "change") -> str:
    for rel, text in (files or {}).items():
        _write(world.repo / rel, text)
    for rel, dest in (symlinks or {}).items():
        path = world.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or path.exists():
            path.unlink()
        os.symlink(dest, path)
    _git(world.repo, "add", "-A", home=world.home)
    _git(world.repo, "commit", "-q", "-m", message, home=world.home)
    return _git(world.repo, "rev-parse", "HEAD", home=world.home).stdout.strip()


def env_for(world: World, *, sha: str | None = None, seams: bool = True,
            test_host: bool = True, path: str | None = None,
            drop_seams: tuple[str, ...] = ()) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("QEVIK_")}
    env["PATH"] = path if path is not None else f"{world.shims}{os.pathsep}{env['PATH']}"
    env["HOME"] = str(world.home)
    env["XDG_CONFIG_HOME"] = str(world.home)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["TMPDIR"] = str(world.scratch)
    if test_host:
        env["QEVIK_TEST_HOST"] = "1"
    if seams:
        for name, value in world.seams().items():
            if name not in drop_seams:
                env[name] = value
    if sha is not None:
        env["QEVIK_DEPLOY_SHA"] = sha
    return env


def run(world: World, *args: str, env: dict[str, str],
        timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(world.repo / "infra" / "deploy_control.sh"), *args, TARGET],
        cwd=str(world.scratch), env=env, capture_output=True, text=True,
        timeout=timeout)


def both(proc: subprocess.CompletedProcess) -> str:
    return proc.stdout + proc.stderr


# --- the payload is the commit ----------------------------------------------


def test_ships_the_commit_not_the_working_tree(world: World):
    """(a) HEAD has moved on; every byte on the host is still S's."""
    commit(world, DRIFT_FILES, message="after S")
    assert _git(world.repo, "rev-parse", "HEAD", home=world.home).stdout.strip() != world.sha
    assert not _git(world.repo, "status", "--porcelain", home=world.home).stdout

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 0, out
    assert f"deployed sha={world.sha}" in out

    kernel = world.app / "packages/kernel/atlas_kernel/qevik/app.py"
    assert kernel.read_text() == S_FILES["packages/kernel/atlas_kernel/qevik/app.py"]
    assert (world.console / "index.html").read_text() == S_FILES["apps/control/src/index.html"]
    assert (world.app / "infra/mission_worker.py").read_text() == S_FILES["infra/mission_worker.py"]
    assert (world.units / "qevik-worker.service").read_text() == S_FILES["infra/qevik-worker.service"]
    assert f"expecting fingerprint {fingerprint(S_FILES['infra/mission_worker.py'])}" in out
    # --delete on the kernel is unchanged by this task.
    assert not (world.app / "packages/kernel/atlas_kernel/gone.py").exists()


def test_a_checkout_mid_deploy_cannot_alter_the_payload(world: World):
    """(b) The tree changes under the copies; the payload does not."""
    _git(world.repo, "checkout", "-q", "-b", "drift", home=world.home)
    commit(world, DRIFT_FILES, message="drift")
    _git(world.repo, "checkout", "-q", "main", home=world.home)

    _write(world.ctl / "hook", f"""#!/usr/bin/env bash
CTL="{world.ctl}"
[ -f "$CTL/hook_ran" ] && exit 0
printf 'ran\\n' > "$CTL/hook_ran"
git -C "{world.repo}" checkout -q drift
""", executable=True)

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 0, out
    # Without this the test could pass because nothing ever changed.
    assert (world.ctl / "hook_ran").exists(), "the mid-deploy checkout never ran"
    assert (world.repo / "packages/kernel/atlas_kernel/qevik/app.py").read_text() \
        == DRIFT_FILES["packages/kernel/atlas_kernel/qevik/app.py"]

    assert (world.app / "packages/kernel/atlas_kernel/qevik/app.py").read_text() \
        == S_FILES["packages/kernel/atlas_kernel/qevik/app.py"]
    assert (world.console / "index.html").read_text() == S_FILES["apps/control/src/index.html"]
    assert (world.app / "infra/mission_worker.py").read_text() == S_FILES["infra/mission_worker.py"]
    assert (world.units / "qevik-worker.service").read_text() == S_FILES["infra/qevik-worker.service"]
    assert f"expecting fingerprint {fingerprint(S_FILES['infra/mission_worker.py'])}" in out


# --- refusals, none of which may touch the host ------------------------------


def _assert_refused_untouched(world: World, proc: subprocess.CompletedProcess,
                              before: dict[str, str], code: int) -> None:
    out = both(proc)
    assert proc.returncode == code, out
    assert not [line for line in world.log()
                if line.startswith("ssh ") or line.startswith("rsync ")], world.log()
    assert snapshot(world.fake) == before


def test_a_missing_sha_is_refused(world: World):
    before = snapshot(world.fake)
    proc = run(world, env=env_for(world, sha=None))
    _assert_refused_untouched(world, proc, before, 2)
    assert "QEVIK_DEPLOY_SHA" in both(proc)


def test_a_sha_that_is_not_a_commit_is_refused(world: World):
    before = snapshot(world.fake)
    proc = run(world, env=env_for(world, sha="0" * 40))
    _assert_refused_untouched(world, proc, before, 2)
    assert "not a commit" in both(proc)


def test_a_commit_that_never_landed_on_main_is_refused(world: World):
    _git(world.repo, "checkout", "-q", "-b", "unmerged", home=world.home)
    unmerged = commit(world, DRIFT_FILES, message="unreviewed")
    _git(world.repo, "checkout", "-q", "main", home=world.home)
    assert not _git(world.repo, "status", "--porcelain", home=world.home).stdout

    before = snapshot(world.fake)
    proc = run(world, env=env_for(world, sha=unmerged))
    _assert_refused_untouched(world, proc, before, 2)
    assert "not landed on main" in both(proc)


def test_an_export_that_does_not_match_the_commit_is_refused(world: World):
    """(d) export-ignore makes the tar disagree with the commit's own tree."""
    sha = commit(world, {".gitattributes": "apps/control/src/index.html export-ignore\n"},
                 message="ignore a shipped file")
    before = snapshot(world.fake)
    proc = run(world, env=env_for(world, sha=sha))
    _assert_refused_untouched(world, proc, before, 3)
    assert "export mismatch (100644): apps/control/src/index.html" in both(proc)


def test_a_commit_without_the_worker_source_is_refused(world: World):
    """The worker fingerprint is taken before the host is touched, not after.

    Redeploying an older landed commit is supported on purpose, and such a
    commit may predate `infra/mission_worker.py` or remove it. The export still
    verifies -- the file is simply not in that commit's tree -- so nothing
    upstream catches it. Fingerprinting after the copies and the restarts would
    abort the script under `set -o pipefail` with production already written and
    the rollback path skipped, which is a worse outcome than either deploying or
    refusing.
    """
    (world.repo / "infra/mission_worker.py").unlink()
    _git(world.repo, "add", "-A", home=world.home)
    _git(world.repo, "commit", "-q", "-m", "drop the worker", home=world.home)
    sha = _git(world.repo, "rev-parse", "HEAD", home=world.home).stdout.strip()

    before = snapshot(world.fake)
    proc = run(world, env=env_for(world, sha=sha))
    _assert_refused_untouched(world, proc, before, 1)
    assert "carries no infra/mission_worker.py" in both(proc)

    # A rehearsal predicts a real run, so it has to refuse the same commit
    # rather than reporting a deploy that would abort halfway.
    proc = run(world, "--rehearse", env=env_for(world, sha=sha))
    _assert_refused_untouched(world, proc, before, 1)
    assert "carries no infra/mission_worker.py" in both(proc)


def test_unknown_flags_and_a_second_positional_are_refused(world: World):
    before = snapshot(world.fake)
    proc = run(world, "--frobnicate", env=env_for(world, sha=world.sha))
    _assert_refused_untouched(world, proc, before, 2)
    assert "unknown option '--frobnicate'" in both(proc)

    proc = run(world, "another-host", env=env_for(world, sha=world.sha))
    _assert_refused_untouched(world, proc, before, 2)
    assert "at most one ssh target" in both(proc)


def test_partial_test_seams_are_refused(world: World):
    """(h, C) A seam without the flag, the flag without the seams, or a gap."""
    before = snapshot(world.fake)

    proc = run(world, env=env_for(world, sha=world.sha, test_host=False))
    _assert_refused_untouched(world, proc, before, 2)
    assert "seams are partially set" in both(proc)

    proc = run(world, env=env_for(world, sha=world.sha,
                                  drop_seams=("QEVIK_ROLLBACK_DIR",)))
    _assert_refused_untouched(world, proc, before, 2)
    assert "5 of 6 host paths" in both(proc)

    # The dangerous one: the flag alone used to skip the all-or-none check and
    # run against the production defaults. Deliberately without the shims — if
    # this refusal ever regressed, the shimmed `ssh` would run the deploy's
    # `rm -rf` against the real /opt/qevik on the machine running the tests.
    proc = run(world, env=env_for(world, sha=world.sha, seams=False,
                                  path=os.environ["PATH"]), timeout=60)
    _assert_refused_untouched(world, proc, before, 2)
    assert "0 of 6 host paths" in both(proc)


# --- tracked symlinks --------------------------------------------------------


def test_a_tracked_symlink_verifies_and_ships(world: World):
    """(A) 120000 blobs are link text, and `find -type f` cannot see them."""
    sha = commit(world, symlinks={"apps/control/src/latest.html": "index.html"},
                 message="add a tracked link")
    proc = run(world, env=env_for(world, sha=sha))
    out = both(proc)
    assert proc.returncode == 0, out
    assert f"export verified: 7 files from {sha}" in out
    link = world.console / "latest.html"
    assert link.is_symlink() and os.readlink(link) == "index.html"


def test_a_utf8_filename_verifies(world: World):
    """git quotes non-ASCII paths by default, and a quoted path is not found."""
    sha = commit(world, {"apps/control/src/café.html": "<h1>café</h1>\n"},
                 message="a name git would quote")
    proc = run(world, env=env_for(world, sha=sha))
    out = both(proc)
    assert proc.returncode == 0, out
    assert f"export verified: 7 files from {sha}" in out


def test_a_symlink_missing_from_the_export_is_refused(world: World):
    commit(world, symlinks={"apps/control/src/latest.html": "index.html"},
           message="add a tracked link")
    sha = commit(world, {".gitattributes": "apps/control/src/latest.html export-ignore\n"},
                 message="ignore the link")
    before = snapshot(world.fake)
    proc = run(world, env=env_for(world, sha=sha))
    _assert_refused_untouched(world, proc, before, 3)
    assert "export mismatch (120000): apps/control/src/latest.html" in both(proc)


# --- rehearse ----------------------------------------------------------------

_FORBIDDEN_IN_REHEARSAL = {"rm", "cp", "mv", "mkdir", "chown", "journalctl"}


def _tokens(command: str) -> list[str]:
    for separator in (";", "&&", "||"):
        command = command.replace(separator, " ")
    return command.split()


def test_rehearse_writes_nothing(world: World):
    """(e) Same payload, every transfer planned, not one byte written."""
    before = snapshot(world.fake)
    proc = run(world, "--rehearse", env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 0, out
    assert snapshot(world.fake) == before

    assert f"REHEARSED sha={world.sha}" in out
    assert f"targets: app={world.app}" in out
    assert f"export verified: 6 files from {world.sha}" in out

    for line in world.log():
        if line.startswith("rsync "):
            assert "-n" in line.split(), line
    for command in world.remote_commands():
        tokens = _tokens(command)
        assert not _FORBIDDEN_IN_REHEARSAL.intersection(tokens), command
        for index, token in enumerate(tokens):
            if token == "systemctl":
                assert tokens[index + 1] == "is-active", command
    assert not [line for line in world.log() if ".venv/bin/python" in line]


def test_a_real_run_does_change_the_host(world: World):
    """(f) The negative control: the "unchanged" assertion above can fail."""
    before = snapshot(world.fake)
    proc = run(world, env=env_for(world, sha=world.sha))
    assert proc.returncode == 0, both(proc)
    assert snapshot(world.fake) != before
    assert [line for line in world.log() if line.startswith("systemctl restart")]


# --- ssh_ retries only link failures -----------------------------------------


def test_only_a_dropped_link_is_retried(world: World):
    """(i, first half) Two 255s are absorbed; the deploy still succeeds."""
    _write(world.ctl / "ssh_drop", "2")
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 0, out

    commands = world.remote_commands()
    assert commands[:3] == ["true", "true", "true"], commands[:4]
    assert commands[3] != "true"
    assert "(link dropped; retry 1)" in out
    assert "(link dropped; retry 2)" in out
    assert "(link dropped; retry 3)" not in out


def test_a_failing_remote_command_is_answered_once(world: World):
    """(i, second half) A remote failure costs one call, not twelve."""
    _write(world.ctl / "ssh_fail_match", "init_db")
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "the schema could not be applied" in out
    attempts = [c for c in world.remote_commands() if "init_db" in c]
    assert len(attempts) == 1, f"the schema step ran {len(attempts)} time(s), not 1"
    # The deploy stopped there: the rollback's own restarts are the only ones,
    # and the worker registry was never asked anything.
    assert not [c for c in world.remote_commands() if "SELECT DISTINCT" in c]


# --- the worker registry poll ------------------------------------------------


def _rolled_back(world: World) -> bool:
    kernel = world.app / "packages/kernel/atlas_kernel/qevik/app.py"
    infra = world.app / "infra/mission_worker.py"
    return (kernel.read_text() == OLD_HOST[
        "opt/qevik/atlas/packages/kernel/atlas_kernel/qevik/app.py"]
        and infra.read_text() == OLD_HOST["opt/qevik/atlas/infra/mission_worker.py"])


def test_a_registry_that_cannot_be_read_is_polled_then_rolled_back(world: World):
    """(B) An unguarded `$(ssh_ …)` aborts here under `set -e`, mid-deploy."""
    _write(world.ctl / "ssh_fail_match", "SELECT DISTINCT")
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out

    polls = [c for c in world.remote_commands() if "SELECT DISTINCT" in c]
    assert len(polls) == 60, f"the poll ran {len(polls)} time(s), not 60"
    assert "could not be read" in out
    assert "180s" in out
    assert _rolled_back(world), "production was left holding the new tree"


def test_a_wrong_fingerprint_rolls_back_without_blaming_the_read(world: World):
    _write(world.ctl / "worker_version", "deadbeefdead")
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "workers report 'deadbeefdead'" in out
    assert "could not be read" not in out
    polls = [c for c in world.remote_commands() if "SELECT DISTINCT" in c]
    assert len(polls) == 60, f"the poll ran {len(polls)} time(s), not 60"
    assert _rolled_back(world)


# --- the harness cannot reach anything ---------------------------------------


def test_without_the_shims_the_script_reaches_nothing(world: World):
    """The safety layer itself: no shims, no key, no host, no writes.

    Bounded by a timeout rather than waited out: without the `sleep` shim the
    real `ssh_` spends its full 165 s retry budget on a host that is not there.
    The observation is positive rather than "it had not finished yet" — the run
    is required to have reached the access check and failed it.
    """
    before = snapshot(world.fake)
    env = env_for(world, sha=world.sha, path=os.environ["PATH"])
    try:
        proc = run(world, env=env, timeout=12)
        out = both(proc)
        assert proc.returncode != 0, out
    except subprocess.TimeoutExpired as expired:
        out = (expired.stdout or b"").decode(errors="replace") + \
              (expired.stderr or b"").decode(errors="replace")
    assert "REFUSED: no SSH access" in out or "(link dropped" in out, out
    assert "deployed" not in out
    assert snapshot(world.fake) == before


# --- what the host says it holds ---------------------------------------------


def test_the_marker_and_the_manifest_say_what_the_host_holds(world: World):
    """(a) The host measured itself, and the marker records that measurement."""
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 0, out

    expected = expected_manifest(world, world.sha)
    body = (world.app / "DEPLOYED_MANIFEST").read_text()
    assert body.splitlines() == expected
    assert f"host verified: {len(expected)} files match {world.sha}" in out

    # Not just the paths: every hash is the sha256 this test computes from the
    # file the host now holds.
    for line in body.splitlines():
        digest, _, path = line.partition("  ")
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path

    marker = read_marker(world)
    assert marker["sha"] == world.sha
    assert marker["state"] == "installed"
    datetime.strptime(marker["installed_at"], "%Y-%m-%dT%H:%M:%SZ")
    assert marker["manifest_sha256"] == hashlib.sha256(
        (world.app / "DEPLOYED_MANIFEST").read_bytes()).hexdigest()
    assert not (world.app / "DEPLOYED_MANIFEST.new").exists()


def test_bytes_that_do_not_match_the_commit_are_caught_on_the_host(world: World):
    """(b) rsync exited zero and the bytes were still wrong."""
    previous = write_previous_provenance(world, manifest=False)
    # Corrupt the kernel *after* the copy reported success, and photograph the
    # marker at that instant: the end state alone cannot show that the marker
    # was never written `installed` before the bytes were verified.
    _write(world.ctl / "after_hook", f"""#!/usr/bin/env bash
CTL="{world.ctl}"
if [ -f "$CTL/after_hook_ran" ]; then exit 0; fi
printf 'ran\\n' > "$CTL/after_hook_ran"
cat "{world.app}/DEPLOYED_SHA" > "$CTL/marker_at_hook"
printf 'APP = %s\\n' "'CORRUPTED'" > "{world.app}/packages/kernel/atlas_kernel/qevik/app.py"
""", executable=True)

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert (world.ctl / "after_hook_ran").exists(), "the corruption never ran"
    assert f"the bytes on the host do not match {world.sha}" in out
    assert "host verified" not in out
    assert "ROLLED BACK:" in out

    at_hook = dict(line.partition("=")[::2]
                   for line in (world.ctl / "marker_at_hook").read_text().splitlines()
                   if "=" in line)
    assert at_hook["state"] == "installing", at_hook
    assert at_hook["attempted_sha"] == world.sha, at_hook
    assert at_hook["previous_sha"] == "1" * 40, at_hook
    datetime.strptime(at_hook["started_at"], "%Y-%m-%dT%H:%M:%SZ")

    assert (world.app / "DEPLOYED_SHA").read_text() == previous
    assert not (world.app / "DEPLOYED_MANIFEST.new").exists()
    assert _rolled_back(world)


def test_a_host_check_that_cannot_run_is_a_refusal_not_a_pass(world: World):
    """(g) A missing tool must fail closed, exactly like a mismatch."""
    previous = write_previous_provenance(world, manifest=False)
    _write(world.ctl / "no_sha256sum", "1")

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert f"the bytes on the host do not match {world.sha}" in out
    assert "host verified" not in out
    assert "ROLLED BACK:" in out
    assert (world.app / "DEPLOYED_SHA").read_text() == previous
    assert not (world.app / "DEPLOYED_MANIFEST.new").exists()
    assert _rolled_back(world)


# --- a rollback tells the truth ----------------------------------------------


def _assert_previous_targets(world: World, before: dict[str, str]) -> None:
    assert targets_only(snapshot(world.fake)) == targets_only(before)


def test_a_health_failure_restores_every_target_and_the_provenance(world: World):
    """(c) All four targets, the marker and the manifest go back."""
    previous = write_previous_provenance(world)
    previous_manifest = (world.app / "DEPLOYED_MANIFEST").read_text()
    before = snapshot(world.fake)

    # Without this the "unchanged" assertions could pass vacuously.
    for host_rel, source in (
        ("opt/qevik/atlas/packages/kernel/atlas_kernel/qevik/app.py",
         "packages/kernel/atlas_kernel/qevik/app.py"),
        ("opt/qevik/atlas/infra/mission_worker.py", "infra/mission_worker.py"),
        ("srv/qevik-control/index.html", "apps/control/src/index.html"),
        ("etc/systemd/system/qevik-worker.service", "infra/qevik-worker.service"),
    ):
        assert before[host_rel] != hashlib.sha256(S_FILES[source].encode()).hexdigest()

    _write(world.ctl / "health_code", "500")
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "ROLLED BACK:" in out
    assert "deployed" not in out
    assert "the restored bytes match the previous manifest" in out

    _assert_previous_targets(world, before)
    assert (world.app / "DEPLOYED_SHA").read_text() == previous
    assert (world.app / "DEPLOYED_MANIFEST").read_text() == previous_manifest


def test_a_rollback_with_no_previous_marker_says_unknown(world: World):
    """(d) It cannot claim a sha nobody recorded."""
    _write(world.ctl / "health_code", "500")
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out

    marker = read_marker(world)
    assert marker["sha"] == "unknown"
    assert marker["state"] == "rolled-back"
    assert marker["attempted_sha"] == world.sha
    # Nothing recorded what was here, so no manifest may claim to.
    assert not (world.app / "DEPLOYED_MANIFEST").exists()


def test_a_failed_restore_is_never_reported_as_success(world: World):
    """(e) The rollback could not put the kernel back, and says exactly that."""
    write_previous_provenance(world, manifest=False)
    _write(world.ctl / "health_code", "500")
    _write(world.ctl / "fail_cp_dest",
           str(world.app / "packages/kernel/atlas_kernel"))

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 4, out
    assert "ROLLBACK INCOMPLETE" in out
    assert "ROLLED BACK" not in out

    marker = read_marker(world)
    assert marker["state"] == "rollback-incomplete"
    assert "kernel" in marker["not_restored"].split(",")
    assert marker["attempted_sha"] == world.sha
    assert "kernel" not in marker["restored"].split(",")


def test_a_stale_snapshot_is_not_restored_over_a_target_that_was_absent(world: World):
    """A target absent before this deploy has nothing to restore, and says so.

    An earlier deploy leaves its copy at `<rollback>-console`. If the console is
    gone from the host when the next deploy runs, keeping only on the `-e`
    branch would leave that old copy in place — and the rollback, which asks
    nothing but "is there a copy?", would restore the earlier deploy's bytes
    into a path that held nothing and report `ROLLED BACK`.
    """
    stale = "<h1>console STALE</h1>\n"
    shutil.rmtree(world.console)
    _write(world.fake / "opt/qevik/rollback-console/index.html", stale)
    _write(world.ctl / "health_code", "500")

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 4, out
    assert "ROLLBACK INCOMPLETE" in out
    assert "ROLLED BACK:" not in out
    assert "it did not exist before this deploy" in out

    marker = read_marker(world)
    assert marker["state"] == "rollback-incomplete"
    assert "console" in marker["not_restored"].split(","), marker
    # The targets that *were* there still go back, so this is not a rollback
    # that simply gave up.
    assert "kernel" in marker["restored"].split(","), marker

    # The stale copy is gone, and nothing restored it anywhere.
    assert not (world.fake / "opt/qevik/rollback-console").exists()
    assert (world.console / "index.html").read_text() != stale


def test_a_rollback_marker_that_cannot_be_written_is_not_success(world: World):
    """The marker is part of the rollback; a marker that failed is exit 4.

    With no earlier marker to put back, the rollback writes `state=rolled-back`
    itself. If that write fails the host keeps saying `state=installing` — a
    deploy in flight that is not in flight — so reporting `ROLLED BACK` would be
    a claim the host contradicts.
    """
    _write(world.ctl / "health_code", "500")
    # Fails exactly the rolled-back marker write: no other remote command this
    # run sends carries that string.
    _write(world.ctl / "ssh_fail_match", "state=rolled-back")

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 4, out
    assert "ROLLBACK INCOMPLETE" in out
    assert "ROLLED BACK:" not in out
    assert "the marker could not be written" in out

    marker = read_marker(world)
    assert marker["state"] == "rollback-incomplete"
    assert "provenance" in marker["not_restored"].split(","), marker
    assert marker["attempted_sha"] == world.sha
    # The bytes did go back; it is the provenance that did not.
    assert _rolled_back(world)


def test_a_rollback_copy_that_fails_refuses_before_any_transfer(world: World):
    """(f) A rollback that could not be kept is a refusal, not `echo kept`."""
    previous = write_previous_provenance(world, manifest=False)
    before = snapshot(world.fake)
    _write(world.ctl / "fail_cp_dest", str(world.fake / "opt/qevik/rollback"))

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "could not keep the current tree" in out
    assert not [line for line in world.log() if line.startswith("rsync ")]
    assert snapshot(world.fake) == before
    assert (world.app / "DEPLOYED_SHA").read_text() == previous


def test_a_schema_failure_rolls_back(world: World):
    """(h) The step between the copies and the restart is covered too."""
    previous = write_previous_provenance(world, manifest=False)
    before = snapshot(world.fake)
    _write(world.ctl / "schema_fail", "1")

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "the schema could not be applied" in out
    assert "ROLLED BACK:" in out
    _assert_previous_targets(world, before)
    assert (world.app / "DEPLOYED_SHA").read_text() == previous


def test_a_deploy_that_cannot_copy_never_leaves_the_marker_installing(world: World):
    """(i) The marker admits a mixture only while there might be one."""
    _write(world.ctl / "rsync_fail", "1")
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out

    attempts = [line for line in world.log() if line.startswith("rsync ")]
    assert len(attempts) == 12, f"rsync_ tried {len(attempts)} time(s), not 12"
    text = (world.app / "DEPLOYED_SHA").read_text()
    assert "state=installing" not in text, text
    marker = read_marker(world)
    assert marker["state"] == "rolled-back"
    assert marker["sha"] == "unknown"


def test_a_registry_read_that_always_fails_reaches_the_rollback(world: World):
    """(j) An unguarded `$(ssh_ …)` would exit here silently, mid-deploy."""
    _write(world.ctl / "ssh_fail_match", "psql")
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "could not be read" in out
    assert "ROLLED BACK" in out
    assert _rolled_back(world)


# --- rehearse proves the host-side check --------------------------------------


def test_rehearse_reports_the_manifest_and_proves_the_host_check(world: World):
    """(k) Still writes nothing, and refuses a host the deploy would refuse."""
    before = snapshot(world.fake)
    lines = expected_manifest(world, world.sha)

    proc = run(world, "--rehearse", env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 0, out
    assert f"manifest: {len(lines)} files, sha256 {manifest_digest(lines)}" in out
    assert "host sha256sum --check: works" in out
    assert snapshot(world.fake) == before

    _write(world.ctl / "no_sha256sum", "1")
    proc = run(world, "--rehearse", env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 5, out
    assert "host sha256sum --check: DOES NOT WORK" in out
    assert "NOT READY: a real deploy would refuse at the host check" in out
    assert "REHEARSED" not in out
    assert snapshot(world.fake) == before
