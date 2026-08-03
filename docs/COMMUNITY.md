# Community

Atlas is maintained by one person. These are the channels, and what each is
actually for.

## Where to go

| I want to… | Go to |
|---|---|
| Report something broken | [Bug report](https://github.com/hellnight333/atlas/issues/new/choose) |
| Suggest a capability | [Feature request](https://github.com/hellnight333/atlas/issues/new/choose) |
| Ask how something works | [Discussions → Q&A](https://github.com/hellnight333/atlas/discussions) |
| Show what I built | [Discussions → Show and tell](https://github.com/hellnight333/atlas/discussions) |
| Report a vulnerability | [Security advisory](https://github.com/hellnight333/atlas/security/advisories/new) — never a public issue |
| Contribute code | [CONTRIBUTING.md](../CONTRIBUTING.md) — open an issue first |

## Discussion categories

Proposed structure for GitHub Discussions. These must be created in the
repository's Discussions settings; this file is the plan, not a live mirror.

| Category | Format | For |
|---|---|---|
| **Announcements** | Announcement | Releases and changes that affect you. Maintainer posts only |
| **Q&A** | Question | "How do I…", "Why does Atlas…". Answers get marked |
| **Ideas** | Open | Half-formed thoughts, before they are a feature request |
| **Show and tell** | Open | What you built. Screenshots welcome |
| **Workflows & recipes** | Open | Automation rules and pipelines worth stealing |
| **Self-hosting & hardware** | Open | GPUs, workers, storage, deployment |

## Chat

A Discord server is **planned, not yet open**. When it exists it will be
announced in Announcements and linked here and from the website. Until then,
Discussions is the place.

The intended structure, kept here so it is designed rather than improvised:

```
INFORMATION
  #announcements     releases, breaking changes        read-only
  #rules-and-links   guidelines, docs, roadmap          read-only

HELP
  #install-help      it will not start
  #questions         how do I
  #bugs              triage before a GitHub issue

BUILDING
  #automation        rules and triggers
  #workflows         pipelines end to end
  #hardware          GPUs, workers, storage
  #providers         models and integrations

COMMUNITY
  #show-and-tell     what you made
  #off-topic
```

Two rules the structure encodes: bugs get triaged in chat but **live in GitHub
issues**, because chat is not a tracker; and announcements are one-way, so the
signal channel stays readable.

## Expectations, stated honestly

- **This is one person's project.** No support contract, no response-time
  guarantee. Security reports are acknowledged within five working days.
- **Alpha means rough edges**, and reporting them bluntly is useful. There is
  a difference between blunt and contemptuous — see
  [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md).
- **Some requests will be declined as out of scope.** A marketplace, billing,
  a cloud offering, mobile apps and autonomous agents are excluded by design,
  not by omission. `CLAUDE.md` explains why.
- **Nobody owes you free labour**, including you owing it to anyone else.

## Most useful things you can do right now

1. **Install it and say where you got stuck.** First-run friction is the
   hardest thing to see from the inside.
2. **Tell us what you tried to automate** and where Atlas got in the way.
3. **Report anything dishonest** — a button that does nothing, a screen that
   claims a capability that is not there. That is the bug class this project
   cares most about.
