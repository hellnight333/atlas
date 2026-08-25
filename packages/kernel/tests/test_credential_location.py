"""One credential boundary, and the test that keeps it one.

The control plane wrote `<QEVIK_STATE>/vault.json`; the worker read
`<vault_root>/credentials.json`. Two files, so the Credential Centre could show
a credential CONNECTED that the worker could not see, and the worker's refusal
read as "no credential configured" to an operator looking at a screen saying
otherwise.

The first attempt at a fix accepted either shape and fell back to whichever
existed. That is worse: two paths that usually agree diverge the moment one is
written, and nothing reports it.

So the real guard is not that the paths currently match — it is that **nothing
outside `credentials/location.py` is allowed to name a credential file at all**.
Two of the tests below read the source to enforce that, because a matching pair
of literals is exactly what the original bug looked like on the day it was
written.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from atlas_kernel.credentials.location import (
    DEFAULT_STATE,
    RECORDS_FILE,
    VAULT_FILE,
    CredentialPaths,
    describe,
    paths_for,
)

ROOT = Path(__file__).resolve().parents[3]

#: Everything that opens a credential store. Adding a process here is cheaper
#: than discovering it diverged.
CALLERS = (
    ROOT / "packages" / "kernel" / "atlas_kernel" / "qevik" / "app.py",
    ROOT / "infra" / "mission_worker.py",
)


# ============================================ one answer

def test_both_files_come_from_one_state_directory() -> None:
    where = paths_for("/srv/example")
    assert where.vault == Path("/srv/example") / VAULT_FILE
    assert where.records == Path("/srv/example") / RECORDS_FILE
    assert where.vault.parent == where.records.parent, (
        "the two halves must live together; resolving them separately is how "
        "one process ends up with the secret and no record")


def test_the_two_halves_are_returned_together() -> None:
    """A caller that resolved the vault in one place and the records in another
    is the shape of the bug this replaced."""
    where = paths_for("/srv/example")
    assert isinstance(where, CredentialPaths)
    assert {"state", "vault", "records"} <= set(where.summary())


def test_passing_a_file_is_refused_rather_than_interpreted() -> None:
    """A function that accepted both a file and a directory would be the
    fallback that silently diverges."""
    with pytest.raises(ValueError, match="state \\*directory\\*"):
        paths_for("/srv/example/vault.json")


def test_the_state_directory_comes_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("QEVIK_STATE", "/var/lib/example")
    assert paths_for().state == Path("/var/lib/example")


def test_without_a_state_directory_it_is_under_the_users_home(monkeypatch
                                                              ) -> None:
    """Not the repository: a checkout can be deleted without destroying the keys
    in it, and `git status` never lists them."""
    monkeypatch.delenv("QEVIK_STATE", raising=False)
    assert paths_for().state == DEFAULT_STATE
    assert ROOT not in DEFAULT_STATE.parents


# ============================================ nobody else may name these files

@pytest.mark.parametrize("caller", CALLERS, ids=lambda p: p.name)
def test_no_caller_constructs_a_credential_path_itself(caller: Path) -> None:
    """Read from the source. A matching pair of literals in two files is what
    the original bug looked like on the day it was written — they agreed then
    too."""
    assert caller.is_file(), caller
    source = caller.read_text(encoding="utf-8")
    for named in (VAULT_FILE, RECORDS_FILE, "credentials.json"):
        for line in source.splitlines():
            stripped = line.strip()
            if named not in stripped:
                continue
            # A comment explaining the history is fine; a string literal that
            # something opens is not.
            assert stripped.startswith("#"), (
                f"{caller.name} names {named!r} itself:\n    {stripped}\n"
                "Credential file names belong to credentials/location.py.")


@pytest.mark.parametrize("caller", CALLERS, ids=lambda p: p.name)
def test_every_caller_asks_the_one_module(caller: Path) -> None:
    """The other direction. If a caller stopped asking, the test above would
    still pass — it would simply have no literals, and no credentials either."""
    tree = ast.parse(caller.read_text(encoding="utf-8"))
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "paths_for" in called, (
        f"{caller.name} opens a credential store without asking "
        "credentials/location.py where it is")


def test_the_environment_variable_that_named_one_file_is_gone() -> None:
    """`QEVIK_VAULT` named the vault alone, so the records file was resolved
    somewhere else — which is precisely how the two ended up in different
    directories."""
    for caller in CALLERS:
        source = caller.read_text(encoding="utf-8")
        assert "QEVIK_VAULT\"" not in source and "QEVIK_VAULT'" not in source, (
            f"{caller.name} still reads QEVIK_VAULT")


# ============================================ what a process would read

def test_describe_says_which_files_and_whether_they_are_there() -> None:
    """The failure was invisible because neither process ever said which file it
    was looking at."""
    stated = describe("/srv/example")
    assert stated["vault"].endswith(VAULT_FILE)
    assert stated["records"].endswith(RECORDS_FILE)
    assert stated["vault_exists"] is False
    assert "one boundary" in stated["note"].lower()


def test_describe_notices_a_real_store(tmp_path) -> None:
    """The negative control on the line above: if `vault_exists` were always
    False it would report a missing vault for a working deployment."""
    (tmp_path / VAULT_FILE).write_text("{}")
    stated = describe(tmp_path)
    assert stated["vault_exists"] is True
    assert stated["records_exist"] is False


# ============================================ the round trip, both processes

def test_what_the_centre_writes_is_what_the_worker_reads(tmp_path,
                                                         monkeypatch) -> None:
    """Both halves, resolved the same way by both sides, with no fallback in
    between."""
    from atlas_kernel.credentials.service import CredentialService, Status
    from atlas_kernel.credentials.vault import FileSecretStore, Vault
    from atlas_kernel.mission.timeline import Timeline

    monkeypatch.setenv("QEVIK_VAULT_MASTER_KEY", "test-only-master-key")
    monkeypatch.setenv("QEVIK_STATE", str(tmp_path))
    where = paths_for()

    def service() -> CredentialService:
        records = Timeline(where.records)
        return CredentialService(Vault(FileSecretStore(where.vault)),
                                 events=records.read(), sink=records.append)

    service().store(provider="qwen", tenant="t1", secret="sk-not-a-real-key")

    # A different process, resolving the same way from the same environment.
    worker = service()
    assert worker.status(provider="qwen",
                         tenant="t1") is Status.PENDING_CREDENTIAL
    assert worker.resolve(provider="qwen", tenant="t1") == "sk-not-a-real-key"

    written = {p.name for p in tmp_path.iterdir()}
    assert written == {VAULT_FILE, RECORDS_FILE}, (
        f"a third credential file appeared: {written}")


def test_no_secret_reaches_the_records_file(tmp_path, monkeypatch) -> None:
    from atlas_kernel.credentials.service import CredentialService
    from atlas_kernel.credentials.vault import FileSecretStore, Vault
    from atlas_kernel.mission.timeline import Timeline

    monkeypatch.setenv("QEVIK_VAULT_MASTER_KEY", "test-only-master-key")
    monkeypatch.setenv("QEVIK_STATE", str(tmp_path))
    where = paths_for()
    records = Timeline(where.records)
    secret = "sk-a-very-distinctive-value-not-real"
    CredentialService(Vault(FileSecretStore(where.vault)),
                      events=records.read(), sink=records.append).store(
        provider="qwen", tenant="t1", secret=secret)

    assert secret not in where.records.read_text(encoding="utf-8")
    assert secret not in where.vault.read_text(encoding="utf-8"), (
        "the vault stores ciphertext, not the value")
