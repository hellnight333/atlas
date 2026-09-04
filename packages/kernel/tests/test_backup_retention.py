"""Which dumps retention owns, and which dump the daily proof reads back.

Eleven verified production dumps were migrated from the old host onto the new
one, into the directory `qevik_backup.sh` prunes to the fourteen newest. Four
backups on the new host and it would have begun deleting production history — a
silent loss with no error, discovered whenever someone next went looking for an
August dump.

Two rules, both exercised here against the real scripts:

  * retention owns the dumps **this host produced** — the top level of the
    backup directory. `archive/` is history it did not write, and only the owner
    removes it (Phase 11);
  * the daily restore proof reads back a **current** dump when there is one and
    falls back to the archive only while this host has produced none — with
    `--strict-current` turning a missing current dump into a failure once the
    database holds data, rather than a proof quietly about a 2026 file.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKUP = REPO_ROOT / "infra" / "qevik_backup.sh"
OFFSITE = REPO_ROOT / "infra" / "qevik_offsite.sh"


def _dump(path: Path, name: str, *, age: int = 0) -> Path:
    """A file shaped like a dump, old enough to be distinguishable."""
    path.mkdir(parents=True, exist_ok=True)
    target = path / name
    target.write_bytes(name.encode())
    if age:
        stamp = 1_700_000_000 - age
        os.utime(target, (stamp, stamp))
    return target


def _source_function(script: Path, call: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run one function out of a script, without running the script.

    Both scripts refuse to do anything without an environment (a database URL, a
    restic repository), which is correct and makes them awkward to exercise. The
    functions under test are pure enough to lift out: this extracts the file up
    to its first executable statement and calls in.
    """
    text = script.read_text(encoding="utf-8")
    # Everything up to the case statement is definitions...
    head = text.split('case "${1:-run}"', 1)[0]
    head = head.split("# ---- run", 1)[0]
    # ...except the guards that make the *script* refuse to run anywhere but the
    # host: root, a repository, a password, restic on PATH. They are correct and
    # are not what these tests are about; dropping them is the smallest way to
    # exercise the real functions rather than a copy of them.
    guards = ("id -u", "RESTIC_REPOSITORY:-", "RESTIC_PASSWORD:-", "command -v restic")
    head = "\n".join(line for line in head.splitlines()
                     if not any(guard in line for guard in guards))
    return subprocess.run(["bash", "-c", head + "\n" + call],
                          capture_output=True, text=True, env=env, timeout=60)


# --- retention -----------------------------------------------------------------

