# Privacy

Short version: **Atlas collects nothing by default and operates no server that
could receive your data.**

## What Atlas sends when you do nothing

Nothing. A fresh install has telemetry disabled and the update check disabled.
No network request is made to any Atlas-operated endpoint, because none exists.

Two things do reach the network, and both are yours:

- **Providers you configure.** If you set up Anthropic, Google, Runway or any
  other provider, prompts and assets go to that provider under *their* privacy
  terms, using *your* credentials. Atlas is the client, not the counterparty.
- **Model downloads**, when you choose to download one.

Running `ATLAS_PROFILE=offline` refuses cloud providers outright.

## If you turn telemetry on

Off by default. Two levels, both revocable:

| Mode | Collects |
|---|---|
| `disabled` | Nothing. The default. |
| `crash_only` | Anonymous crash reports. |
| `diagnostics` | Crash reports plus version and platform. |

### What a crash report contains

Exception *type* and module, a count of stack frames, and the frames that are
inside Atlas itself, reduced to `module:function:line`. Plus your OS, CPU
architecture, Atlas version and a random install id.

### What it deliberately does not contain

The **exception message** is excluded, because messages routinely embed file
paths, identifiers and user input. Stack frames outside the Atlas package are
dropped, because their paths contain your username and your project names. No
local variables. No prompts, assets, filenames, project names, credentials or
provider keys.

This is enforced structurally: events are assembled from an allow-list of
field names (`ALLOWED_EVENT_FIELDS` in `atlas_kernel/telemetry.py`), so a field
cannot be collected until someone adds it to that list on purpose. A deny-list
would leak the first time anyone added a field; an allow-list cannot.

### Where it goes

By default, a local file you can read. Atlas runs no telemetry server, so
there is nowhere for events to be sent unless you configure a sink yourself.

```bash
curl localhost:8000/telemetry        # exactly what is collected and where
```

### The install id

A random identifier, generated only when you enable telemetry. It is not
derived from your hardware, username or network. Disabling telemetry discards
it — revoking consent destroys the only identifier that existed, so
re-enabling later produces a new one.

## The diagnostics export

`GET /diagnostics` is designed to be pasted into a bug report. It contains the
profile, host platform, dependency versions and component health. It
deliberately **excludes the database URL** (which can carry a password) and all
provider credentials.

It is generated on demand and sent nowhere. Attaching it to an issue is your
action, not Atlas's.

## Update checks

Disabled by default. When you enable it, or press "Check for updates", Atlas
makes one unauthenticated request to the public GitHub releases API. GitHub
sees your IP address, as it would for any web request. Atlas sends no
identifier, no version, and no usage data with it.

## Your data on disk

Projects, assets, the knowledge graph and audit records live in your own
PostgreSQL database and data directory. Nothing is uploaded. Back it up
yourself — `POST /backups/export` handles Atlas's own records, but asset
*bytes* live on your filesystem and need their own backup.

## Deleting everything

Atlas keeps no account and no remote state. Uninstall, then delete the data
directory and the database. That is a complete erasure; there is no copy
anywhere else.
