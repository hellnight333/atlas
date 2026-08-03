# Quick start

Ten minutes, from download to something real running on your machine.

## 1. Install

Download the build for your platform from
[Releases](https://github.com/hellnight333/atlas/releases), then see
[INSTALLATION.md](INSTALLATION.md) for the security warning you will hit —
alpha builds are unsigned, and both macOS and Windows will say so.

**You do not need to install a database.** Atlas brings its own PostgreSQL and
its own Python runtime. Nothing else has to be on the machine.

## 2. First launch

The first launch takes longer than every later one, because Atlas is creating
its database. The window tells you which stage it is on.

Then setup runs — seven screens, about a minute:

| Step | What happens |
|---|---|
| Welcome | What Atlas is |
| Workspace | Creates a real workspace |
| Storage | Shows where your data lives |
| Appearance | Dark, light or follow the system |
| Diagnostics | **Off by default.** Leave it off if you prefer |
| Providers | Which model services you intend to use later |
| Examples | Install a demo project, or skip |

You can skip setup entirely. Nothing is required.

## 3. Install the Automation Studio example

On the last setup screen, install **Automation Studio**.

Pick that one first for a specific reason: it is the only demo that runs end to
end with **no model provider and no API key**. Atlas has no provider
integrations yet ([why](IMPLEMENTATION_STATUS.md)), so the other four demos
install real projects but mark several steps as needing a provider you cannot
connect yet.

Automation Studio installs:

- a real project
- four real automation rules
- a real knowledge graph

## 4. Run something

Open **Automation Studio** in the sidebar. You will see the four rules,
switched off.

They arrive switched off deliberately: a demo should never start doing work on
a schedule you did not ask for.

1. Pick **Nightly backup and verify**.
2. Press **Run**. It reports `skipped — rule disabled`. That is honest, not
   broken.
3. **Enable** the rule.
4. Press **Run** again. Now it completes and the action is applied.

You have just executed real work through the scheduler, on a machine with no
credentials, and it is in the audit trail.

## 5. Look at what happened

| Where | What it shows |
|---|---|
| **Activity Center** | Everything that just ran |
| **Diagnostics** | Component health, and the export to attach to a bug report |
| **Approval Center** | Empty until a policy matches — nothing is waiting on you yet |
| **Cluster Studio** | One worker: this machine |

## What to expect next

Be clear-eyed about the alpha. Atlas today is a complete **coordination**
platform: scheduling, automation, approvals, governance, lineage, recovery.
The **generation** half — connecting real models — is the next milestone.

If you were hoping to generate an image in the next five minutes, that is not
possible yet, and no setting will make it possible. If you want to see how work
gets orchestrated, approved and audited, all of that is real right now.

## Where to go

- [USER_GUIDE.md](USER_GUIDE.md) — every screen, explained
- [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) — what exists, what does not
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — when something is stuck
- [FAQ.md](FAQ.md)
