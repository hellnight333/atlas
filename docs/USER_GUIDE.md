# Atlas user guide

Every screen, what it does, and what it does not do yet.

Atlas is an AI operating system: it coordinates work across projects, machines
and people. Today the coordination half is complete and the model-integration
half is not — see [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). This
guide marks anything that needs a provider you cannot connect yet.

## The shape of it

```
Workspace ─ Project ─ Run ─ Step ─ Job
```

A **workspace** holds related work. A **project** is one body of work. A
**run** is one attempt at producing something, made of **steps**, which become
**jobs** that a worker executes.

Around that sit the systems that make it trustworthy: automation decides when
work starts, approvals decide whether it may proceed, the cluster decides
where it runs, and the knowledge graph records what came from what.

## Getting around

| Shortcut | Does |
|---|---|
| `Cmd/Ctrl + K` | Command palette |
| `Cmd/Ctrl + M` | Mission Control |
| `Esc` | Close the palette, Mission Control or the Activity Center |

Those are the only three global shortcuts. See
[KEYBOARD_SHORTCUTS.md](KEYBOARD_SHORTCUTS.md).

## Screens

### Desktop Overview

The landing screen: recent work, what is running, what needs you.

### Home Workspace

Projects and assets for the current workspace. Start here for day-to-day work.

### Automation Studio

Rules that start work for you. A rule is three declarative parts:

- **Trigger** — a schedule, an event, or manual
- **Conditions** — must hold for the rule to act
- **Actions** — what happens

**Dry run** shows exactly what a rule would do without doing it. Use it before
enabling anything.

Rules that arrive from a demo are **switched off**. Running one while it is off
reports `skipped — rule disabled`, which is the truth rather than a failure.
Enable it and Run applies for real.

Automation never calls a model provider. It enqueues work through the
scheduler, which is why it works fully on a machine with no credentials.

### Approval Center

Where work waits for a person.

When a policy matches, execution stops **before a job is created** and appears
here. Nothing in Atlas publishes, deletes or spends on its own.

Rules that always hold:

- You cannot approve your own request.
- Only designated approvers can decide.
- The same person cannot approve twice toward a quorum.
- A decided request cannot be re-decided.

With no policy configured, nothing requires approval.

### Cluster Studio

Which machines can run work, and what they are doing.

A single computer is a cluster of one — the in-process worker registers itself
and needs no setup. You never choose a worker; the scheduler places work from
what the job needs and what each machine offers.

If something is stuck, `placement_reason` says which constraint failed: no
worker online, no worker with that capability, every worker at capacity.

> **Alpha limit:** there is no remote worker agent yet, so the cluster is this
> machine. The placement, reservation and lease logic is real and complete;
> there is simply nothing else to place onto.

### Organization Studio

Teams, roles and permissions.

Creating an organization seeds seven built-in roles. Permissions resolve from
role data, never from a role-name check, so a custom role is not second-class.

Ask why someone can do something and Atlas answers with the role and
membership that granted it — the same data support and the UI both see.

> **Alpha limit:** this governs actions inside Atlas. It is not network
> authentication. The API has no auth and must not be exposed beyond your
> machine.

### Research

Questions, sources and findings, kept in a session you can reopen and audit.

> **Needs a provider.** Structure, sessions and the graph work now; the
> gathering and synthesis steps do not.

### Image Studio

Prompts, variants and results.

> **Needs a provider.** The screen and pipeline are wired; there is no image
> model connected, so generation returns a simulated placeholder.

### Agent Studio

Agents, their capabilities, and the teams they form. Planning and assignment
are real; what an agent *produces* needs a provider.

### Review

Side-by-side comparison with comments and decisions. Used for choosing between
variants and for editorial gates.

### Activity Center

Everything that has happened: runs, automation, approvals, worker events. The
first place to look when you wonder what Atlas just did.

### Mission Control

`Cmd/Ctrl + M`. A live view of everything in flight across projects.

### Diagnostics

Component health, environment, dependency versions, backup and restore, and
the recovery sweep.

**Export** produces a file that is safe to attach to a bug report: it
deliberately excludes the database URL and every credential.

## Backups

`Diagnostics → Backup`. Always **validate** before restoring, and prefer a dry
run first.

Restore is **additive**: existing records are skipped, never overwritten. A
restore reporting `0 restored` means the records already exist — success, not
failure.

Archives contain **asset metadata, not asset bytes**. Backing up Atlas is not
the same as backing up your files.

## Privacy

Atlas collects nothing by default and there is no Atlas server to receive
anything. There is no account and no sign-in.

If you enable diagnostics, crash reports carry the exception *type* and where
in Atlas it happened — never the message, which routinely contains file paths
and your own text. Enforced by an allow-list in code, not by policy. See
[PRIVACY.md](PRIVACY.md).

## When something is stuck

1. `Diagnostics` — is a component degraded?
2. `Approval Center` — waiting on a person?
3. `Cluster Studio` — waiting on a machine? Read `placement_reason`.
4. `Diagnostics → Recovery` — dry run the sweep, then run it.

[TROUBLESHOOTING.md](TROUBLESHOOTING.md) has the full list.
