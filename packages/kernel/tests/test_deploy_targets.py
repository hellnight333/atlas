"""Where a deploy is allowed to go, and with which key.

Two production hosts exist during the migration — the one serving customers and
the one being built — and the deploy scripts used to carry a hard-coded host and
a hard-coded identity. That is fine with one host and dangerous with two: the
new host must never accept the old shared key, and a deploy that picks a default
picks the wrong one exactly on the day it matters.

So there is one registry, two readers (shell and Python), and four rules these
tests hold to:

  1. a registry name resolves to that entry;
  2. a raw `user@host` resolves only with an explicitly named identity;
  3. nothing given is a refusal — there is no default host;
  4. an unknown name is a refusal, never a fallback.

Both readers are exercised against the same fixtures, because the whole point of
one registry is that the shell and the Python agree about it.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CONF = REPO_ROOT / "infra" / "deploy_targets.conf"
RESOLVER = REPO_ROOT / "infra" / "deploy_target.sh"

_spec = importlib.util.spec_from_file_location(
    "qevik_deploy_targets", REPO_ROOT / "infra" / "deploy_targets.py")
assert _spec and _spec.loader
targets = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("qevik_deploy_targets", targets)
_spec.loader.exec_module(targets)


# --- the registry itself ------------------------------------------------------

def test_the_registry_names_both_hosts_of_the_migration() -> None:
    assert targets.names(CONF) == ["old-prod", "new-prod"]


def test_the_registry_has_no_default_entry() -> None:
    """A default is the failure mode this whole change exists to remove.

    With a default, `deploy_control.sh` with no argument goes *somewhere*, and
    during a migration "somewhere" is a coin toss between the host serving
    customers and the host being built.
    """
    text = CONF.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert not stripped.lower().startswith("default"), stripped


def test_each_production_entry_names_its_own_identity() -> None:
    """`-` (defer to ~/.ssh/config) is for ad-hoc rows, not for production.

    The operator's ssh config is not in the repository and cannot be reviewed,
    so a production row that deferred to it would put the choice of key outside
    review — which is where it was before.
    """
    for name, _host, key, _role in targets._rows(CONF):
        assert key != "-", f"{name} defers its identity to ssh_config"
        assert key.endswith(("naml_hetzner", "qevik_prod")), key


def test_the_two_hosts_do_not_share_an_identity() -> None:
    """D-F: the key that reaches the old host must not reach the new one."""
    keys = {name: key for name, _h, key, _r in targets._rows(CONF)}
    assert keys["old-prod"] != keys["new-prod"]
    assert "naml_hetzner" not in keys["new-prod"]


# --- the Python reader --------------------------------------------------------

def test_python_resolves_a_name(tmp_path: Path) -> None:
    key = tmp_path / "id"
    key.write_text("k")
    conf = tmp_path / "targets.conf"
    conf.write_text(f"demo|root@10.0.0.1|{key}|a demo host\n")

    target = targets.resolve("demo", conf=conf)
    assert (target.name, target.host, target.key) == ("demo", "root@10.0.0.1", str(key))
    assert target.ssh_argv("true") == [
        "ssh", "-i", str(key), "-o", "IdentitiesOnly=yes", "root@10.0.0.1", "true"]


def test_python_refuses_with_no_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QEVIK_DEPLOY_TARGET", raising=False)
    with pytest.raises(targets.TargetError, match="no default host"):
        targets.resolve()


def test_python_refuses_an_unknown_name() -> None:
    with pytest.raises(targets.TargetError, match="no fallback"):
        targets.resolve("does-not-exist", conf=CONF)


def test_python_refuses_a_raw_host_without_an_identity(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QEVIK_DEPLOY_KEY", raising=False)
    with pytest.raises(targets.TargetError, match="never guessed"):
        targets.resolve("root@10.0.0.1", conf=CONF)


def test_python_accepts_a_raw_host_with_an_identity(tmp_path: Path) -> None:
    key = tmp_path / "id"
    key.write_text("k")
    target = targets.resolve("root@10.0.0.1", conf=CONF, key=str(key))
    assert (target.name, target.host, target.key) == ("explicit", "root@10.0.0.1", str(key))


def test_python_refuses_an_identity_that_is_not_there(tmp_path: Path) -> None:
    """A missing key is a refusal now, not "Permission denied" ten minutes in."""
    with pytest.raises(targets.TargetError, match="does not exist"):
        targets.resolve("root@10.0.0.1", conf=CONF, key=str(tmp_path / "absent"))


# --- the shell reader, driven for real ----------------------------------------

def _shell(spec: str, *, conf: Path, env_extra: dict[str, str] | None = None
           ) -> subprocess.CompletedProcess:
    script = (
        f'. "{RESOLVER}"\n'
        f'qevik_resolve_target "{spec}"\n'
        'echo "RESOLVED $QEVIK_TARGET_NAME $QEVIK_TARGET_HOST $QEVIK_TARGET_KEY"\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith("QEVIK_")}
    env["QEVIK_TARGETS_FILE"] = str(conf)
    env.update(env_extra or {})
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env=env, timeout=60)


@pytest.fixture
def conf(tmp_path: Path) -> Path:
    key = tmp_path / "id"
    key.write_text("k")
    path = tmp_path / "targets.conf"
    path.write_text(
        "# a fixture registry\n"
        f"demo|root@10.0.0.1|{key}|a demo host\n"
        "aliased|some-ssh-alias|-|defers to ssh_config\n")
    return path


def test_shell_resolves_a_name(conf: Path) -> None:
    done = _shell("demo", conf=conf)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split()[1:3] == ["demo", "root@10.0.0.1"]


def test_shell_refuses_with_no_target(conf: Path) -> None:
    done = _shell("", conf=conf)
    assert done.returncode == 2, done.stdout
    assert "no default host" in done.stderr
    assert "known targets: demo aliased" in done.stderr


def test_shell_refuses_an_unknown_name(conf: Path) -> None:
    done = _shell("prod", conf=conf)
    assert done.returncode == 2, done.stdout
    assert "unknown target 'prod'" in done.stderr
    assert "RESOLVED" not in done.stdout


def test_shell_refuses_a_raw_host_without_an_identity(conf: Path) -> None:
    done = _shell("root@10.0.0.1", conf=conf)
    assert done.returncode == 2, done.stdout
    assert "QEVIK_DEPLOY_KEY is not set" in done.stderr


def test_shell_accepts_a_raw_host_with_an_identity(conf: Path, tmp_path: Path) -> None:
    key = tmp_path / "adhoc"
    key.write_text("k")
    done = _shell("root@10.0.0.1", conf=conf, env_extra={"QEVIK_DEPLOY_KEY": str(key)})
    assert done.returncode == 0, done.stderr
    assert done.stdout.split()[1:4] == ["explicit", "root@10.0.0.1", str(key)]


def test_shell_reuses_a_target_a_parent_script_resolved(conf: Path) -> None:
    """`deploy_console.sh` calls `deploy_public.sh`; both must land on one host."""
    done = _shell("", conf=conf, env_extra={
        "QEVIK_TARGET_RESOLVED": "1",
        "QEVIK_TARGET_NAME": "inherited",
        "QEVIK_TARGET_HOST": "root@10.0.0.9",
        "QEVIK_TARGET_KEY": "/dev/null",
    })
    assert done.returncode == 0, done.stderr
    assert done.stdout.split()[1:3] == ["inherited", "root@10.0.0.9"]


def test_shell_and_python_agree(conf: Path) -> None:
    """One registry is only one registry if both readers say the same thing."""
    shell = _shell("demo", conf=conf).stdout.split()
    python = targets.resolve("demo", conf=conf)
    assert shell[1:4] == [python.name, python.host, python.key]


def test_an_entry_may_defer_to_ssh_config(conf: Path) -> None:
    """`-` means "no -i argument", which is not the same as "no key"."""
    done = _shell("aliased", conf=conf)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split()[1:3] == ["aliased", "some-ssh-alias"]
    python = targets.resolve("aliased", conf=conf)
    assert python.key is None
    assert python.ssh_argv("true") == ["ssh", "some-ssh-alias", "true"]


# --- the guard constant that is deliberately NOT in the registry --------------

def test_cloudflare_origin_constant() -> None:
    """`ORIGIN_IP` is a DNS guard, not a deploy target, and is owned separately.

    It says which address the DNS automation is permitted to publish; the
    registry says where a deploy may go. Coupling them would let a deploy-time
    choice repoint public DNS, so this constant changes exactly once, by hand,
    as a reviewed step of the cutover — and this test is what makes that change
    deliberate instead of accidental.
    """
    from atlas_kernel.infra import cloudflare

    assert cloudflare.ORIGIN_IP == "2.28.62.83", (
        "ORIGIN_IP changed. If this is the cutover, update this test in the same "
        "reviewed commit as the Cloudflare records; if it is not, revert it.")
    source = Path(cloudflare.__file__).read_text(encoding="utf-8")
    # The comment above the constant names the registry to say it is *not* read
    # from it, so the check is for a read, not for the word.
    for coupling in ("import deploy_targets", "from deploy_targets",
                     "deploy_targets.resolve", "deploy_targets.conf\")",
                     "QEVIK_DEPLOY_TARGET"):
        assert coupling not in source, (
            f"the DNS guard must not read the deploy-target registry ({coupling})")


# --- no environment file is read through a shell, anywhere ---------------------

def test_no_infra_script_sources_an_environment_file() -> None:
    """One rule, everywhere (D-S5).

    `set -a; . atlas.env; set +a` is a shell reading a file that contains a
    password. It breaks on `$`, a backtick, a quote or a space, and — worse —
    can alter the value silently. Every reader now goes through systemd's own
    `EnvironmentFile=` parser, which is the parser the units use, so the schema
    step, the backup script and the DevLoop probes all see the same bytes the
    services see.

    No file is exempt, including the comments that explain the rule: a grep the
    reviewer runs must come back empty, and an allow-list is where the next
    instance hides.
    """
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "infra").rglob("*")):
        if not path.is_file() or path.suffix not in {".sh", ".py"}:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if "set -a" in line or ". /opt/qevik/atlas.env" in line:
                offenders.append(f"{rel}:{number}: {line.strip()}")
    assert not offenders, "an environment file is still read by a shell:\n" + "\n".join(offenders)


def test_the_remote_python_builder_hands_over_a_path() -> None:
    """The DevLoop probes read the environment the same way the deploy does."""
    sys.path.insert(0, str(REPO_ROOT / "infra"))
    from devloop.targets import remote_python  # noqa: PLC0415

    command = remote_python("print('hello')")
    assert "--property=EnvironmentFile=/opt/qevik/atlas.env" in command
    assert "--property=User=qevik" in command
    assert "set -a" not in command and ". /opt/qevik/atlas.env" not in command
