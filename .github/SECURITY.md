# Security Policy

## Reporting a vulnerability

**Do not open a public issue.**

Report privately through
[GitHub Security Advisories](https://github.com/hellnight333/atlas/security/advisories/new).
That channel is private until an advisory is published.

Include what you can: what an attacker gains, how to reproduce it, the Atlas
version, and whether it needs an authenticated session or physical access to
the machine. A proof of concept helps but is not required.

You will get an acknowledgement within **5 working days**. Atlas is maintained
by one person, so please read that as a genuine commitment rather than an SLA
backed by a team.

## Supported versions

| Version | Supported |
|---|---|
| 0.12.x (Public Alpha) | Yes |
| < 0.12 | No — pre-alpha milestone builds |

Alpha means fixes land on `main` and in the next alpha. There is no backported
patch release for older alphas.

## What Atlas already does

- **No telemetry by default.** Nothing is collected until you turn it on, and
  events are built from an allow-list so user content cannot be included. See
  `docs/PRIVACY.md`.
- **No auto-update.** Atlas never downloads or installs code on its own. It
  can tell you a release exists; that is all.
- **No autonomous execution.** When an approval policy matches, work pauses
  before a job exists and waits for a human.
- **Append-only audit.** Governance events cannot be updated or deleted
  through any kernel path.
- **Credentials stay out of reports.** The diagnostics export deliberately
  omits the database URL and provider keys so it is safe to attach to a bug.

## What Atlas does not do yet

Being honest about the alpha's boundaries, because a security policy that
oversells is worse than none:

- **The kernel API has no authentication.** It binds to localhost and assumes
  a single trusted operator on the machine. **Do not expose port 8000 to a
  network you do not control.** Multi-tenant identity exists as a governance
  model inside Atlas; it is not a network authentication layer.
- **Provider credentials are stored in the local configuration**, protected by
  filesystem permissions, not by an OS keychain.
- **Alpha builds are unsigned.** macOS Gatekeeper and Windows SmartScreen will
  warn you. Verify the SHA-256 checksum published with each release before
  running an installer.
- **Bundled PostgreSQL listens on localhost only** and is created per install.

## Scope

In scope: the kernel, the desktop shell, packaging and installers, and the
default configuration.

Out of scope: vulnerabilities in third-party providers or models you connect
Atlas to; issues that require an attacker to already have privileged access to
your machine; and the network exposure of port 8000, which is documented above
as unsupported rather than a defect.
