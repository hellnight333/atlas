"""`infra/deploy_control.sh` ships a commit, never the working tree.

Every test drives the real script against a fake host: a temporary git
repository is the source, a directory tree under `tmp_path` is the target, and a
directory of PATH shims stands in for ssh, rsync and the tools the script
reaches for on the far side. The shims are not a mock of the script — the script
runs unmodified, and the real rsync does the real copy.

Nothing here can reach a real host. Every run is given the positional target
`qevik-test@127.0.0.1`, never the production default, and HOME points at an
empty directory so the key the script names does not exist.
`test_without_the_shims_nothing_is_deployed` proves that layer rather than
assuming it.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "infra" / "deploy_control.sh"

# `cp` is here because the fake host's rollback step runs `cp -a` for real, and
# `rsync` because the shim execs the genuine article so `--delete` and `-n -i`
# behave exactly as they would in production.
_NEEDED = {name: shutil.which(name) for name in ("git", "rsync", "bash", "shasum", "cp")}
_MISSING = sorted(name for name, path in _NEEDED.items() if path is None)
pytestmark = pytest.mark.skipif(
    bool(_MISSING),
    reason="deploy_control.sh cannot be exercised without " + ", ".join(_MISSING),
)

TARGET = "qevik-test@127.0.0.1"

# The commit under test. Small real files under each of the three shipped
# prefixes, so the export, the rsyncs, the unit glob and the fingerprint all
# have something to be right or wrong about.
S_FILES = {
    "packages/kernel/atlas_kernel/qevik/app.py": "def from_environment():\n    return 'S'\n",
    "packages/kernel/atlas_kernel/db.py": "def init_db():\n    return 'S'\n",
    "infra/mission_worker.py": "# mission worker, commit S\n",
    "infra/qevik-worker.service": "[Service]\nEnvironment=VARIANT=S\n",
    "apps/control/src/index.html": "<h1>Qevik Control S</h1>\n",
}
# The same paths, different bytes: what a later commit or a branch checkout
# would put in the working tree while a deploy is running.
LATER_FILES = {
    "packages/kernel/atlas_kernel/qevik/app.py": "def from_environment():\n    return 'LATER'\n",
    "infra/mission_worker.py": "# mission worker, LATER\n",
    "infra/qevik-worker.service": "[Service]\nEnvironment=VARIANT=LATER\n",
    "apps/control/src/index.html": "<h1>Qevik Control LATER</h1>\n",
}

FORBIDDEN_IN_REHEARSAL = {"rm", "cp", "mv", "mkdir", "chown", "journalctl"}


# --------------------------------------------------------------------- shims


def _shim(path: Path, ctl: Path, body: str, extra: str = "") -> None:
    """Write one PATH shim. Every shim logs its argv before it does anything."""
    path.write_text(
        f"#!{sys.executable}\n"
        "import os, re, subprocess, sys\n"
        f"CTL = {str(ctl)!r}\n"
        f"{extra}\n"
        "def log(line):\n"
        "    with open(os.path.join(CTL, 'log'), 'a') as fh:\n"
        "        fh.write(line + '\\n')\n"
        "def ctl_read(name, default=''):\n"
        "    try:\n"
        "        return open(os.path.join(CTL, name)).read().strip()\n"
        "    except OSError:\n"
        "        return default\n"
        "argv = sys.argv[1:]\n" + body
    )
    path.chmod(0o755)


SSH_BODY = """
i = 0
while i < len(argv):                       # skip the options, then the target
    if argv[i].startswith('-'):
        i += 2 if argv[i] in ('-o', '-i', '-p', '-l', '-F') else 1
        continue
    break
cmd = ' '.join(argv[i + 1:])
log(cmd)
calls = int(ctl_read('ssh_calls', '0') or 0) + 1
with open(os.path.join(CTL, 'ssh_calls'), 'w') as fh:
    fh.write(str(calls))
if calls <= int(ctl_read('ssh_drop', '0') or 0):
    sys.exit(255)                          # ssh's own code for a dropped link
