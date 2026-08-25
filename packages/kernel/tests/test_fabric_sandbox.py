"""Isolation, tested on the ways a sandbox stops being one.

The dangerous failure here is not an exception. It is a process that looks
contained and is not — so the tests that matter are the ones that would pass
against a `subprocess.run` with a nice name.

Where a real sandbox exists these run real escape attempts. Where one does not
they **skip, naming the reason**, and the absence-refuses tests still run —
because "there is no sandbox here" must be a visible fact rather than a quiet
green tick. The full escape suite lives in `infra/verify_sandbox.py` and its
recorded run is in `reports/sandbox_verification.txt`.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
from pathlib import Path

import pytest

from atlas_kernel.fabric.sandbox import (
    RESOLVER_PATHS,
    SAFE_ENVIRONMENT,
    SYSTEM_PATHS,
    Bubblewrap,
    Confinement,
    Isolation,
    NoSandbox,
    NotIsolated,
    Outcome,
    available,
    describe,
)

HAS_BWRAP = shutil.which("bwrap") is not None
needs_sandbox = pytest.mark.skipif(
    not HAS_BWRAP,
    reason="no bwrap on this host, so nothing here would prove containment — "
           "see infra/verify_sandbox.py and reports/sandbox_verification.txt")


# ============================================ the absence is never silent

def test_no_sandbox_refuses_to_run_rather_than_running_unconfined() -> None:
    """A passthrough would make "the agent cannot read ~/.ssh" fail loudly on a
    machine with a sandbox and pass silently on one without — backwards."""
    with pytest.raises(NotIsolated, match="Refused"):
        NoSandbox().run(["echo", "hi"], Isolation(workspace=Path.cwd()))


def test_no_sandbox_refuses_to_even_build_a_command() -> None:
    with pytest.raises(NotIsolated):
        NoSandbox().argv(["echo", "hi"], Isolation(workspace=Path.cwd()))


def test_bubblewrap_refuses_to_construct_without_bwrap() -> None:
    """Rather than degrading to `subprocess.run`, which is the same shape of lie
    as a claim implementation that has never seen a database."""
    with pytest.raises(NotIsolated, match="not installed"):
        Bubblewrap(binary="/nonexistent/bwrap-that-is-not-there")


def test_the_description_says_what_this_host_can_actually_enforce() -> None:
    stated = describe(NoSandbox())
    assert stated["confinement"] == Confinement.NONE.value
    assert stated["can_run_coding_agents"] is False
    assert "refused" in stated["detail"]


def test_available_reports_rather_than_raising() -> None:
    """So a deployment can *say* what it has. Running is what refuses."""
    found = available()
    assert isinstance(found, Bubblewrap | NoSandbox)
    assert describe(found)["can_run_coding_agents"] is HAS_BWRAP


def test_there_is_no_permissive_fallback_anywhere_in_the_module() -> None:
    """The absence is the point. If a passthrough is ever added, this test
    should be deleted deliberately rather than quietly satisfied."""
    from atlas_kernel.fabric import sandbox as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    runs = [node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"]
    assert len(runs) == 1, (
        "there should be exactly one subprocess.run in this module, inside "
        "Bubblewrap. A second one is how an unconfined path gets added")


# ============================================ the environment allow-list

def test_a_secret_in_the_parent_environment_is_not_passed_through(
        monkeypatch) -> None:
    """Passing the parent environment hands every API key in it to a process
    whose next action was chosen by a language model."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setenv("QEVIK_VAULT_MASTER_KEY", "not-a-real-key")
    passed = Isolation(workspace=Path.cwd()).env()
    assert "ANTHROPIC_API_KEY" not in passed
    assert "QEVIK_VAULT_MASTER_KEY" not in passed


def test_the_variables_a_toolchain_needs_are_passed(monkeypatch) -> None:
    """The negative control. An environment with no PATH is not a sandbox, it
    is a broken process."""
    monkeypatch.setenv("PATH", "/usr/bin")
    assert Isolation(workspace=Path.cwd()).env()["PATH"] == "/usr/bin"


def test_a_variable_named_on_purpose_is_passed(monkeypatch) -> None:
    passed = Isolation(workspace=Path.cwd(),
                       environment={"DELIBERATE": "yes"}).env()
    assert passed["DELIBERATE"] == "yes"


def test_the_allow_list_holds_nothing_that_looks_like_a_credential() -> None:
    """A deny-list is a promise to have thought of every secret anybody will
    ever put in the environment. This is the other kind, and it must stay
    small enough to read."""
    for name in SAFE_ENVIRONMENT:
        assert not any(word in name for word in ("KEY", "TOKEN", "SECRET",
                                                 "PASSWORD", "CREDENTIAL")), name
    assert len(SAFE_ENVIRONMENT) < 15, (
        "an allow-list nobody reads is a deny-list with extra steps")


# ============================================ the invocation is reviewable

@needs_sandbox
def test_the_flags_can_be_read_rather_than_trusted(tmp_path) -> None:
    """An isolation whose actual flags nobody can see is one nobody can
    review."""
    argv = Bubblewrap().argv(["true"], Isolation(workspace=tmp_path))
    for flag in ("--unshare-user", "--unshare-pid", "--unshare-net",
                 "--die-with-parent", "--new-session"):
        assert flag in argv, flag
    assert argv[argv.index("--chdir") + 1] == str(tmp_path.resolve())


@needs_sandbox
def test_the_workspace_is_the_only_writable_bind(tmp_path) -> None:
    argv = Bubblewrap().argv(["true"], Isolation(workspace=tmp_path))
    writable = [argv[i + 1] for i, flag in enumerate(argv) if flag == "--bind"]
    assert writable == [str(tmp_path.resolve())]


