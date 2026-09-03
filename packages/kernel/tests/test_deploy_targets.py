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


# --- which unit is installed by what, and enabled by whom ---------------------

INFRA = REPO_ROOT / "infra"
INSTALLER = INFRA / "install_qevik_infra.sh"
DEPLOY = INFRA / "deploy_control.sh"


def test_the_deploy_ships_every_unit_file_including_timers() -> None:
    """A `.timer` used to match nothing, so the schedule on a host was whatever
    had been installed by hand and no deploy could correct it."""
    deploy = DEPLOY.read_text(encoding="utf-8")
    globs = [line for line in deploy.splitlines()
             if "qevik-*.service" in line and "EXPORT" in line]
    assert globs, "the deploy no longer ships units at all"
    for line in globs:
        assert "qevik-*.timer" in line, f"timers are not shipped here: {line.strip()}"


def test_the_snapshot_and_the_rollback_cover_what_the_deploy_installs() -> None:
    """Shipping timers without snapshotting them would make a rollback delete
    files it never saved — the failure this pairing exists to prevent."""
    deploy = DEPLOY.read_text(encoding="utf-8")
    snapshot = next(line for line in deploy.splitlines()
                    if "ROLLBACK_DIR}-units" in line and "cp -a" in line and "for f in" in line)
    rollback = next(line for line in deploy.splitlines()
                    if "rm -f $UNIT_DIR/qevik-" in line)
    for line in (snapshot, rollback):
        assert "qevik-*.service" in line and "qevik-*.timer" in line, line