match = ctl_read('ssh_fail_match')
if match and match in cmd:
    sys.exit(1)                            # the remote command's own answer
sys.exit(subprocess.run(['bash', '-c', cmd]).returncode)
"""

RSYNC_BODY = """
log('rsync ' + ' '.join(argv))
kept, i = [], 0
while i < len(argv):
    if argv[i] == '-e':
        i += 2
        continue
    if argv[i].startswith('--timeout='):
        i += 1
        continue
    kept.append(re.sub(r'^[^\\s:/]+@[^\\s:/]+:', '', argv[i]))
    i += 1
hook = os.path.join(CTL, 'hook')
if os.access(hook, os.X_OK):
    subprocess.run([hook])
os.execv(REAL_RSYNC, [REAL_RSYNC] + kept)
"""

CURL_BODY = """
log('curl ' + ' '.join(argv))
fmt = ''
for i, a in enumerate(argv):
    if a == '-w' and i + 1 < len(argv):
        fmt = argv[i + 1]
code = ctl_read('health_code', '200') or '200'
sys.stdout.write((fmt or '%{http_code}').replace('%{http_code}', code).replace('\\\\n', '\\n'))
"""

SUDO_BODY = """
joined = ' '.join(argv)
log('sudo ' + joined)
if 'DISTINCT' in joined:
    sys.stdout.write(ctl_read('worker_version') + '\\n')
elif 'count(' in joined:
    sys.stdout.write('1\\n')
"""

SHA256SUM_BODY = """
log('sha256sum ' + ' '.join(argv))
os.execvp('shasum', ['shasum', '-a', '256'] + argv)
"""


def _write_shims(shims: Path, ctl: Path) -> None:
    shims.mkdir(parents=True)
    _shim(shims / "ssh", ctl, SSH_BODY)
    _shim(shims / "rsync", ctl, RSYNC_BODY, extra=f"REAL_RSYNC = {_NEEDED['rsync']!r}")
    _shim(shims / "curl", ctl, CURL_BODY)
    _shim(shims / "sudo", ctl, SUDO_BODY)
    _shim(shims / "sha256sum", ctl, SHA256SUM_BODY)
    # Every sleep in the script is a pure wait, so returning at once changes
    # nothing about what the script does — only how long the suite takes.
    for name in ("sleep", "systemctl", "chown", "journalctl"):
        _shim(shims / name, ctl, f"log({name!r} + ' ' + ' '.join(argv))\n")


# ---------------------------------------------------------------- the world


class World:
    def __init__(self, tmp: Path, repo: Path, fake: Path, shims: Path, sha: str,
                 other_sha: str, env: dict) -> None:
        self.tmp = tmp
        self.repo = repo
        self.fake = fake
        self.host = fake / "host"
        self.ctl = fake / "ctl"
        self.shims = shims
        self.sha = sha
        self.other_sha = other_sha
        self.env = env


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True)
    return done.stdout.strip()


def _write_all(root: Path, files: dict) -> None:
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)


def build_world(tmp_path: Path, monkeypatch, extra: dict | None = None) -> World:
    """A temp repository holding commit S, a fake host, and the PATH shims."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "deploy-test@example.invalid")
    _git(repo, "config", "user.name", "deploy test")
    _git(repo, "config", "commit.gpgsign", "false")

    _write_all(repo, dict(S_FILES, **(extra or {})))
    # Copied, never symlinked: a symlink is an untracked path, and the export
    # verification counts every regular file it extracts.
    (repo / "infra").mkdir(exist_ok=True)
    shutil.copyfile(SCRIPT, repo / "infra" / "deploy_control.sh")
    (repo / "infra" / "deploy_control.sh").chmod(0o755)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "S")
    sha = _git(repo, "rev-parse", "HEAD")

    # A branch that never landed: the source of the non-ancestor refusal, and
    # what the mid-deploy hook checks out.
    _git(repo, "checkout", "-q", "-b", "other")
    _write_all(repo, LATER_FILES)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "unmerged")
    other_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")

    fake = tmp_path / "fake"
    ctl = fake / "ctl"
    ctl.mkdir(parents=True)
    host = fake / "host"
    app = host / "app"
    (app / "packages" / "kernel" / "atlas_kernel" / "qevik").mkdir(parents=True)
    (app / "packages" / "kernel" / "atlas_kernel" / "qevik" / "app.py").write_text("# stale\n")
    (app / "packages" / "kernel" / "atlas_kernel" / "stale.py").write_text("# stale\n")
    (app / "infra").mkdir(parents=True)
    (app / "infra" / "mission_worker.py").write_text("# stale worker\n")
    (app / ".venv" / "bin").mkdir(parents=True)
    (app / ".venv" / "bin" / "python").write_text("#!/bin/bash\necho 'schema applied'\n")
    (app / ".venv" / "bin" / "python").chmod(0o755)
    (host / "console").mkdir()
    (host / "console" / "index.html").write_text("<h1>stale</h1>\n")
    (host / "units").mkdir()
    (host / "units" / "qevik-worker.service").write_text("[Service]\n# stale\n")
    (host / "atlas.env").write_text("")

    # The workers must be able to report the fingerprint of S's worker, or the
    # deploy would roll back before any of the interesting assertions.
    (ctl / "worker_version").write_text(fingerprint_of(S_FILES["infra/mission_worker.py"]))

    shims = tmp_path / "shims"
    _write_shims(shims, ctl)

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    env = {k: v for k, v in os.environ.items() if not k.startswith("QEVIK_")}
    env["PATH"] = os.pathsep.join([str(shims), os.environ["PATH"]])
    env["HOME"] = str(home)
    env.update({
        "QEVIK_TEST_HOST": "1",
        "QEVIK_REMOTE_APP": str(app),
        "QEVIK_CONSOLE_DIR": str(host / "console"),
        "QEVIK_UNIT_DIR": str(host / "units"),
        "QEVIK_ENV_FILE": str(host / "atlas.env"),
        "QEVIK_HEALTH_URL": "http://127.0.0.1:8081/api/health",
        "QEVIK_ROLLBACK_DIR": str(host / "rollback"),
    })
    return World(tmp_path, repo, fake, shims, sha, other_sha, env)


