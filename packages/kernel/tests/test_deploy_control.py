"""Drive the real `infra/deploy_control.sh` end to end against a fake host.

The invariant these tests exist for is ADR-0010 Step 1: what a deploy ships is
one immutable commit, never the working tree. That cannot be proved by reading
the script — the old script also *looked* like it copied the right thing — so
the script is executed for real, with `ssh`, `rsync`, `systemctl`, `curl` and
friends shimmed onto `PATH` and the host paths pointed at directories under
`tmp_path`. Every negative case below fails against a tree-reading deploy.

Two safety layers, because a test that drives a deploy script is one mistake
away from driving a deploy: every run passes an explicit `qevik-test@127.0.0.1`
target — the script has no production default to fall back to — together with a
`QEVIK_DEPLOY_KEY` that points inside `tmp_path`, and `HOME` is a directory in
`tmp_path` where no real key exists, so a shim that failed to take effect
reaches nothing. One test asserts exactly that.
"""

from __future__ import annotations

import hashlib
import os
import re
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
_TOOLS = {name: shutil.which(name)
          for name in ("git", "rsync", "bash", "shasum", "cp", "mv")}
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


SYSTEMD_RUN_SHIM = r'''#!/usr/bin/env python3
# systemd-run, as far as the deploy uses it.
#
# Reads the environment file the way systemd reads it - as a file, never through
# a shell - and runs the command with it. What this proves locally is that the
# deploy hands over a *path* and never interpolates a value into a command line;
# that systemd's real parser agrees with this one is proved on the host, where
# both the file and the parser live.
import os
import subprocess
import sys

CTL = "@CTL@"
os.makedirs(CTL, exist_ok=True)
with open(os.path.join(CTL, "log"), "a", encoding="utf-8") as fh:
    fh.write("systemd-run " + " ".join(sys.argv[1:]) + "\n")

env = dict(os.environ)
argv = list(sys.argv[1:])
cwd = None
QUOTES = ("'", '"')
while argv:
    arg = argv[0]
    if arg in ("--wait", "--collect", "--pipe", "--quiet"):
        argv.pop(0)
        continue
    if arg.startswith("--property=EnvironmentFile="):
        path = arg.split("=", 2)[2]
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if len(value) >= 2 and value[0] == value[-1] and value[0] in QUOTES:
                    value = value[1:-1]
                env[key.strip()] = value
        argv.pop(0)
        continue
    if arg.startswith("--property=WorkingDirectory="):
        cwd = arg.split("=", 2)[2]
        argv.pop(0)
        continue
    if arg.startswith("--property="):
        argv.pop(0)
        continue
    if arg.startswith("--setenv="):
        key, _, value = arg[len("--setenv="):].partition("=")
        env[key] = value
        argv.pop(0)
        continue
    break
sys.exit(subprocess.run(argv, cwd=cwd, env=env).returncode)
'''

#: The venv python the deploy runs, answering with a digest of what it was given.
SCHEMA_PYTHON = r'''#!/usr/bin/env python3
import hashlib
import os
import sys

if os.path.exists("@CTL@/schema_fail"):
    print("init_db failed", file=sys.stderr)
    raise SystemExit(1)
# The digest, never the value: a test can assert the process saw the exact bytes
# of the environment file without a secret-shaped string appearing in an
# assertion, a log or a failure message.
dsn = os.environ.get("ATLAS_DATABASE_URL", "")
print("dsn-sha=" + hashlib.sha256(dsn.encode()).hexdigest())
print("cwd=" + os.getcwd())
print("schema applied")
'''


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
printf 'ssh %s\\n' "$CMD" >> "$CTL/log"
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
# The whole command, not a substring: `rm -f …/DEPLOYED_MANIFEST` and
# `rm -f …/DEPLOYED_MANIFEST.new` are two different steps of the rollback and a
# substring match cannot fail one without failing the other.
if [ -f "$CTL/ssh_fail_exact" ] && [ "$CMD" = "$(cat "$CTL/ssh_fail_exact")" ]; then
  echo "the test refused: $CMD" >&2
  exit 1
fi
# 255 is ssh's own status for a connection-level failure, which is the one thing
# `ssh_` retries -- and the one thing a caller must not read as an answer from
# the host. Unlike `ssh_drop` this never stops, so the retry budget runs out.
if [ -f "$CTL/ssh_drop_match" ]; then
  MATCH="$(cat "$CTL/ssh_drop_match")"
  case "$CMD" in
    *"$MATCH"*)
      echo "ssh: timed out during banner exchange" >&2
      exit 255 ;;
  esac
fi
# Every atomic marker write is counted, and `fail_marker_write_nth` makes one
# chosen write fail. That is how a test reaches one call site of the script's
# single marker writer without disturbing the others.
case "$CMD" in
  *DEPLOYED_SHA.tmp*)
    MW=0
    [ -f "$CTL/marker_writes" ] && MW="$(cat "$CTL/marker_writes")"
    MW=$((MW + 1))
    printf '%s\\n' "$MW" > "$CTL/marker_writes"
    if [ -f "$CTL/fail_marker_write_nth" ] \\
       && [ "$MW" = "$(cat "$CTL/fail_marker_write_nth")" ]; then
      echo "the test refused marker write #$MW" >&2
      exit 1
    fi ;;
esac
exec bash -c "$CMD"
""", executable=True)

    _write(shims / "rsync", f"""#!/usr/bin/env bash
# Stand in for rsync only as far as the transport: -e and --timeout go, the
# "target:" prefix goes, and every other flag -- -n, -i, --delete, --exclude --
# reaches the real rsync, so a dry run really is a dry run.
{common}
printf 'rsync %s\\n' "$*" >> "$CTL/log"
if [ -f "$CTL/rsync_fail" ]; then
  MATCH="$(cat "$CTL/rsync_fail")"
  case "$*" in *"$MATCH"*) echo "rsync: refused by the test" >&2; exit 1 ;; esac
