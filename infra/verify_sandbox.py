#!/usr/bin/env python3
"""Try to escape the sandbox, and fail. On a real host, for real.

A coding agent is a process with its own tool loop: it reads files, writes
files, runs commands and calls the network, choosing as it goes. "It runs in a
git worktree" is version control, not containment — a process in one can still
read `~/.ssh` and POST to anywhere.

So the only honest test is to *attempt the escape*. Each check below runs a real
command inside the sandbox and asserts it could not do the thing. Every one is
paired with a negative control that does the same thing *outside* the sandbox
and asserts it worked — because a check that passes because the command was
broken proves nothing at all.

    python3 infra/verify_sandbox.py

Needs `bwrap` and unprivileged user namespaces. Refuses to report success
without them rather than skipping quietly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from atlas_kernel.fabric.sandbox import (  # noqa: E402
    Bubblewrap,
    Isolation,
    NoSandbox,
    NotIsolated,
    available,
    describe,
)

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))
    return ok


def main() -> int:
    print("Sandbox — attempting the escapes that matter\n")

    sandbox = available()
    print("0. What this host can enforce")
    print(f"     {json.dumps(describe(sandbox))}")
    if isinstance(sandbox, NoSandbox):
        print("\nNOT VERIFIED. There is no sandbox here, so nothing was "
              "demonstrated. This is a report, not a pass.")
        return 1

    assert isinstance(sandbox, Bubblewrap)

    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw) / "worktree"
        workspace.mkdir()
        (workspace / "ours.txt").write_text("the agent's own file\n")

        outside = Path(raw) / "outside"
        outside.mkdir()
        secret = outside / "credentials.txt"
        secret.write_text("A-SECRET-THE-AGENT-MUST-NOT-READ\n")

        iso = Isolation(workspace=workspace, seconds=30)

        print("\n1. The filesystem")
        inside = sandbox.run(["cat", "ours.txt"], iso)
        check("it can read its own workspace",
              inside.exit_code == 0 and "agent's own file" in inside.stdout,
              "the negative control: if this failed, every check below would "
              "pass because nothing ran")

        wrote = sandbox.run(["sh", "-c", "echo written > new.txt && cat new.txt"],
                            iso)
        check("it can write inside its workspace",
              wrote.exit_code == 0 and "written" in wrote.stdout)

        stolen = sandbox.run(["cat", str(secret)], iso)
        check("it cannot read a file outside the workspace",
              stolen.exit_code != 0 and "SECRET" not in stolen.stdout,
              f"exit {stolen.exit_code}")

        # The control: the same path *is* readable from outside the sandbox, so
        # the check above is about confinement rather than about a missing file.
        plain = subprocess.run(["cat", str(secret)], capture_output=True,
                               text=True, check=False)
        check("and that same file is readable outside the sandbox",
              plain.returncode == 0 and "SECRET" in plain.stdout,
              "otherwise the check above proves only that the file was absent")

        escaped = sandbox.run(
            ["sh", "-c", f"echo pwned > {outside / 'pwned.txt'}"], iso)
        check("it cannot write outside the workspace",
              escaped.exit_code != 0 and not (outside / "pwned.txt").exists(),
              f"exit {escaped.exit_code}")

        # The root filesystem is an empty tmpfs and `/root` is never bound, so
        # the correct outcome is that it does not exist at all — a stronger
        # result than "exists and is unreadable". The check accepts either,
        # because both are containment, and asserts that no real entry came
        # back rather than asserting a particular error message.
        # No pipe: `ls … | head` reports *head's* exit code, which is always 0,
        # so the failure would be invisible. The output is capped in Python
        # instead.
        home = sandbox.run(["ls", "-a", "/root", "/home"], iso)
        entries = [line for line in home.stdout.splitlines()
                   if line.strip() not in ("", ".", "..")
                   and not line.endswith(":")]
        check("root's home is not even present",
              not entries and home.exit_code != 0,
              f"exit {home.exit_code}, stdout {home.stdout[:40]!r}, "
              f"stderr {home.stderr[:50]!r}")
        check("and it does exist on the host outside the sandbox",
              Path("/root").exists() or Path("/home").exists(),
              "otherwise the check above proves only that this machine has no "
              "home directories")

        print("\n2. The network")
        offline = sandbox.run(
            ["sh", "-c", "getent hosts example.com || echo NO-RESOLUTION"], iso)
        check("it cannot resolve a name with the network unshared",
              "NO-RESOLUTION" in offline.stdout, offline.stdout.strip()[:60])

        online = sandbox.run(
            ["sh", "-c", "getent hosts localhost || echo NO-RESOLUTION"],
            Isolation(workspace=workspace, network=True, seconds=30))
        check("and it can when the work says it needs the network",
              "NO-RESOLUTION" not in online.stdout,
              "the negative control on network isolation")

        print("\n3. The environment")
        os.environ["QEVIK_VERIFY_FAKE_KEY"] = "not-a-real-key-just-a-marker"
        leaked = sandbox.run(["sh", "-c", "env"], iso)
        check("a key in the parent environment does not reach the process",
              "QEVIK_VERIFY_FAKE_KEY" not in leaked.stdout,
              "an allow-list, so a secret nobody thought of is still dropped")
        check("but the variables a toolchain needs do",
              "PATH=" in leaked.stdout)

        named = sandbox.run(
            ["sh", "-c", "echo $DELIBERATELY_PASSED"],
            Isolation(workspace=workspace, seconds=30,
                      environment={"DELIBERATELY_PASSED": "yes"}))
        check("a variable passed on purpose does reach it",
              named.stdout.strip() == "yes",
              "otherwise the check above would pass on a sandbox that drops "
              "everything and is unusable")
        os.environ.pop("QEVIK_VERIFY_FAKE_KEY", None)

        print("\n4. Time")
        slow = sandbox.run(["sleep", "30"],
                           Isolation(workspace=workspace, seconds=2))
        check("a process that will not finish is killed",
              slow.timed_out and slow.exit_code is None, slow.detail[:60])
        check("and being killed is not reported as a failed exit code",
              slow.exit_code is None,
              "a non-zero exit means the work failed; this means nobody knows")

        print("\n5. The absence refuses rather than running unconfined")
        try:
            NoSandbox().run(["echo", "hello"], iso)
            check("NoSandbox refuses to run", False, "it ran something")
        except NotIsolated as refused:
            check("NoSandbox refuses to run", True, str(refused)[:70] + "…")

        print("\n6. The invocation is reviewable")
        argv = sandbox.argv(["true"], iso)
        check("the flags can be read rather than trusted",
              "--unshare-net" in argv and "--die-with-parent" in argv,
              " ".join(argv[:9]) + " …")

    print("\n" + "=" * 66)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    print("=" * 66)
    if FAILED:
        print("\nNOT VERIFIED. " + "; ".join(FAILED))
        return 1
    print("\nVerified: " + json.dumps(describe(sandbox)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