def fingerprint_of(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()[:12]


def run(world: World, *args: str, overrides: dict | None = None, timeout: int = 300):
    env = dict(world.env)
    env["QEVIK_DEPLOY_SHA"] = world.sha
    for key, value in (overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        ["bash", str(world.repo / "infra" / "deploy_control.sh"), *args, TARGET],
        env=env, cwd=str(world.tmp), capture_output=True, text=True, timeout=timeout)


def snapshot(fake: Path) -> dict:
    """Every file on the fake host by digest, plus its directory list."""
    host = Path(fake) / "host"
    files, dirs = {}, []
    for root, dirnames, filenames in os.walk(host):
        for name in dirnames:
            dirs.append(str((Path(root) / name).relative_to(host)))
        for name in filenames:
            path = Path(root) / name
            rel = str(path.relative_to(host))
            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"files": files, "dirs": sorted(dirs)}


def log_lines(world: World) -> list:
    path = world.ctl / "log"
    return path.read_text().splitlines() if path.exists() else []


# ------------------------------------------------------- the payload is the commit


def test_the_payload_is_the_commit_not_the_tree(tmp_path, monkeypatch):
    """A later commit on main is in the tree; none of it reaches the host."""
    world = build_world(tmp_path, monkeypatch)
    _write_all(world.repo, LATER_FILES)
    _git(world.repo, "add", "-A")
    _git(world.repo, "commit", "-qm", "later")
    assert _git(world.repo, "rev-parse", "HEAD") != world.sha
    assert _git(world.repo, "status", "--porcelain") == ""

    done = run(world)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "deployed" in done.stdout

    host = world.host
    kernel = host / "app" / "packages" / "kernel" / "atlas_kernel" / "qevik" / "app.py"
    assert kernel.read_text() == S_FILES["packages/kernel/atlas_kernel/qevik/app.py"]
    assert (host / "console" / "index.html").read_text() == S_FILES["apps/control/src/index.html"]
    assert (host / "app" / "infra" / "mission_worker.py").read_text() == (
        S_FILES["infra/mission_worker.py"])
    assert (host / "units" / "qevik-worker.service").read_text() == (
        S_FILES["infra/qevik-worker.service"])

    printed = re.search(r"expecting fingerprint ([0-9a-f]{12})", done.stdout)
    assert printed and printed.group(1) == fingerprint_of(S_FILES["infra/mission_worker.py"])