fi
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
"{real_rsync}" "${{ARGS[@]}}"
RC=$?
# after_hook runs once the bytes have landed, which is where a test can corrupt
# them behind the script's back.
if [ -x "$CTL/after_hook" ]; then "$CTL/after_hook"; fi
exit $RC
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

    _write(shims / "systemd-run", SYSTEMD_RUN_SHIM.replace("@CTL@", str(ctl)),
           executable=True)

    for name in ("chown", "journalctl"):
        _write(shims / name, f"""#!/usr/bin/env bash
{common}
printf '{name} %s\\n' "$*" >> "$CTL/log"
exit 0
""", executable=True)

    _write(shims / "sha256sum", f"""#!/usr/bin/env bash
# macOS has /sbin/sha256sum too, so leaving the tool off PATH cannot prove the
# absent case; `no_sha256sum` is that seam. `--check` is implemented here rather
# than handed to `shasum`, which does not take the host's flags, so the test
# observes the script's own fail-closed behaviour and not the Mac's shasum.
{common}
printf 'sha256sum %s\\n' "$*" >> "$CTL/log"
if [ -f "$CTL/no_sha256sum" ]; then
  echo "sha256sum: command not found" >&2
  exit 127
fi
CHECK=0
SRC=""
for a in "$@"; do
  case "$a" in
    -c|--check) CHECK=1 ;;
    -*) ;;
    *) SRC="$a" ;;
  esac
done
if [ "$CHECK" = 0 ]; then exec shasum -a 256 "$@"; fi
[ -z "$SRC" ] && SRC=-
[ "$SRC" = "-" ] && SRC=/dev/stdin
RC=0
while IFS= read -r line; do
  [ -n "$line" ] || continue
  want="${{line%% *}}"
  path="${{line#*  }}"
  # -r rather than -f: the rehearsal's known input is /dev/null, which the real
  # tool hashes happily and which is not a regular file.
  if [ ! -r "$path" ] || [ -d "$path" ]; then
    echo "$path: FAILED open or read" >&2; RC=1; continue
  fi
  got="$(shasum -a 256 "$path" | cut -d' ' -f1)"
  if [ "$got" != "$want" ]; then echo "$path: FAILED" >&2; RC=1; fi
done < "$SRC"
exit $RC
""", executable=True)

    for name, gate in (("cp", "fail_cp_dest"), ("mv", "fail_mv_dest")):
        _write(shims / name, f"""#!/usr/bin/env bash
# The real tool, except that a destination the test names fails. Only the
# destination is matched, so a test can fail a restore without failing the
# snapshot that feeds it.
{common}
printf '{name} %s\\n' "$*" >> "$CTL/log"
if [ -f "$CTL/{gate}" ]; then
  PAT="$(cat "$CTL/{gate}")"
  DEST=""
  for a in "$@"; do DEST="$a"; done
  case "$DEST" in
    *"$PAT"*) echo "{name}: refused by the test: $DEST" >&2; exit 1 ;;
  esac
fi
exec "{_TOOLS[name]}" "$@"
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
           SCHEMA_PYTHON.replace("@CTL@", str(ctl)), executable=True)
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
    # path inside the repository and the export check would count it. The target
    # resolver and its registry travel with it — the script sources them, so a
    # deploy that could not find them would fail before it did anything, and the
    # tests would be proving that instead of what they are here for.
    shutil.copy2(SCRIPT, repo / "infra" / "deploy_control.sh")
    (repo / "infra" / "deploy_control.sh").chmod(0o755)
    shutil.copy2(REPO_ROOT / "infra" / "deploy_target.sh", repo / "infra" / "deploy_target.sh")
    shutil.copy2(REPO_ROOT / "infra" / "deploy_targets.conf", repo / "infra" / "deploy_targets.conf")
    # An identity that exists, inside tmp_path. The script refuses a raw host
    # without one, which is the point: an approved identity is never inferred.
    _write(home / ".ssh" / "deploy_key", "not a real key\n")
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
    env["QEVIK_DEPLOY_KEY"] = str(world.home / ".ssh" / "deploy_key")
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


def rsync_calls(world: World, needle: str) -> list[str]:
    """The rsync invocations the script made, matching `needle`.

    A local-to-local transfer makes real rsync re-exec itself as `rsync
    --server`, and the shim is first on PATH, so it logs that child too. Only
    the script's own calls carry `--timeout=120` — the shim strips it before
    handing the rest to the real tool — so that is what tells them apart.
    """
    return [line for line in world.log()
            if line.startswith("rsync ") and "--timeout=120" in line
            and needle in line]


# --- provenance and manifest helpers -----------------------------------------

PREV_SHA = "1" * 40


def marker_path(world: World) -> Path:
    return world.app / "DEPLOYED_SHA"


def manifest_path(world: World) -> Path:
    return world.app / "DEPLOYED_MANIFEST"


def read_marker(world: World) -> dict[str, str]:
    path = marker_path(world)
    if not path.exists():
        return {}
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            fields.setdefault(key, value)
    return fields


def host_manifest_for(paths: dict[Path, str]) -> str:
    """The `sha256sum --check` file the script writes: two spaces, C-sorted."""
    lines = [f"{hashlib.sha256(text.encode()).hexdigest()}  {path}"
             for path, text in paths.items()]
    return "".join(f"{line}\n" for line in sorted(lines))


def expected_manifest(world: World) -> str:
    """What the manifest for S must say, computed independently of the script."""
    paths: dict[Path, str] = {}
    for rel, text in S_FILES.items():
        if rel.startswith("packages/kernel/atlas_kernel/"):
            paths[world.app / rel] = text
        elif rel.startswith("infra/"):
            paths[world.app / rel] = text
            if rel.startswith("infra/qevik-") and rel.endswith(".service"):
                paths[world.units / Path(rel).name] = text
        elif rel.startswith("apps/control/src/"):
            paths[world.console / rel[len("apps/control/src/"):]] = text
    # The script itself is a tracked file under infra/ and ships with the rest —
    # and so do the target resolver and its registry, which the script sources.
    for name in ("deploy_control.sh", "deploy_target.sh", "deploy_targets.conf"):
        paths[world.app / "infra" / name] = (
            (world.repo / "infra" / name).read_text(encoding="utf-8"))
    return host_manifest_for(paths)


def previous_manifest(world: World) -> str:
    """A manifest that describes the host exactly as OLD_HOST leaves it."""
    return host_manifest_for({world.fake / rel: text for rel, text in OLD_HOST.items()})


def plant_previous(world: World, *, marker: bool = True, manifest: bool = True) -> str:
    """Give the fake host the provenance a previously deployed host would have."""
    text = previous_manifest(world)
    if manifest:
        _write(manifest_path(world), text)
    if marker:
        _write(marker_path(world),
               "state=installed\n"
               f"sha={PREV_SHA}\n"
               "installed_at=2026-01-01T00:00:00Z\n"
               f"manifest_sha256={hashlib.sha256(text.encode()).hexdigest()}\n")
    return marker_path(world).read_text(encoding="utf-8") if marker else ""


def deployed_state(world: World) -> dict[str, str]:
    """Everything this deploy can change, minus its own rollback scratch."""
    return {rel: value for rel, value in snapshot(world.fake).items()
            if not rel.startswith("opt/qevik/rollback")}


# --- the payload is the commit ----------------------------------------------


def test_ships_the_commit_not_the_working_tree(world: World):
    """(a) HEAD has moved on; every byte on the host is still S's."""
    commit(world, DRIFT_FILES, message="after S")
    assert _git(world.repo, "rev-parse", "HEAD", home=world.home).stdout.strip() != world.sha
    assert not _git(world.repo, "status", "--porcelain", home=world.home).stdout

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 0, out
    assert f"deployed {world.sha}" in out

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


def test_a_symlink_under_a_deployed_subtree_is_refused(world: World):
    """(A) The manifest verifies content, and a link has none.

    `rsync -a` ships a link as a link, so nothing the host can hash describes
    it: the check would pass whatever the link points at. Refusing the commit is
    what makes the manifest's `-type f` exhaustive, and it happens before the
    host is contacted at all.
    """
    sha = commit(world, symlinks={"infra/latest.py": "mission_worker.py"},
                 message="add a tracked link under infra")
    before = snapshot(world.fake)
    proc = run(world, env=env_for(world, sha=sha))
    _assert_refused_untouched(world, proc, before, 2)
    assert "ships a symlink under infra" in both(proc)


def test_a_symlink_outside_every_deployed_subtree_is_not_refused(world: World):
    """The negative control: the refusal is about what ships, not the repo."""
    sha = commit(world, symlinks={"packages/kernel/other/link.py": "../notes.txt"},
                 message="a link nothing deploys")
    proc = run(world, env=env_for(world, sha=sha))
    out = both(proc)
    assert proc.returncode == 0, out
    assert "ships a symlink" not in out
    assert f"deployed {sha}" in out


def test_a_utf8_filename_verifies(world: World):
    """git quotes non-ASCII paths by default, and a quoted path is not found."""
    sha = commit(world, {"apps/control/src/café.html": "<h1>café</h1>\n"},
                 message="a name git would quote")
    proc = run(world, env=env_for(world, sha=sha))
    out = both(proc)
    assert proc.returncode == 0, out
    assert f"export verified: 9 files from {sha}" in out


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
    assert f"export verified: 8 files from {world.sha}" in out

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
    # Nothing was restarted before the schema step; every restart in the log is
    # the rollback putting the services back.
    log = world.log()
    schema_at = next(i for i, line in enumerate(log) if "init_db" in line)
    assert not [line for line in log[:schema_at]
                if line.startswith("systemctl restart")]
    assert "ROLLED BACK:" in out


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
    assert "ROLLED BACK:" in out
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


def test_the_marker_and_the_manifest_describe_the_installed_bytes(world: World):
    """(8a) The marker names S, and the manifest is measured, not asserted."""
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 0, out

    manifest = manifest_path(world)
    assert manifest.read_text(encoding="utf-8") == expected_manifest(world)
    assert not (world.app / "DEPLOYED_MANIFEST.new").exists()

    # Every line of the manifest is checked against the host's own bytes here,
    # by this test, rather than trusted because the script said so.
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, _, path = line.partition("  ")
        assert Path(path).is_file(), path
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path

    marker = read_marker(world)
    assert marker["state"] == "installed"
    assert marker["sha"] == world.sha
    datetime.strptime(marker["installed_at"], "%Y-%m-%dT%H:%M:%SZ")
    assert marker["manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert f"host verified: {len(expected_manifest(world).splitlines())} files" in out
    # No secret ever reaches either file.
    assert "DATABASE_URL" not in manifest.read_text(encoding="utf-8")
    assert "DATABASE_URL" not in marker_path(world).read_text(encoding="utf-8")


def test_the_manifest_lists_every_file_the_transfers_actually_send(world: World):
    """A deployed file the manifest omits is a file the host never checked.

    The exclusions used to be written twice — as `--exclude` flags on the
    transfers and as `find` predicates in the manifest — and the two copies
    disagreed. The console transfer excluded nothing while the manifest dropped
    `*.pyc`, `__pycache__` and `.pytest_cache`; the kernel transfer did not
    exclude `.pytest_cache` while the manifest did. git does not care what a
    tracked file is called, so each path below really is copied to the host, and
    each one used to land there with no line in the manifest describing it —
    leaving `state=installed` recorded over bytes the host check never saw.
    """
    tracked = {
        "apps/control/src/vendor.pyc": "a console blob that happens to be named .pyc\n",
        "apps/control/src/__pycache__/keep.txt": "a console asset under that name\n",
        "apps/control/src/.pytest_cache/keep.txt": "and under that one\n",
        "packages/kernel/atlas_kernel/.pytest_cache/keep.txt": "kernel, shipped\n",
    }
    sha = commit(world, tracked, message="paths the two lists disagreed about")

    proc = run(world, env=env_for(world, sha=sha))
    out = both(proc)
    assert proc.returncode == 0, out

    manifest = manifest_path(world).read_text(encoding="utf-8")
    listed = {line.partition("  ")[2] for line in manifest.splitlines()}
    for rel, text in tracked.items():
        if rel.startswith("apps/control/src/"):
            host = world.console / rel[len("apps/control/src/"):]
        else:
            host = world.app / rel
        assert host.is_file(), f"{rel} was not deployed at all"
        assert host.read_text() == text, rel
        assert str(host) in listed, f"{rel} is on the host and not in the manifest"

    # And the manifest is still a description of the host rather than a claim:
    # every line of it holds.
    for line in manifest.splitlines():
        digest, _, path = line.partition("  ")
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path


def test_a_file_a_transfer_excludes_is_neither_shipped_nor_listed(world: World):
    """The other direction of the same rule: one list, read both ways.

    A manifest line for a file the deploy does not send would fail the host
    check and roll back a good deploy, so agreement has to hold both ways.
    """
    excluded = [
        "infra/stale.pyc",
        "infra/__pycache__/mission_worker.cpython-312.pyc",
        "infra/.pytest_cache/CACHEDIR.TAG",
        "packages/kernel/atlas_kernel/__pycache__/app.cpython-312.pyc",
        "packages/kernel/atlas_kernel/qevik/old.pyc",
    ]
    sha = commit(world, {rel: f"# {rel}\n" for rel in excluded},
                 message="paths every transfer excludes")

    proc = run(world, env=env_for(world, sha=sha))
    out = both(proc)
    assert proc.returncode == 0, out

    manifest = manifest_path(world).read_text(encoding="utf-8")
    for rel in excluded:
        host = world.app / rel
        assert not host.exists(), f"{rel} was shipped despite the exclusion"
        assert str(host) not in manifest, f"{rel} is in the manifest and not on the host"


def test_the_exclusions_are_written_down_once():
    """The structural half: a transfer may not carry its own copy of the list.

    This is what stops the two lists drifting apart again. Every `--exclude`
    flag in the script is produced from a named set, and both the transfers and
    `manifest_lines` take that same set.
    """
    literal = re.compile(r"--exclude(?![-\w])")
    lines = [line for line in SCRIPT.read_text(encoding="utf-8").splitlines()
             if literal.search(line) and not line.strip().startswith("#")]
    assert lines, "the exclusions vanished entirely"
    for line in lines:
        assert "RSYNC_EXCLUDE+=(--exclude" in line, (
            "a --exclude flag is spelled out at a transfer instead of coming "
            f"from the named set the manifest also reads: {line}")


def test_a_byte_mismatch_on_the_host_is_caught_and_rolled_back(world: World):
    """(8b) rsync exited zero and the bytes are still wrong."""
    plant_previous(world)
    kept = marker_path(world).read_text(encoding="utf-8")
    kernel = world.app / "packages/kernel/atlas_kernel/qevik/app.py"
    _write(world.ctl / "after_hook", f"""#!/usr/bin/env bash
CTL="{world.ctl}"
[ -f "$CTL/after_hook_ran" ] && exit 0
printf 'ran\\n' > "$CTL/after_hook_ran"
cat "{marker_path(world)}" > "$CTL/marker_at_hook" 2>/dev/null
printf 'CORRUPTED\\n' > "{kernel}"
""", executable=True)

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert (world.ctl / "after_hook_ran").exists(), "nothing was ever corrupted"
    assert f"the bytes on the host do not match {world.sha}" in out
    assert "ROLLED BACK:" in out
    assert "host verified" not in out

    # The end state cannot show the *order* the marker was written in, so the
    # hook kept a copy: while the bytes were in flight the marker said so.
    at_hook = (world.ctl / "marker_at_hook").read_text(encoding="utf-8")
    assert "state=installing" in at_hook
    assert f"attempted_sha={world.sha}" in at_hook

    assert marker_path(world).read_text(encoding="utf-8") == kept
    assert kernel.read_text() == OLD_HOST[
        "opt/qevik/atlas/packages/kernel/atlas_kernel/qevik/app.py"]
    assert not (world.app / "DEPLOYED_MANIFEST.new").exists()


def test_a_health_failure_restores_every_target_and_the_previous_marker(world: World):
    """(8c) Four targets and both provenance files, byte for byte."""
    plant_previous(world)
    kept_marker = marker_path(world).read_text(encoding="utf-8")
    kept_manifest = manifest_path(world).read_text(encoding="utf-8")
    _write(world.ctl / "health_code", "500")

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "ROLLED BACK:" in out
    assert "deployed" not in out

    for rel, text in OLD_HOST.items():
        assert (world.fake / rel).read_text() == text, rel
    assert marker_path(world).read_text(encoding="utf-8") == kept_marker
    assert manifest_path(world).read_text(encoding="utf-8") == kept_manifest
    assert not (world.app / "DEPLOYED_MANIFEST.new").exists()
    # The pre-deploy content differs from S's everywhere, so none of the above
    # could have passed without a restore.
    for rel, text in OLD_HOST.items():
        assert text not in S_FILES.values(), rel

    # The rollback restarts the way the deploy does: control and api together,
    # then each worker on its own with `reset-failed` first.
    log = world.log()
    assert "systemctl restart qevik-control.service qevik-api.service" in log
    for unit in ("qevik-worker.service", "qevik-worker-research.service",
                 "qevik-worker-delivery.service", "qevik-worker-publish.service",
                 "qevik-worker-healthcheck.service"):
        assert f"systemctl reset-failed {unit}" in log
        assert f"systemctl restart {unit}" in log


def test_restored_bytes_are_measured_against_the_previous_manifest(world: World):
    """A restore that put the wrong bytes back is not a rollback.

    `cp -a` exiting zero says the copy ran, not that the host now holds what it
    held. The previous manifest is the only description of that, so the rollback
    checks it — and a target that fails the check stops being counted as
    restored, rather than appearing on both lists.
    """
    plant_previous(world)
    stale = previous_manifest(world).replace(
        str(world.app / "infra/mission_worker.py"),
        str(world.app / "infra/mission_worker.py") + ".gone")
    _write(manifest_path(world), stale)
    _write(world.ctl / "health_code", "500")

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 4, out
    assert "do NOT match the previous manifest" in out
    assert "ROLLBACK INCOMPLETE" in out
    assert "ROLLED BACK" not in out

    marker = read_marker(world)
    assert marker["state"] == "rollback-incomplete"
    assert marker["restored"] == "none"
    for target in ("kernel", "infra", "console", "units"):
        assert target in marker["not_restored"]


def test_a_health_failure_with_no_previous_marker_says_unknown(world: World):
    """(8d) A host that recorded nothing gets an honest marker, not a guess."""
    _write(world.ctl / "health_code", "500")
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "ROLLED BACK:" in out

    marker = read_marker(world)
    assert marker["state"] == "rolled-back"
    assert marker["sha"] == "unknown"
    assert marker["attempted_sha"] == world.sha
    assert not manifest_path(world).exists()


def test_a_failed_restore_is_never_reported_as_a_rollback(world: World):
    """(8e) The restore fails; the word `ROLLED BACK` must not appear."""
    _write(world.ctl / "fail_cp_dest",
           str(world.app / "packages/kernel/atlas_kernel"))
    _write(world.ctl / "health_code", "500")

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 4, out
    assert "ROLLBACK INCOMPLETE" in out
    assert "ROLLED BACK" not in out

    marker = read_marker(world)
    assert marker["state"] == "rollback-incomplete"
    assert "kernel" in marker["not_restored"]
    assert marker["attempted_sha"] == world.sha


def test_a_failed_rollback_copy_refuses_before_any_transfer(world: World):
    """(8f) `echo kept` used to mask this; now nothing is transferred."""
    _write(world.ctl / "fail_cp_dest", str(world.fake / "opt/qevik/rollback"))
    before = deployed_state(world)

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "could not keep the current tree" in out
    assert not [line for line in world.log() if line.startswith("rsync ")]
    assert deployed_state(world) == before
    assert not marker_path(world).exists(), "an `installing` marker was written"


def test_a_host_check_that_cannot_run_is_a_refusal(world: World):
    """(8g) A missing tool is a refusal, never a pass.

    No previous manifest is planted on purpose: with `sha256sum` gone the
    rollback could not measure one either, and it would then — correctly — say
    ROLLBACK INCOMPLETE. What is under test here is that the *check* fails
    closed, so the run is given nothing it cannot measure.
    """
    plant_previous(world, manifest=False)
    kept = marker_path(world).read_text(encoding="utf-8")
    _write(world.ctl / "no_sha256sum", "1")

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert f"the bytes on the host do not match {world.sha}" in out
    assert "host verified" not in out
    assert "ROLLED BACK:" in out
    assert marker_path(world).read_text(encoding="utf-8") == kept


def test_a_schema_failure_rolls_back(world: World):
    """(8h) The step between the copies and the first restart."""
    plant_previous(world)
    kept = marker_path(world).read_text(encoding="utf-8")
    _write(world.ctl / "schema_fail", "1")

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "the schema could not be applied" in out
    assert "ROLLED BACK:" in out
    for rel, text in OLD_HOST.items():
        assert (world.fake / rel).read_text() == text, rel
    assert marker_path(world).read_text(encoding="utf-8") == kept


def test_a_transfer_that_exhausts_its_retries_does_not_leave_installing(world: World):
    """(8i) A deploy that dies mid-copy must not leave `installing` behind."""
    _write(world.ctl / "rsync_fail", "packages/kernel/atlas_kernel/")

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "the kernel could not be copied" in out
    attempts = [line for line in world.log()
                if line.startswith("rsync ") and "atlas_kernel/" in line]
    assert len(attempts) == 12, f"rsync_ tried {len(attempts)} time(s), not 12"

    marker = read_marker(world)
    assert marker["state"] == "rolled-back"
    assert marker["sha"] == "unknown"


def test_the_fingerprint_poll_reads_are_both_guarded(world: World):
    """(8j) `:220` — an unguarded read exits the script with the host written."""
    _write(world.ctl / "ssh_fail_match", "psql")
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "could not be read" in out
    assert "ROLLED BACK" in out
    assert _rolled_back(world)


def test_the_second_fingerprint_read_is_guarded_too(world: World):
    """The count read alone: the first answers, the second does not."""
    _write(world.ctl / "ssh_fail_match", "count(*)")
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "could not be read" in out
    assert "ROLLED BACK" in out
    assert _rolled_back(world)


# --- rollback hygiene: absence, promotion ------------------------------------


def test_an_absent_target_is_never_restored_from_a_stale_snapshot(world: World):
    """(F1) A stale snapshot at every rollback path, and an absent console.

    The old copy step left whatever was already at the rollback path when the
    live target was missing, so a later failure restored unrelated old content
    and called it a rollback.
    """
    rollback = world.fake / "opt/qevik/rollback"
    for suffix in ("", "-infra", "-console", "-units"):
        _write(Path(f"{rollback}{suffix}") / "stale.py", "STALE = 'from last week'\n")
    shutil.rmtree(world.console)
    _write(world.ctl / "health_code", "500")

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 4, out
    assert "ROLLBACK INCOMPLETE" in out
    assert "ROLLED BACK" not in out
    assert "console was absent before this deploy" in out

    marker = read_marker(world)
    assert marker["state"] == "rollback-incomplete"
    assert "console" in marker["not_restored"]

    stale = [path for path in world.fake.rglob("stale.py")
             if not str(path).startswith(str(rollback))]
    assert not stale, f"a stale snapshot was restored: {stale}"
    assert (world.app / "packages/kernel/atlas_kernel/qevik/app.py").read_text() \
        == OLD_HOST["opt/qevik/atlas/packages/kernel/atlas_kernel/qevik/app.py"]


def test_a_dropped_link_reading_the_saved_provenance_is_not_read_as_absence(world: World):
    """(F4) "the link went down" and "nothing was recorded" are not the same.

    The two facts the rollback depends on -- was a marker kept, was a manifest
    kept -- used to be read as `if ssh_ "[ -f … ]"`, where a link that exhausted
    its retries is indistinguishable from a file that is not there. Believing
    absence is the expensive direction: the rollback would put `sha=unknown`
    over a real previous marker and *remove* the manifest it was supposed to
    restore, with both snapshots sitting on the host the whole time.

    So the probe refuses instead, while the live tree is still untouched.
    """
    plant_previous(world)
    kept_marker = marker_path(world).read_text(encoding="utf-8")
    kept_manifest = manifest_path(world).read_text(encoding="utf-8")
    before = deployed_state(world)
    _write(world.ctl / "ssh_drop_match", "saved marker=")

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "could not be asked what it had kept" in out
    assert "Nothing has been transferred." in out
    assert "deployed" not in out

    # A refusal, not a rollback: nothing was copied and no marker was written.
    assert not [line for line in world.log() if line.startswith("rsync ")]
    assert "ROLLED BACK" not in out and "ROLLBACK INCOMPLETE" not in out
    assert marker_path(world).read_text(encoding="utf-8") == kept_marker
    assert manifest_path(world).read_text(encoding="utf-8") == kept_manifest
    assert deployed_state(world) == before

    # 255 is the one status `ssh_` retries, so the refusal is only reached once
    # the whole budget is spent -- not on the first lost packet.
    attempts = [c for c in world.remote_commands() if "saved marker=" in c]
    assert len(attempts) == 12, f"the probe ran {len(attempts)} time(s), not 12"


def test_a_manifest_that_cannot_be_removed_is_not_a_rollback(world: World):
    """(F5) Two provenance files may never contradict each other.

    With nothing recorded before the deploy there is no previous manifest to
    restore, so the rollback removes the attempted sha's. When that removal
    fails, the host is left describing S's files in `DEPLOYED_MANIFEST` while
    holding the previous bytes. Reporting `ROLLED BACK` over that is the failure
    under test: it has to be `rollback-incomplete`, naming `provenance`.
    """
    assert not marker_path(world).exists() and not manifest_path(world).exists()
    _write(world.ctl / "ssh_fail_exact", f"rm -f {manifest_path(world)}")
    # Fail late, after the manifest has been promoted, so there is a real
    # manifest for S on the host at the moment the rollback tries to remove it.
    _write(world.ctl / "worker_version", "deadbeefdead")

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 4, out
    assert "the manifest for" in out and "could not be removed" in out
    assert "ROLLBACK INCOMPLETE" in out
    assert "ROLLED BACK" not in out

    marker = read_marker(world)
    assert marker["state"] == "rollback-incomplete"
    assert "provenance" in marker["not_restored"]
    assert marker["attempted_sha"] == world.sha
    # The bytes really did go back -- the incompleteness is the provenance
    # alone, which is exactly what the marker has to say.
    assert _rolled_back(world)
    for target in ("kernel", "infra", "console", "units"):
        assert target in marker["restored"], marker
    # And the contradiction the marker is admitting to is really there.
    assert manifest_path(world).read_text(encoding="utf-8") == expected_manifest(world)


def test_a_failed_manifest_promotion_rolls_back(world: World):
    """(F3) `mv M.new M || [ -f M ]` used to pass whenever an old M existed."""
    plant_previous(world)
    kept_marker = marker_path(world).read_text(encoding="utf-8")
    kept_manifest = manifest_path(world).read_text(encoding="utf-8")
    _write(world.ctl / "fail_mv_dest", str(manifest_path(world)))

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "the manifest could not be promoted" in out
    assert "ROLLED BACK:" in out
    marker = read_marker(world)
    assert not (marker.get("state") == "installed" and marker.get("sha") == world.sha)
    assert marker_path(world).read_text(encoding="utf-8") == kept_marker
    assert manifest_path(world).read_text(encoding="utf-8") == kept_manifest


# --- the class: one checked writer, and every one of its call sites ----------


def _provenance_call_sites() -> list[str]:
    sites = []
    for line in SCRIPT.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "provenance_write " in stripped:
            sites.append(stripped)
    return sites


def test_the_marker_has_exactly_one_writer():
    """Every atomic marker write lives inside `provenance_write`, and only there."""
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines)
                 if line.startswith("provenance_write() {"))
    end = next(i for i, line in enumerate(lines[start:], start) if line == "}")
    writes = [i for i, line in enumerate(lines) if "DEPLOYED_SHA.tmp" in line]
    assert writes, "the marker is not written atomically anywhere"
    outside = [lines[i] for i in writes if not start < i < end]
    assert not outside, f"the marker is written outside provenance_write: {outside}"


