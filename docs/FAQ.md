# Frequently asked questions

## What is Atlas?

An AI operating system that runs on your own machine. It coordinates work
across projects, machines and people: scheduling, automation, approvals,
governance, lineage and recovery.

It is not a chat app and not a model. It is the layer that decides what runs,
where, in what order, and whether a human needs to approve it first.

## Can I generate images or text with it today?

**No.** Atlas has no model provider integrations yet. The two adapters it ships
are simulations that exercise the pipeline without calling a model.

Everything Atlas does to *coordinate* work is real and complete. Everything it
does to *generate* content is not connected. See
[PROVIDER_SETUP.md](PROVIDER_SETUP.md).

## Then what can I actually do?

Run automation rules, build approval policies that pause real executions, watch
the scheduler place work, explore the knowledge graph, manage organizations and
permissions, take backups, and run crash recovery. All of that works on a fresh
install with no configuration.

The **Automation Studio** demo demonstrates it end to end.

## Do I need to install a database?

No. Atlas bundles PostgreSQL 16 and starts its own private instance on a
loopback port. It does not touch a PostgreSQL you already have.

## Do I need Python?

No. The kernel ships as a standalone binary with the runtime embedded.

## Why is the download so large?

About 140 MB compressed, mostly PostgreSQL. `libicudata` alone is 55 MB and
cannot be removed — PostgreSQL 16 links ICU for collation and will not start
without it. The alternative was making you install a database first.

## Why does my computer say Atlas is unsafe?

Alpha builds are unsigned. Signing needs an Apple Developer ID (99 USD/year)
and a Windows code-signing certificate (200–500 USD/year), neither of which is
part of this release.

Verify the SHA-256 against `SHA256SUMS.txt` instead. See
[INSTALLATION.md](INSTALLATION.md).

## Does Atlas send my data anywhere?

No. There is no account, no sign-in, no cloud, and **no Atlas server at all**.
Telemetry is off by default, and even enabled it writes to a local file you can
read.

Once real providers exist, prompts you send to a provider will go to that
provider under your own key and their terms. Atlas is the client, not the
counterparty. See [PRIVACY.md](PRIVACY.md).

## Will it update itself?

No, deliberately. Atlas can tell you a release exists; it will never download
or install one. Software that can replace its own code without being asked is a
security property nobody agreed to.

## Is it open source?

Source-available, not open source. Atlas is under the
[Business Source License 1.1](../LICENSE).

Permitted, including commercially: personal use, use inside your own company,
research, education, and consulting for a client. Not permitted: offering Atlas
to third parties as a hosted or embedded service.

On **2030-08-03** this version becomes Apache-2.0 automatically.

## Can I use it at work?

Yes. Internal company use is explicitly permitted, commercial or not. The only
restriction is reselling Atlas itself as a service.

## Can I run it on a server for my team?

Not safely. **The kernel API has no authentication.** It binds to localhost and
assumes one trusted operator. Do not expose port 8000 to a network you do not
control.

The organization and permission system governs actions inside Atlas; it is not
a network auth layer.

## What happened to the six studios in the docs?

`CLAUDE.md` describes the design intent: Coding, Image, Video, Audio, Business
and Research. Today there are working screens for Image, Research, Review,
Agent and Automation. Video, Audio, Coding and Business are not built.

[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) is the honest inventory.

## Atlas will not start after a crash

It should recover on its own — a launch reclaims anything a previous crash left
running. If it does not, quit fully and reopen. See
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## How do I move my data to another machine?

Copy the data folder (see [INSTALLATION.md](INSTALLATION.md)) or use
`Diagnostics → Backup`. Note that archives hold asset *metadata*, not asset
bytes.

## How do I completely remove it?

Delete the application and the data folder. That is everything — no registry
sprawl, no cloud state, nothing left behind.

## Can I contribute?

Yes, and there is a real caveat worth reading first: open an issue before
writing anything beyond a bug fix, because Atlas has a written architecture and
deliberate scope limits. See [CONTRIBUTING.md](../CONTRIBUTING.md).

## Where do I report a bug?

[Issue templates](https://github.com/hellnight333/atlas/issues/new/choose). The
diagnostics export field saves several rounds of questions.

Security problems go through
[Security Advisories](https://github.com/hellnight333/atlas/security/advisories/new),
never a public issue.

## Who makes this?

Atlas is built by Ayoub Soleimani. It is a long-term personal project made
public at alpha, not a company product. There is no support contract and no
guaranteed response time.