def test_a_checkout_during_the_deploy_cannot_alter_the_payload(tmp_path, monkeypatch):
    """The tree moves to another branch on the first copy; the rest still ships S."""
    world = build_world(tmp_path, monkeypatch)
    hook = world.ctl / "hook"
    hook.write_text(
        "#!/bin/bash\n"
        f'if [ -f "{world.ctl}/hook_ran" ]; then exit 0; fi\n'
        f'touch "{world.ctl}/hook_ran"\n'
        f'git -C "{world.repo}" checkout -q other\n')
    hook.chmod(0o755)

    done = run(world)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (world.ctl / "hook_ran").exists(), "the hook never ran; the test proves nothing"
    assert _git(world.repo, "rev-parse", "--abbrev-ref", "HEAD") == "other"

    host = world.host
    kernel = host / "app" / "packages" / "kernel" / "atlas_kernel" / "qevik" / "app.py"
    assert kernel.read_text() == S_FILES["packages/kernel/atlas_kernel/qevik/app.py"]
    assert (host / "console" / "index.html").read_text() == S_FILES["apps/control/src/index.html"]
    assert (host / "app" / "infra" / "mission_worker.py").read_text() == (
        S_FILES["infra/mission_worker.py"])
    assert (host / "units" / "qevik-worker.service").read_text() == (
        S_FILES["infra/qevik-worker.service"])
    printed = re.search(r"expecting fingerprint ([0-9a-f]{12})", done.stdout)
    assert printed and printed.group(1) == fingerprint_of(S_FILES["infra/mission_worker.py"])


# ------------------------------------------------------------------- refusals


def test_the_sha_contract_refuses_before_touching_the_host(tmp_path, monkeypatch):
    world = build_world(tmp_path, monkeypatch)
    before = snapshot(world.fake)

    unset = run(world, overrides={"QEVIK_DEPLOY_SHA": None})
    assert unset.returncode == 2, unset.stdout + unset.stderr

    absent = run(world, overrides={"QEVIK_DEPLOY_SHA": "0" * 40})
    assert absent.returncode == 2, absent.stdout + absent.stderr

    unlanded = run(world, overrides={"QEVIK_DEPLOY_SHA": world.other_sha})
    assert unlanded.returncode == 2, unlanded.stdout + unlanded.stderr
    assert "not landed on main" in unlanded.stderr

    assert log_lines(world) == [], "a refusal reached the host"
    assert snapshot(world.fake) == before


def test_an_export_that_does_not_match_the_commit_is_refused(tmp_path, monkeypatch):
    """`export-ignore` drops a file from `git archive` that `ls-tree` still lists."""
    world = build_world(
        tmp_path, monkeypatch,
        extra={".gitattributes": "infra/qevik-worker.service export-ignore\n"})
    before = snapshot(world.fake)

    done = run(world)
    assert done.returncode == 3, done.stdout + done.stderr
    assert "does not match" in done.stderr
    assert log_lines(world) == [], "the host was contacted with an unverified export"
    assert snapshot(world.fake) == before


def test_bad_arguments_are_refused(tmp_path, monkeypatch):
    world = build_world(tmp_path, monkeypatch)
    assert run(world, "--frobnicate").returncode == 2
    assert run(world, "an-extra-positional").returncode == 2


def test_a_partially_set_seam_is_refused(tmp_path, monkeypatch):
    world = build_world(tmp_path, monkeypatch)

    unguarded = run(world, overrides={"QEVIK_TEST_HOST": None})
    assert unguarded.returncode == 2, unguarded.stdout + unguarded.stderr
    assert "seams are partially set" in unguarded.stderr

    incomplete = run(world, overrides={"QEVIK_ENV_FILE": None})
    assert incomplete.returncode == 2, incomplete.stdout + incomplete.stderr
    assert "seams are partially set" in incomplete.stderr

    assert log_lines(world) == []