@needs_sandbox
def test_system_paths_are_bound_read_only(tmp_path) -> None:
    argv = Bubblewrap().argv(["true"], Isolation(workspace=tmp_path))
    readonly = {argv[i + 1] for i, flag in enumerate(argv) if flag == "--ro-bind"}
    assert readonly & set(SYSTEM_PATHS), readonly
    assert not any(p.startswith(("/home", "/root")) for p in readonly)


@needs_sandbox
def test_the_resolver_is_bound_only_when_the_network_is_on(tmp_path) -> None:
    """Found by verification: with an empty root and no `/etc/resolv.conf`, a
    process given the network still could not resolve a name, and would have
    reported the host as broken."""
    sandbox = Bubblewrap()
    offline = sandbox.argv(["true"], Isolation(workspace=tmp_path))
    online = sandbox.argv(["true"],
                          Isolation(workspace=tmp_path, network=True))
    existing = [p for p in RESOLVER_PATHS if Path(p).exists()]
    assert existing, "this host has no resolver files at all"
    for path in existing:
        assert path in online, path
        assert path not in offline, (
            f"{path} reached an offline sandbox, which carries the host's "
            "resolver configuration in for no reason")
    assert "--unshare-net" in offline
    assert "--unshare-net" not in online


# ============================================ real escapes, where possible

@needs_sandbox
def test_it_can_do_its_job(tmp_path) -> None:
    """The control that every escape test depends on: if nothing runs, every
    "it could not" below passes for the wrong reason."""
    (tmp_path / "ours.txt").write_text("mine\n")
    done = Bubblewrap().run(["cat", "ours.txt"], Isolation(workspace=tmp_path,
                                                           seconds=30))
    assert done.exit_code == 0
    assert "mine" in done.stdout


@needs_sandbox
def test_it_cannot_read_a_file_outside_its_workspace(tmp_path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("A-SECRET\n")

    stolen = Bubblewrap().run(["cat", str(secret)],
                              Isolation(workspace=workspace, seconds=30))
    assert stolen.exit_code != 0
    assert "A-SECRET" not in stolen.stdout
    # The control: the same file is readable from here, so the assertion above
    # is about containment rather than about a file that was never there.
    plain = subprocess.run(["cat", str(secret)], capture_output=True,
                           text=True, check=False)
    assert plain.returncode == 0 and "A-SECRET" in plain.stdout


@needs_sandbox
def test_it_cannot_write_outside_its_workspace(tmp_path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    target = tmp_path / "escaped.txt"

    Bubblewrap().run(["sh", "-c", f"echo out > {target}"],
                     Isolation(workspace=workspace, seconds=30))
    assert not target.exists()


@needs_sandbox
def test_a_runaway_is_killed_and_says_so(tmp_path) -> None:
    """`timed_out` rather than a non-zero exit: one means the work failed, the
    other means nobody knows how far it got."""
    killed = Bubblewrap().run(["sleep", "30"],
                              Isolation(workspace=tmp_path, seconds=2))
    assert killed.timed_out is True
    assert killed.exit_code is None
    assert "killed after 2s" in killed.detail


# ============================================ outcomes stay honest

def test_a_kill_is_not_reported_as_an_exit_code() -> None:
    """Constructed directly, so the distinction is pinned even on a host with
    no sandbox to demonstrate it."""
    killed = Outcome(ran=True, exit_code=None, stdout="", stderr="",
                     timed_out=True)
    assert killed.exit_code is None
    assert killed.timed_out is True


def test_confinement_is_three_valued_rather_than_a_boolean() -> None:
    """"We could not isolate it" and "we chose not to" are different facts, and
    only one of them is a decision."""
    assert {c.value for c in Confinement} == {"FULL", "PARTIAL", "NONE"}


# ============================================ what the deployment reports

def test_health_reports_whether_this_host_can_contain_a_coding_agent() -> None:
    """A property of the machine, so it is reported rather than assumed — and
    the answer decides whether such an agent may run here at all."""
    from fastapi.testclient import TestClient

    from atlas_kernel.qevik.app import Wiring, create_app

    with TestClient(create_app(Wiring())) as client:
        body = client.get("/api/health").json()
    stated = body["components"]["sandbox"]
    assert stated["can_run_coding_agents"] is HAS_BWRAP
    assert stated["confinement"] == (Confinement.FULL.value if HAS_BWRAP
                                     else Confinement.NONE.value)


def test_the_app_decides_cli_readiness_once_from_the_sandbox_it_would_use(
        ) -> None:
    """Twice would be twice to disagree. The registry the app holds and the
    sandbox it would run in are settled together at start-up."""
    from atlas_kernel.fabric import AGENTS, Backend
    from atlas_kernel.fabric.agents import Need
    from atlas_kernel.qevik.app import Wiring, create_app

    # Only the agents whose declared blocker *is* the sandbox. `browser` is a
    # CLI agent waiting on a browser worker, and a sandbox does not supply one.
    waiting = [a.id for a in AGENTS if Need.SANDBOX in a.blocked_by]
    assert waiting, "the fixture must contain an agent waiting on a sandbox"

    app = create_app(Wiring())
    assert [a for a in app.state.agents.agents
            if a.backend is Backend.CLI_AGENT], (
        "the registry must still list CLI agents either way — an absence is "
        "invisible")
    for agent_id in waiting:
        blocked = Need.SANDBOX in app.state.agents.get(agent_id).blocked_by
        assert blocked is not HAS_BWRAP, (
            f"{agent_id} says the sandbox blocker is "
            f"{'present' if blocked else 'lifted'} while this host "
            f"{'has' if HAS_BWRAP else 'has no'} bwrap")
