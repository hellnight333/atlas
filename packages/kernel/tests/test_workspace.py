"""The workspace: real files, real subprocesses, real confinement.

Marked `integration` because it genuinely touches the filesystem and spawns
processes. Mocking either would leave the interesting failures untested — path
escape and process cleanup are only real when the OS is involved.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from atlas_kernel.workspace import (
    CODE_EXECUTE,
    PathEscape,
    Workspace,
    WorkspaceError,
    free_port,
    safe_join,
    wait_for_port,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path, "project")


class TestConfinement:
    """An agent writing outside its own directory is the most damaging thing a
    coding capability can do, and it happens through a generated `..` far more
    often than through malice."""

    def test_a_parent_traversal_is_refused(self, ws: Workspace) -> None:
        with pytest.raises(PathEscape):
            ws.write("../escaped.txt", "no")

    def test_a_deep_traversal_that_looks_innocent_is_refused(self, ws: Workspace) -> None:
        with pytest.raises(PathEscape):
            ws.write("a/b/../../../../etc/passwd", "no")

    def test_an_absolute_path_is_refused(self, ws: Workspace) -> None:
        with pytest.raises(PathEscape):
            ws.write("/etc/passwd", "no")

    def test_a_symlink_out_of_the_workspace_is_refused(self, ws: Workspace, tmp_path) -> None:
        """Checked after resolution, because a symlink is invisible in the text
        of a path."""
        outside = tmp_path / "outside"
        outside.mkdir()
        (ws.root / "link").symlink_to(outside)
        with pytest.raises(PathEscape):
            ws.write("link/file.txt", "no")

    def test_the_root_itself_resolves(self, ws: Workspace) -> None:
        assert safe_join(ws.root, ".") == ws.root

    def test_ordinary_nested_paths_are_fine(self, ws: Workspace) -> None:
        ws.write("src/deep/app.py", "print('hi')")
        assert ws.read("src/deep/app.py") == "print('hi')"

    def test_running_outside_the_workspace_is_refused(self, ws: Workspace) -> None:
        with pytest.raises(PathEscape):
            ws.run([sys.executable, "-c", "pass"], cwd="../..")


class TestRunningCommands:
    def test_it_runs_a_real_process_and_captures_output(self, ws: Workspace) -> None:
        result = ws.run([sys.executable, "-c", "print('hello')"])
        assert result.ok
        assert "hello" in result.stdout

    def test_a_failing_command_is_recorded_not_raised(self, ws: Workspace) -> None:
        """A factory that only records its successes cannot diagnose anything."""
        result = ws.run([sys.executable, "-c", "import sys; sys.exit(3)"])
        assert not result.ok
        assert result.exit_code == 3
        assert result in ws.commands

    def test_check_turns_a_failure_into_an_exception_with_the_output(self, ws: Workspace) -> None:
        with pytest.raises(WorkspaceError, match="boom"):
            ws.run(
                [sys.executable, "-c", "import sys; print('boom'); sys.exit(1)"],
                check=True,
            )

    def test_a_hanging_command_is_killed(self, ws: Workspace) -> None:
        """A hung build on a 4-vCPU box does not fail, it occupies — and the
        factory stops for a reason that never reaches a log."""
        result = ws.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1.0)
        assert result.timed_out
        assert not result.ok

    def test_a_missing_tool_is_a_configuration_error(self, ws: Workspace) -> None:
        """Not a failed build. Saying so saves reading a build log for an error
        that is not in it."""
        with pytest.raises(WorkspaceError, match="not installed"):
            ws.run(["definitely-not-a-real-binary-xyz"])

    def test_enormous_output_is_truncated(self, ws: Workspace) -> None:
        """A build printing half a gigabyte must not take the control plane down
        with it."""
        result = ws.run([sys.executable, "-c", "print('x' * 2_000_000)"])
        assert result.truncated
        assert "[truncated]" in result.stdout
        assert len(result.stdout) < 1_100_000

    def test_it_runs_in_the_workspace_by_default(self, ws: Workspace) -> None:
        result = ws.run([sys.executable, "-c", "import os; print(os.getcwd())"])
        assert str(ws.root.resolve()) in result.stdout

    def test_an_empty_command_is_refused(self, ws: Workspace) -> None:
        with pytest.raises(ValueError, match="no command"):
            ws.run([])

    def test_the_command_renders_for_a_human_but_is_stored_as_argv(self, ws: Workspace) -> None:
        """Rebuilding a shell string and running it is the injection this design
        avoids; rendering one for a report is not."""
        result = ws.run([sys.executable, "-c", "print('a b')"])
        assert result.argv[0] == sys.executable
        assert "-c" in result.command

    def test_environment_can_be_extended(self, ws: Workspace) -> None:
        result = ws.run(
            [sys.executable, "-c", "import os; print(os.environ['QEVIK_TEST'])"],
            env={"QEVIK_TEST": "set"},
        )
        assert "set" in result.stdout


class TestLifecycle:
    def test_a_workspace_is_never_silently_reused(self, tmp_path: Path) -> None:
        """Adopting one would let a new project inherit a previous failure's
        half-written files, and the bug then looks like the generator."""
        Workspace.create(tmp_path, "p")
        with pytest.raises(WorkspaceError, match="already exists"):
            Workspace.create(tmp_path, "p")

    def test_an_existing_directory_can_be_resumed_deliberately(self, tmp_path: Path) -> None:
        first = Workspace.create(tmp_path, "p")
        first.write("kept.txt", "still here")
        assert Workspace.open(first.root).read("kept.txt") == "still here"

    def test_opening_something_that_is_not_a_directory_fails(self, tmp_path: Path) -> None:
        with pytest.raises(WorkspaceError, match="not a directory"):
            Workspace.open(tmp_path / "nope")

    def test_projects_do_not_destroy_each_other(self, tmp_path: Path) -> None:
        """Multiple projects must coexist; that is the whole point of a factory."""
        a, b = Workspace.create(tmp_path, "a"), Workspace.create(tmp_path, "b")
        a.write("f.txt", "A")
        b.write("f.txt", "B")
        assert (a.read("f.txt"), b.read("f.txt")) == ("A", "B")
        a.destroy()
        assert b.read("f.txt") == "B"
        assert not a.root.exists()

    def test_ids_are_unique_per_workspace(self, tmp_path: Path) -> None:
        ids = {Workspace.create(tmp_path, f"p{i}").record.id for i in range(3)}
        assert len(ids) == 3


class TestLineage:
    def test_every_write_and_command_is_recorded_in_order(self, ws: Workspace) -> None:
        ws.write("a.py", "print(1)")
        ws.run([sys.executable, "a.py"])
        ws.write("b.py", "print(2)")
        assert [type(h).__name__ for h in ws.history] == [
            "FileWrite",
            "CommandResult",
            "FileWrite",
        ]

    def test_the_lineage_reads_as_a_report(self, ws: Workspace) -> None:
        ws.write("a.py", "print(1)")
        ws.run([sys.executable, "a.py"])
        text = ws.lineage()
        assert "wrote a.py" in text
        assert "ran " in text
        assert ws.record.id in text

    def test_files_lists_what_was_built(self, ws: Workspace) -> None:
        ws.write("src/app.py", "x")
        ws.write("README.md", "y")
        assert ws.files() == ["README.md", "src/app.py"]

    def test_the_tail_is_where_the_error_is(self, ws: Workspace) -> None:
        result = ws.run([sys.executable, "-c", "print('\\n'.join(str(i) for i in range(100)))"])
        assert result.tail(3) == "97\n98\n99"


class TestServing:
    def test_it_serves_and_stops_for_certain(self, ws: Workspace) -> None:
        """A background process that survives its verification is a port leak on
        a shared box; after a few runs nothing can bind anything."""
        import urllib.request

        ws.write("index.html", "<h1>served</h1>")
        port = free_port()
        with ws.serve(
            [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
            port=port,
        ):
            body = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read()
            assert b"served" in body
        assert not wait_for_port(port, timeout=2), "the server outlived its block"

    def test_a_server_that_never_listens_fails_with_its_output(self, ws: Workspace) -> None:
        port = free_port()
        with pytest.raises(WorkspaceError, match="nothing was listening"):
            with ws.serve(
                [sys.executable, "-c", "print('crashed immediately')"],
                port=port,
                ready_timeout=2.0,
            ):
                pass  # pragma: no cover

    def test_free_port_gives_a_usable_port(self) -> None:
        assert 1024 < free_port() < 65536


class TestItIsACapability:
    def test_the_capability_is_named_not_a_runtime(self) -> None:
        assert CODE_EXECUTE == "code.execute"