# Each row drives one call site of `provenance_write` into failure and states
# what the host and the exit code must then say. A row that passes while another
# fails is a failing test: the point is the class, not the instance.
PROVENANCE_SITES = [
    # id, nth marker write to fail, previous provenance, health, cp failure,
    # exit, marker state at exit, `provenance` in not_restored
    ("installing", 1, True, None, False, 1, "installed", False),
    ("installed", 2, True, None, False, 1, "installed", False),
    ("rolling-back", 2, True, 500, False, 4, "rollback-incomplete", True),
    ("previous-verbatim", 3, True, 500, False, 4, "rollback-incomplete", True),
    ("rolled-back", 3, False, 500, False, 4, "rollback-incomplete", True),
    ("rollback-incomplete", 3, False, 500, True, 4, "rolling-back", True),
]


def test_every_provenance_write_has_a_case_below():
    sites = _provenance_call_sites()
    assert len(sites) == len(PROVENANCE_SITES), (
        f"{len(sites)} call site(s) of provenance_write, "
        f"{len(PROVENANCE_SITES)} exercised:\n" + "\n".join(sites))


@pytest.mark.parametrize(
    "site,nth,previous,health,cp_fails,code,state,blames_provenance",
    PROVENANCE_SITES, ids=[row[0] for row in PROVENANCE_SITES])