# ------------------------------------------------------------------- rehearse


def test_rehearse_writes_nothing(tmp_path, monkeypatch):
    world = build_world(tmp_path, monkeypatch)
    before = snapshot(world.fake)

    done = run(world, "--rehearse")
    assert done.returncode == 0, done.stdout + done.stderr
    assert snapshot(world.fake) == before, "--rehearse changed the host"

    assert any(line.startswith(f"REHEARSED sha={world.sha}") for line in done.stdout.splitlines())
    assert any(line.startswith("targets: app=") for line in done.stdout.splitlines())

    lines = log_lines(world)
    transfers = [line for line in lines if line.startswith("rsync ")]
    assert transfers, "no transfer was planned"
    for line in transfers:
        assert "-n" in line.split(), line

    for line in lines:
        assert ".venv/bin/python" not in line, line
        tokens = [t for t in re.split(r"[\s;]+|&&|\|\|", line) if t]
        assert not (FORBIDDEN_IN_REHEARSAL & set(tokens)), line
        for index, token in enumerate(tokens):
            if token == "systemctl":
                assert tokens[index + 1:index + 2] == ["is-active"], line


def test_a_real_run_does_change_the_host(tmp_path, monkeypatch):
    """The negative control for the rehearsal: the check above can fail."""
    world = build_world(tmp_path, monkeypatch)
    before = snapshot(world.fake)

    done = run(world)
    assert done.returncode == 0, done.stdout + done.stderr
    assert snapshot(world.fake) != before
    assert any("systemctl restart" in line for line in log_lines(world))


# ------------------------------------------------------------- ssh_ semantics


def test_only_a_dropped_link_is_retried(tmp_path, monkeypatch):
    """Exit 255 is retried; any other status is the remote command's answer."""
    world = build_world(tmp_path, monkeypatch)
    (world.ctl / "ssh_drop").write_text("2")

    done = run(world)
    assert done.returncode == 0, done.stdout + done.stderr
    # `ssh_ true` is the first thing the script sends: two drops, then the answer.
    assert [line for line in log_lines(world) if line == "true"] == ["true"] * 3

    other = build_world(tmp_path / "second", monkeypatch)
    (other.ctl / "ssh_fail_match").write_text("init_db")
    failed = run(other)
    assert failed.returncode == 1, failed.stdout + failed.stderr
    assert "schema could not be applied" in failed.stdout
    assert sum(1 for line in log_lines(other) if "init_db" in line) == 1, (
        "a remote command that answered non-zero was retried")


# ---------------------------------------------------------- the shims themselves


def test_without_the_shims_nothing_is_deployed(tmp_path, monkeypatch):
    """The layer the other tests stand on: no shims, no host, no deploy.

    Bounded by a timeout rather than run to completion: with the real ssh in
    front of a host that is not there, `ssh_` spends its whole 165-second retry
    budget before giving up, and this test only needs to see that it never gets
    past the access check.
    """
    world = build_world(tmp_path, monkeypatch)
    before = snapshot(world.fake)
    env = dict(world.env)
    env["QEVIK_DEPLOY_SHA"] = world.sha
    env["PATH"] = os.pathsep.join(
        p for p in world.env["PATH"].split(os.pathsep) if p != str(world.shims))

    argv = ["bash", str(world.repo / "infra" / "deploy_control.sh"), TARGET]
    try:
        done = subprocess.run(argv, env=env, cwd=str(world.tmp), capture_output=True,
                              text=True, timeout=12, start_new_session=True)
        assert done.returncode != 0
        assert "deployed" not in done.stdout
    except subprocess.TimeoutExpired as expired:
        partial = expired.output or b""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        assert "deployed" not in partial

    assert snapshot(world.fake) == before
    assert not (world.ctl / "log").exists()