def test_the_deploy_enables_nothing() -> None:
    """Installing a unit and starting one are different decisions.

    The deploy restarts what is already running; enabling is the installer's
    job, and enabling a *timer* is a separate decision again, gated on data.
    """
    deploy = DEPLOY.read_text(encoding="utf-8")
    for number, line in enumerate(deploy.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "systemctl enable" not in stripped, f"deploy_control.sh:{number}: {stripped}"


def test_the_installer_never_enables_the_data_timers_by_default() -> None:
    """`qevik-backup.timer` and the market scan wait for data and for a key."""
    text = INSTALLER.read_text(encoding="utf-8")
    # The action, not the word: both timers are *named* in the header that
    # explains why they wait, and one is named again in what the run reports.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "systemctl enable" not in stripped:
            continue
        for deferred in ("qevik-backup.timer", "qevik-market-scan.timer"):
            if deferred in stripped:
                assert "$MODE" in text.split(stripped)[0].rsplit("\n\n", 1)[-1] or \
                    "--enable-backup-timer" in text.split(stripped)[0][-2000:], (
                    f"{deferred} is enabled outside the guarded path: {stripped}")


def test_the_backup_timer_is_guarded_by_data_and_by_the_archive() -> None:
    """Two refusals, not two warnings: an empty database, or migrated dumps
    still sitting where `qevik_backup.sh` would prune them."""
    text = INSTALLER.read_text(encoding="utf-8")
    guarded = text.split('if [ "$MODE" = backup-timer ]', 1)[1].split("exit 0", 1)[0]
    assert "database_has_data" in guarded and "die " in guarded
    assert "unarchived_migrated_dumps" in guarded
    enable = guarded.index("systemctl enable --now qevik-backup.timer")
    for guard in ("database_has_data", "unarchived_migrated_dumps"):
        assert guarded.index(guard) < enable, f"{guard} is checked after enabling"


def test_recovery_does_not_carry_a_second_copy_of_the_install_logic() -> None:
    """D-S6: one implementation, so a recovery cannot install a different set."""
    recover = (INFRA / "recover_qevik_server.sh").read_text(encoding="utf-8")
    assert "install_qevik_infra.sh" in recover
    # Reading the slice's effective limits is a report; installing the file is
    # the duplication that mattered.
    for line in recover.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not (stripped.startswith("install ") and "systemd/" in stripped), stripped
        assert "resources.conf" not in stripped, stripped


def test_every_shipped_timer_has_a_service_to_run() -> None:
    """A timer that names nothing is a schedule that silently does nothing."""
    for timer in sorted(INFRA.glob("qevik-*.timer")):
        text = timer.read_text(encoding="utf-8")
        named = [line.split("=", 1)[1].strip() for line in text.splitlines()
                 if line.strip().startswith("Unit=")]
        service = named[0] if named else timer.name.replace(".timer", ".service")
        assert (INFRA / service).is_file(), f"{timer.name} runs {service}, which is not shipped"


# --- the literals do not come back ---------------------------------------------

#: The one place the old production host may be named as an address, and why.
#: `cloudflare.py` holds it as a DNS *guard* — the content an A record must have
#: before the automation will touch it — which is a different question from
#: where a deploy may go, and is owned separately (see the constant's own
#: comment and `test_cloudflare_origin_constant`).
#: This file is exempt from both greps for the obvious reason: it is the grep.
SELF = "packages/kernel/tests/test_deploy_targets.py"

ORIGIN_EXEMPT = {"packages/kernel/atlas_kernel/infra/cloudflare.py", SELF}

#: `naml_hetzner` reaches the *Naml* host, which is a different system that this
#: migration does not touch. It may be named where that host is the subject.
NAML_EXEMPT = {"infra/phase_a_proof.py", SELF}

CODE_SUFFIXES = {".py", ".sh", ".Caddyfile", ".service", ".timer", ".slice", ".conf"}


def _code_files():
    for root in ("infra", "packages/kernel/atlas_kernel", "packages/kernel/tests", "apps"):
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            if path.suffix not in CODE_SUFFIXES:
                continue
            yield path, path.relative_to(REPO_ROOT).as_posix()


def test_the_old_production_ip_is_not_written_into_code() -> None:
    """It lived in seventeen files, and each one was a place a deploy could go
    to the wrong host once a second production host existed.

    The registry names hosts now. This test is the thing that keeps the literal
    from creeping back one convenience at a time.
    """
    offenders = []
    for path, rel in _code_files():
        if rel in ORIGIN_EXEMPT or rel == "infra/deploy_targets.conf":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if "2.28.62.83" in line:
                offenders.append(f"{rel}:{number}: {line.strip()}")
    assert not offenders, (
        "the old production IP is back in code; put the host in "
        "infra/deploy_targets.conf instead:\n" + "\n".join(offenders))


def test_the_shared_operator_key_is_not_written_into_qevik_code() -> None:
    """D-F: the key that reaches the old host must be unreachable from the new
    one's deploy path — including by a script that hard-codes it."""
    offenders = []
    for path, rel in _code_files():
        if rel in NAML_EXEMPT or rel == "infra/deploy_targets.conf":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if "naml_hetzner" in line:
                offenders.append(f"{rel}:{number}: {line.strip()}")
    assert not offenders, (
        "an identity is hard-coded again; name it in infra/deploy_targets.conf "
        "or pass QEVIK_DEPLOY_KEY:\n" + "\n".join(offenders))


def test_only_one_path_puts_application_code_on_a_host() -> None:
    """D-S1: a second, provenance-free kernel copy is not a deployment method.

    `deploy_console.sh` used to rsync the kernel into the directory ADR-0010
    owns, without writing DEPLOYED_SHA or DEPLOYED_MANIFEST and without any of
    deploy_control.sh's refusals — so a host could serve code while reporting a
    provenance it no longer had.
    """
    for name in ("deploy_console.sh", "deploy_public.sh"):
        text = (INFRA / name).read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "packages/kernel/atlas_kernel" not in stripped, f"{name}:{number}: {stripped}"


def test_the_superseded_configurations_are_gone() -> None:
    """D-S3/D-S4: obsolete operational files are removed, not kept "for reference".

    Each carried the old host's address, and a file that is not used but is
    still there is a file someone eventually copies onto a host.
    """
    for name in ("secure_8443.sh", "qevik-control.Caddyfile", "qevik-sites.Caddyfile"):
        assert not (INFRA / name).exists(), f"{name} is back"