def test_a_failed_marker_write_is_never_reported_as_success(
        world: World, site: str, nth: int, previous: bool, health: int | None,
        cp_fails: bool, code: int, state: str, blames_provenance: bool):
    if previous:
        plant_previous(world)
    if health is not None:
        _write(world.ctl / "health_code", str(health))
    if cp_fails:
        _write(world.ctl / "fail_cp_dest",
               str(world.app / "packages/kernel/atlas_kernel"))
    _write(world.ctl / "fail_marker_write_nth", str(nth))

    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)

    written = int((world.ctl / "marker_writes").read_text().strip() or 0)
    assert written >= nth, f"marker write #{nth} ({site}) was never reached"

    assert proc.returncode == code, out
    if code == 1:
        assert "ROLLED BACK:" in out and "ROLLBACK INCOMPLETE" not in out
    else:
        assert "ROLLBACK INCOMPLETE:" in out and "ROLLED BACK:" not in out
    assert "deployed " not in out

    marker = read_marker(world)
    assert marker.get("state") == state, marker
    # The one thing the marker may never say unless it is true.
    assert not (marker.get("state") == "installed" and marker.get("sha") == world.sha)
    assert marker.get("state") != "installing"
    if state == "installed":
        assert marker.get("sha") == PREV_SHA, "the previous marker was not restored"
    if blames_provenance and state == "rollback-incomplete":
        assert "provenance" in marker["not_restored"], marker
    if site == "rollback-incomplete":
        # The marker for the outcome itself failed: say so rather than let a
        # reader take `rolling-back` for a recorded end state.
        assert "provenance: marker write failed; host marker state unknown" in out


