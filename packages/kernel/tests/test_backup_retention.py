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

    prune = ('KEEP=14\nDIR="%s"\n'
             'ls -1t "${DIR}"/qevik-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) '
             '| while read -r old; do rm -f "$old"; done\n' % dumps)
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