def test_retention_deletes_only_dumps_this_host_produced(tmp_path: Path) -> None:
    """Twenty of ours and eleven of the old host's: eleven survive untouched."""
    dumps = tmp_path / "backups"
    archive = dumps / "archive" / "old-host"
    for i in range(20):
        _dump(dumps, f"qevik-2026090{i % 10}T0{i % 10}0000Z-{i}.dump", age=i * 60)
    migrated = [_dump(archive, f"qevik-202608{17 + i:02d}T131008Z.dump", age=100_000 + i)
                for i in range(11)]

    prune = (f'KEEP=14\nDIR="{dumps}"\n'
             'ls -1t "${DIR}"/qevik-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) '
             '| while read -r old; do rm -f "$old"; done\n')
    done = subprocess.run(["bash", "-c", prune], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr

    assert len(list(dumps.glob("qevik-*.dump"))) == 14
    for path in migrated:
        assert path.is_file(), f"retention deleted migrated history: {path.name}"


def test_the_pruner_in_the_script_never_descends_into_the_archive() -> None:
    """The rule is structural — a glob that does not recurse — not a promise."""
    text = BACKUP.read_text(encoding="utf-8")
    prune_lines = [line for line in text.splitlines()
                   if "tail -n +$((KEEP + 1))" in line]
    assert len(prune_lines) == 1, prune_lines
    line = prune_lines[0]
    assert '"${DIR}"/qevik-*.dump' in line, line
    # `ls` on a glob does not descend; `find` and `**` would.
    assert "find " not in line, line
    assert "**" not in line, line


# --- which dump the daily proof reads back --------------------------------------

@pytest.fixture
def offsite_env(tmp_path: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("QEVIK_")}
    env["QEVIK_BACKUP_DIR"] = str(tmp_path / "backups")
    env["QEVIK_OFFSITE_STATE"] = str(tmp_path / "state")
    env["RESTIC_REPOSITORY"] = "sftp:unused:unused"
    env["RESTIC_PASSWORD"] = "unused-by-these-tests"
    # The script's cache directory defaults to /var/cache/restic, which a test
    # neither may nor should create.
    env["RESTIC_CACHE_DIR"] = str(tmp_path / "cache")
    return env


def test_a_current_dump_is_preferred_over_the_archive(tmp_path: Path, offsite_env) -> None:
    dumps = tmp_path / "backups"
    _dump(dumps / "archive" / "old-host", "qevik-20260817T131008Z.dump", age=100_000)
    current = _dump(dumps, "qevik-20260910T033000Z.dump")

    done = _source_function(OFFSITE, "select_dump", offsite_env)
    assert done.returncode == 0, done.stderr
    kind, _, path = done.stdout.strip().partition("\t")
    assert kind == "current"
    assert path == str(current)


def test_the_archive_answers_only_while_this_host_has_produced_nothing(
        tmp_path: Path, offsite_env) -> None:
    """Between the migration and the first backup here, the proof keeps running.

    Without this the daily run would report "skipped" every night in that window
    and the off-host copy would go unverified for as long as it lasted.
    """
    dumps = tmp_path / "backups"
    archived = _dump(dumps / "archive" / "old-host", "qevik-20260903T033126Z.dump")
    _dump(dumps / "archive" / "old-host", "qevik-20260817T131008Z.dump", age=100_000)

    done = _source_function(OFFSITE, "select_dump", offsite_env)
    assert done.returncode == 0, done.stderr
    kind, _, path = done.stdout.strip().partition("\t")
    assert kind == "archive"
    assert path == str(archived), "the newest archived dump is the one to prove"


def test_nothing_at_all_is_reported_as_nothing(tmp_path: Path, offsite_env) -> None:
    (tmp_path / "backups").mkdir()
    done = _source_function(OFFSITE, "select_dump", offsite_env)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().split("\t")[0] == "none"


def test_strict_current_turns_a_missing_current_dump_into_a_failure() -> None:
    """After the data migration, an archived dump is not an answer.

    A proof that keeps passing because it found a dump from before the migration
    is exactly the kind of green that hides a stopped backup.
    """
    text = OFFSITE.read_text(encoding="utf-8")
    verify = text.split("restore_verify()", 1)[1].split("\n}", 1)[0]
    assert 'STRICT_CURRENT:-0' in verify
    assert verify.index('kind" = archive') < verify.index("restic restore"), (
        "the strict check must come before the restore, not after it")
    assert "--strict-current" in text, "the flag that sets it is not accepted"


def test_the_restore_helper_returns_both_kinds() -> None:
    """`--restore-dump` is what a person runs in a disaster; it must not hide
    the archived history under a glob that only matches the top level."""
    text = OFFSITE.read_text(encoding="utf-8")
    restore = text.split("--restore-dump)", 1)[1].split("exit 0", 1)[0]
    assert '--include "${DUMPS}"' in restore
    assert "archived history" in restore


# --- the guard that decides when backups may begin ------------------------------

INSTALLER = REPO_ROOT / "infra" / "install_qevik_infra.sh"


def _guard(dumps: Path, *, archive: bool) -> subprocess.CompletedProcess:
    """Run the installer's archive guard against a fixture directory."""
    text = INSTALLER.read_text(encoding="utf-8")
    head = text.split('if [ "$MODE" = backup-timer ]', 1)[0]
    head = head.replace('case "${1:-}" in', 'case "" in')
    env = {k: v for k, v in os.environ.items() if not k.startswith("QEVIK_")}
    env["QEVIK_BACKUP_DIR"] = str(dumps)
    env["QEVIK_BACKUP_ARCHIVE"] = str(dumps / "archive")
    call = ('if unarchived_migrated_dumps; then echo UNARCHIVED; else echo CLEAR; fi')
    return subprocess.run(["bash", "-c", head + "\n" + call],
                          capture_output=True, text=True, env=env, timeout=60)


def test_the_guard_refuses_while_migrated_dumps_sit_in_the_retention_path(
        tmp_path: Path) -> None:
    dumps = tmp_path / "backups"
    _dump(dumps, "qevik-20260903T033126Z.dump")
    done = _guard(dumps, archive=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "UNARCHIVED"


def test_the_guard_opens_once_the_dumps_are_archived(tmp_path: Path) -> None:
    dumps = tmp_path / "backups"
    _dump(dumps / "archive" / "old-host", "qevik-20260903T033126Z.dump")
    _dump(dumps, "qevik-20260910T033000Z.dump")  # one this host produced
    done = _guard(dumps, archive=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "CLEAR"


def test_an_empty_backup_directory_is_not_a_reason_to_refuse(tmp_path: Path) -> None:
    dumps = tmp_path / "backups"
    dumps.mkdir()
    done = _guard(dumps, archive=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "CLEAR"


def test_the_guard_does_not_depend_on_timestamps() -> None:
    """A reboot after the data migration makes every dump look migrated, and a
    host that cannot report its boot time would answer 'nothing to worry about'
    — a guard that fails open. The rule is structural instead."""
    guard = INSTALLER.read_text(encoding="utf-8").split(
        "unarchived_migrated_dumps() {", 1)[1].split("\n}", 1)[0]
    for timeish in ("uptime", "newermt", "date -d", "-mtime"):
        assert timeish not in guard, guard


# --- the env-name manifest, and the backup it stopped ---------------------------

def _env_names(base: Path) -> subprocess.CompletedProcess:
    """Run the offsite script's `env_names` against a directory of env files.

    The function is sourced out of the real script rather than restated here, so
    this exercises the shipped code and not a copy of it that agrees with the
    test.
    """
    state = base / "state"
    state.mkdir(exist_ok=True)
    script = (
        f'set -euo pipefail\n'
        f'BASE={base!s}\n'
        f'STATE_DIR={state!s}\n'
        f'FAILED="$STATE_DIR/FAILED"\n'
        # Just the function, lifted from the file by its own name.
        + OFFSITE.read_text(encoding="utf-8").split("env_names() {", 1)[1]
          .split("\n}\n", 1)[0].join(("env_names() {", "\n}\n"))
        + "\nenv_names\ncat \"$STATE_DIR/env-names.txt\"\n"
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def test_an_env_file_of_only_comments_does_not_stop_the_backup(tmp_path: Path) -> None:
    """The failure that stopped every off-host backup on the new host.

    `grep -v '^\\s*#' file | grep = | ...` under `set -euo pipefail`: a file
    with nothing but comments leaves grep with no match, grep exits 1, pipefail
    propagates it, and `set -e` ends the script — before restic runs, before
    anything is logged, with exit status 1 and not one line of output.

    A comments-only env file is not exotic. Every scaffold starts as one,
    waiting for its values, and creating one is how this broke.
    """
    (tmp_path / "scaffold.env").write_text(
        "# QEVIK_SOMETHING=\n# still waiting for its value\n", encoding="utf-8")
    (tmp_path / "real.env").write_text("A_NAME=a-value\n", encoding="utf-8")

    result = _env_names(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "A_NAME" in result.stdout
    assert "scaffold.env" in result.stdout, "the file is still listed, just empty"


def test_the_manifest_carries_names_and_never_values(tmp_path: Path) -> None:
    """The reason this manifest exists at all is that a rebuild needs the names.
    A value in it would put a secret in the off-host repository."""
    (tmp_path / "real.env").write_text(
        "A_NAME=super-secret-value\nB_NAME=another-one\n", encoding="utf-8")

    result = _env_names(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "A_NAME" in result.stdout and "B_NAME" in result.stdout
    assert "super-secret-value" not in result.stdout
    assert "another-one" not in result.stdout


def test_the_backup_says_why_it_died_even_when_it_dies_unexpectedly() -> None:
    """A `set -e` abort has no message, and the successful runs are the verbose
    ones. That is backwards: the log is read when something went wrong."""
    text = OFFSITE.read_text(encoding="utf-8")
    assert "trap 'on_unexpected_exit" in text, (
        "an unchosen exit leaves no trace, so a backup can stop for days while "
        "the journal shows only 'status=1/FAILURE'")
    assert "$LINENO" in text and "$BASH_COMMAND" in text, (
        "a failure report that names neither the line nor the command is not "
        "one somebody can act on")


def test_the_unit_sends_the_failure_stream_to_the_journal() -> None:
    """`die` and the trap write to stderr. If the unit does not route it, the
    only messages that explain a failure are the ones nobody can read."""
    unit = (REPO_ROOT / "infra" / "qevik-offsite.service").read_text(encoding="utf-8")
    assert "StandardError=journal" in unit
    assert "StandardOutput=journal" in unit


# --- and somebody actually looks at it ------------------------------------------

def test_a_failed_backup_reaches_the_operators_screen(tmp_path: Path) -> None:
    """The half of this that was missing.

    `qevik-backup-failed@.service` says it exists because "a backup that fails
    silently for five days is the failure this unit exists to make loud". It
    wrote its marker faithfully through a day of broken backups. Nothing read
    the marker, so the loudness reached nobody.
    """
    from atlas_kernel.qevik.app import backup_health

    (tmp_path / "FAILED").write_text(
        "2026-09-04T04:15:15Z unit=qevik-offsite.service result=exit-code\n",
        encoding="utf-8")
    report = backup_health(tmp_path)
    assert report["healthy"] is False
    assert report["state"] == "FAILED"
    assert "qevik-offsite" in report["detail"]


def test_never_run_is_not_drawn_as_failed(tmp_path: Path) -> None:
    """Three states, not two. A host that has never run a backup has not failed
    one, and painting it red invents an incident somebody then repeats aloud."""
    from atlas_kernel.qevik.app import backup_health

    report = backup_health(tmp_path)
    assert report["healthy"] is None
    assert report["state"] == "NOT_VERIFIED"
    assert "not the same as one having failed" in report["detail"]


def test_a_good_run_reports_the_restore_not_only_the_copy(tmp_path: Path) -> None:
    """"Copy succeeded" is never evidence; a restore is — the offsite script's
    own words. So the health payload carries the restore, not just the run."""
    import json

    from atlas_kernel.qevik.app import backup_health

    (tmp_path / "status.json").write_text(json.dumps({
        "unit": "qevik-offsite", "last_run_utc": "2026-09-04T08:08:54Z",
        "result": "ok", "snapshot": "78ca7d70",
        "restore_verified": "qevik-20260903T033126Z.dump sha256 match (current)",
    }), encoding="utf-8")

    report = backup_health(tmp_path)
    assert report["healthy"] is True
    assert report["snapshot"] == "78ca7d70"
    assert "sha256 match" in report["restore_verified"]


def test_the_marker_outranks_a_stale_success(tmp_path: Path) -> None:
    """A run that failed after a run that worked leaves both files. The marker
    is the verdict; a successful run is what removes it."""
    import json

    from atlas_kernel.qevik.app import backup_health

    (tmp_path / "status.json").write_text(
        json.dumps({"result": "ok", "last_run_utc": "2026-09-03T16:26:45Z"}),
        encoding="utf-8")
    (tmp_path / "FAILED").write_text("2026-09-04T04:15:15Z unit=qevik-offsite\n",
                                     encoding="utf-8")

    assert backup_health(tmp_path)["healthy"] is False