# --- rehearse ----------------------------------------------------------------


def test_rehearse_proves_the_host_check_and_still_writes_nothing(world: World):
    """(8k) The manifest is stated and the host's checker is exercised."""
    before = snapshot(world.fake)
    proc = run(world, "--rehearse", env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 0, out
    assert snapshot(world.fake) == before

    manifest = expected_manifest(world)
    digest = hashlib.sha256(manifest.encode()).hexdigest()
    assert f"manifest: {len(manifest.splitlines())} file(s) for {world.sha}, " \
           f"digest {digest}" in out
    assert "host sha256sum --check: works" in out
    assert f"REHEARSED sha={world.sha}" in out


def test_rehearse_plans_the_manifest_transfer_too(world: World):
    """Every transfer a real run makes, including the last one.

    The manifest copy is the only transfer whose destination is $REMOTE_APP
    itself rather than a subtree below it, so it is the only one that can fail
    on a host where every subtree is writable. A rehearsal that skipped it
    reported a ready host for a deploy that would fail at its last copy.
    """
    before = snapshot(world.fake)
    proc = run(world, "--rehearse", env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 0, out
    assert snapshot(world.fake) == before

    assert "[rehearse] the manifest" in out
    planned = rsync_calls(world, "DEPLOYED_MANIFEST.new")
    assert len(planned) == 1, "\n\n".join(planned)
    assert "-n" in planned[0].split(), planned[0]
    assert not (world.app / "DEPLOYED_MANIFEST.new").exists()
    assert "manifest=" in out.split("REHEARSED ")[1].splitlines()[0]

    # The rehearsal plans the transfer the real run makes: the same manifest to
    # the same destination, differing only by the dry run.
    real = run(world, env=env_for(world, sha=world.sha))
    assert real.returncode == 0, both(real)
    sent = [line.split() for line in rsync_calls(world, "DEPLOYED_MANIFEST.new")]
    assert len(sent) == 2, sent
    for tokens in sent:
        assert tokens[-1] == f"{TARGET}:{world.app}/DEPLOYED_MANIFEST.new", tokens
        assert tokens[-2].endswith("/DEPLOYED_MANIFEST"), tokens
    assert "-n" in sent[0] and "-n" not in sent[1], sent


def test_a_rehearsal_fails_when_only_the_manifest_transfer_cannot_be_planned(world: World):
    """The negative control: the new plan is really exercising the host.

    Every subtree accepts its copy and only the application root refuses. Before
    the manifest was rehearsed this run printed REHEARSED and exited zero.
    """
    before = snapshot(world.fake)
    _write(world.ctl / "rsync_fail", "DEPLOYED_MANIFEST.new")

    proc = run(world, "--rehearse", env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "[rehearse] the manifest" in out
    assert "that transfer could not be planned" in out
    assert "REHEARSED" not in out
    # The transfers before it were planned, so the failure is the manifest's
    # alone rather than a rehearsal that never got started.
    assert "[rehearse] the kernel" in out and "[rehearse] infra" in out
    assert snapshot(world.fake) == before


def test_rehearse_says_not_ready_when_the_host_check_cannot_run(world: World):
    """The negative control for the line above, and exit 5."""
    before = snapshot(world.fake)
    _write(world.ctl / "no_sha256sum", "1")
    proc = run(world, "--rehearse", env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 5, out
    assert "host sha256sum --check: DOES NOT WORK" in out
    assert "NOT READY: a real deploy would refuse at the host check" in out
    assert "REHEARSED" not in out
    assert snapshot(world.fake) == before


# --- the environment file, and the password it is allowed to contain ----------
#
# A high-entropy password is a string of arbitrary bytes. The deploy used to
# read `/opt/qevik/atlas.env` with `set -a && . $ENV_FILE` — a shell — so `$`,
# a backtick, a quote, a space or a semicolon in the value either broke the
# deploy or, worse, changed the value silently. The fix is in the deploy, not in
# the password: nothing here may constrain what a credential is allowed to be.

#: Every shell metacharacter that matters, in one value. `$(id)` and the
#: backtick would execute; the quotes and the backslash would be eaten; the
#: semicolon and the pipe would end the command; the space would split it.
NASTY = "p@ss w'or\"d`$(id)`;|&<>\\#$HOME*?[]{}!"
NASTY_DSN = f"postgresql+psycopg://qevik:{NASTY}@127.0.0.1:5432/qevik"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _env_file_with(world: World, dsn: str) -> None:
    _write(world.fake / "opt/qevik/atlas.env", f"ATLAS_DATABASE_URL={dsn}\n")


def test_the_schema_step_sees_the_password_byte_for_byte(world: World):
    """The value reaches the process exactly as the file holds it.

    Compared by digest, never printed: an assertion that echoes a credential is
    a credential in a CI log.
    """
    _env_file_with(world, NASTY_DSN)
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 0, out
    assert f"dsn-sha={_sha(NASTY_DSN)}" in out, "the schema step saw different bytes"


def test_the_deploy_never_puts_the_value_on_a_command_line(world: World):
    """A path is handed over, not a value — so no log, argv or transcript holds it."""
    _env_file_with(world, NASTY_DSN)
    proc = run(world, env=env_for(world, sha=world.sha))
    assert proc.returncode == 0, both(proc)

    schema_calls = [c for c in world.remote_commands() if "init_db" in c]
    assert len(schema_calls) == 1, schema_calls
    command = schema_calls[0]
    assert "EnvironmentFile=" in command, command
    assert "set -a" not in command and ". /" not in command, command
    for fragment in (NASTY, "p@ss", "$(id)"):
        assert fragment not in command, "a secret fragment reached the command line"
    # Nor anywhere else the run wrote: the shim log is every command that ran.
    assert not [line for line in world.log() if NASTY in line]
    assert NASTY not in both(proc)


def test_the_schema_step_runs_as_the_service_account_in_the_app_directory(world: World):
    """Same identity and same directory as the units, so it sees the same database."""
    _env_file_with(world, NASTY_DSN)
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 0, out
    command = [c for c in world.remote_commands() if "init_db" in c][0]
    assert "--property=User=qevik" in command, command
    assert f"--property=WorkingDirectory={world.app}" in command, command
    assert f"cwd={world.app}" in out, out


def test_the_old_shell_form_would_have_failed_on_the_same_value(world: World):
    """The negative control.

    Without it, the test above passes just as well against a deploy that never
    had the bug. This runs the *previous* implementation against the same file
    and shows it does not survive it — either it fails outright or it hands the
    process a different value.
    """
    _env_file_with(world, NASTY_DSN)
    env_file = world.fake / "opt/qevik/atlas.env"
    done = subprocess.run(
        ["bash", "-c", f'set -a && . "{env_file}" && set +a && '
                       f'printf "%s" "$ATLAS_DATABASE_URL"'],
        capture_output=True, text=True, timeout=60)
    assert done.returncode != 0 or _sha(done.stdout) != _sha(NASTY_DSN), (
        "the shell form survived the value; this control proves nothing")


def test_a_failing_schema_step_still_rolls_back(world: World):
    """The transport changed; the consequence of a failure did not."""
    _write(world.ctl / "schema_fail", "1")
    proc = run(world, env=env_for(world, sha=world.sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "the schema could not be applied" in out
    assert "ROLLED BACK" in out


# --- timers ship with the code, and are still not started by a deploy ---------

TIMER = ("[Unit]\nDescription=a shipped timer\n\n[Timer]\nOnCalendar=*-*-* 05:00:00\n"
         "\n[Install]\nWantedBy=timers.target\n")


def test_a_timer_is_shipped_and_installed_but_never_enabled(world: World):
    """The schedule comes from the repository now, and starting it does not.

    A `.timer` matched no glob here until this change, so what ran on a host was
    whatever had been installed by hand — and no deploy could correct it. The
    file lands; a timer is inert until `systemctl enable`, which is a separate,
    guarded decision (`install_qevik_infra.sh`), because enabling the backup
    timer before the data migration would start deleting migrated dumps.
    """
    sha = commit(world, {"infra/qevik-shipped.timer": TIMER}, message="add a timer")
    proc = run(world, env=env_for(world, sha=sha))
    out = both(proc)
    assert proc.returncode == 0, out

    installed = world.units / "qevik-shipped.timer"
    assert installed.read_text(encoding="utf-8") == TIMER
    assert f"{world.units}/qevik-shipped.timer" in manifest_path(world).read_text(encoding="utf-8")

    enables = [line for line in world.log()
               if line.startswith("systemctl ") and " enable" in line]
    assert not enables, enables


def test_a_rollback_puts_back_a_timer_it_replaced(world: World):
    """Shipping timers without snapshotting them would delete files on rollback."""
    _write(world.units / "qevik-shipped.timer", "[Timer]\nOnCalendar=daily\n")
    sha = commit(world, {"infra/qevik-shipped.timer": TIMER}, message="change the timer")
    # Fail after the units are installed, so the rollback has to undo them.
    _write(world.ctl / "ssh_fail_match", "sha256sum --check")

    proc = run(world, env=env_for(world, sha=sha))
    out = both(proc)
    assert proc.returncode == 1, out
    assert "ROLLED BACK" in out
    assert (world.units / "qevik-shipped.timer").read_text(encoding="utf-8") == \
        "[Timer]\nOnCalendar=daily\n"


def test_units_are_installed_before_anything_is_restarted(world: World):
    """A restart cannot start a unit that is not on the host yet.

    On a host with a previous deploy the old order happened to work, because the
    units were already there from last time. The first deploy to an empty
    qevik-prod-01 failed with `Unit qevik-control.service not found` and rolled
    back — ADR-0010 had parked this as a behaviour change to make later, and a
    first deploy proved it was a correctness bug.

    Asserted on the log rather than on the script text, so it is the order the
    deploy *ran*, not the order the file reads in.
    """
    proc = run(world, env=env_for(world, sha=world.sha))
    assert proc.returncode == 0, both(proc)

    log = world.log()
    installed = next(i for i, line in enumerate(log)
                     if line.startswith("rsync ") and "qevik-worker.service" in line)
    reloaded = next(i for i, line in enumerate(log)
                    if line.startswith("systemctl ") and "daemon-reload" in line)
    restarted = next(i for i, line in enumerate(log)
                     if line.startswith("systemctl ") and " restart" in line)
    assert installed < reloaded < restarted, (
        "units must be on the host, and systemd told about them, before the "
        "deploy restarts anything")
