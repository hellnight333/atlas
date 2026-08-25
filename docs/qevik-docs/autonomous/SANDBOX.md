# The sandbox

*Status: verified on qevik-core-01. The default registry still assumes no
sandbox, because most hosts do not have one.*

Step 6 of the Munder-Difflin ordering. Listed as `PENDING_INFRASTRUCTURE`:
"needs a host". Like step 5, checking rather than trusting the note found the
blocker had already lifted — **bubblewrap 0.11.1** with unprivileged user
namespaces enabled, already installed.

## Why a worktree is not containment

A CLI coding agent is not a model call. It is a process with its own tool loop
that reads files, writes files, runs commands and calls the network, deciding as
it goes. A git worktree is version control: a process inside one can still read
`~/.ssh`, `POST` to anywhere, and write to the vault.

So the isolation is a **container, not a permission**.

| | |
|---|---|
| filesystem | one writable directory. Everything else read-only or absent. |
| network | off, unless the work says it needs it. |
| environment | an allow-list. |
| time | a wall clock. A loop that never finishes is killed. |

The environment rule is the one people skip. Passing the parent's environment
hands every API key in it to a process whose next action was chosen by a
language model. `SAFE_ENVIRONMENT` is nine variables and a test asserts it stays
short enough to read and contains nothing that looks like a credential — an
allow-list nobody reads is a deny-list with extra steps.

## The absence refuses

`NoSandbox` raises rather than running. Not a `subprocess.run` passthrough,
because a passthrough would make "the agent cannot read `~/.ssh`" fail loudly on
a machine with a sandbox and pass silently on one without — precisely backwards.
`Bubblewrap` refuses to construct where `bwrap` is missing, and refuses an
explicit path that does not exist: trusting the caller's path would move the
failure from construction, where it says "there is no sandbox here", to the
first run, where it looks like the agent's command failing.

An AST test asserts there is exactly one `subprocess.run` in the module.

## What was demonstrated

`infra/verify_sandbox.py`, run 25 August 2026 on qevik-core-01. Full output:
`reports/sandbox_verification.txt`. **16 checks, 0 failures.**

Every check runs a real command inside the sandbox and asserts it could not do
the thing, paired with a control that does the same thing *outside* and asserts
it worked — a check that passes because the command was broken proves nothing.

Two failures on the first run, both real:

**`/root` is not merely unreadable — it does not exist.** The root is an empty
tmpfs and `/root` is never bound, which is stronger than the check expected. The
check was reframed to accept either form of containment rather than one error
message.

**With `network=True` a process still could not resolve `localhost`.**
`/etc/resolv.conf` and friends were never bound, so an agent that asked for the
network would have got a confusing DNS failure and concluded the host was
broken. `RESOLVER_PATHS` is now bound read-only when — and only when — the
network is on, so an offline sandbox does not carry the host's resolver
configuration in for no reason.

A third, in the harness: `ls … | head` reports *head's* exit code, always 0, so
an exit-code assertion behind a pipe is unfalsifiable. The pipe was removed.

## Readiness is a fact about the host

`Agent.ready` is now **derived** from `Agent.blocked_by` rather than stored
beside it. Two fields are two answers to "can this run", and they drift the
first time somebody clears a blocker and forgets the flag.

`Need` makes a blocker structured — `SANDBOX`, `CREDENTIAL`, `BROWSER_WORKER`,
`APPROVAL_POLICY` — so a host that gains a sandbox lifts exactly that one:

    Registry().on_a_host_with_a_sandbox()

The first version of this lifted every CLI agent, which was wrong. `browser` is
waiting on a browser worker; `administrator` needs a per-action approval policy
as well as a sandbox, because a shell on a host is not reversible and containing
it does not make it so. A rule that read "CLI agent → ready" would have declared
both available, and one of them holds a shell.

Matching on `why_not_ready` prose to decide this would have broken the first
time somebody improved the wording. The sentence is for a person; `blocked_by`
is for the code.

`create_app` settles it once at start-up, from the same sandbox the runner would
use — asking twice is asking to disagree — and `/api/health` reports it under
`components.sandbox`.

## What is not built

- **Nothing runs a coding agent through this yet.** `Bubblewrap.run()` executes
  an arbitrary command under isolation; wiring it to the mission worker's agent
  invocation is the remaining step, and claiming a working CLI agent before that
  would be fabricated completion.
- **`cli-implementer` is still blocked** — on `CREDENTIAL` now, not on the
  sandbox.
- **No memory or CPU limit.** `bwrap` does not provide one; that is a cgroup,
  and `systemd-run --scope -p MemoryMax=` is the obvious route on this host.
- **macOS has no backend.** `available()` returns `NoSandbox` there, and the
  unit tests skip with that reason named rather than passing quietly.
