# Website Factory (M015)

Builds, deploys and maintains real websites for real customers. Scope, phases and
non-goals live in [`M015.md`](../M015.md); this describes what exists and why it
is shaped this way.

**Phase A is frozen and proven.** **Phase B — generation from content — is
implemented**, and a generated site has been deployed to a real host with the
gate passing on zero findings. Phase C (scheduled health checks) is not built.

## Phase B: no fabricated business facts

The invariant this phase exists to enforce. M014's rule is that Atlas may not
make a claim about a business it cannot substantiate; publishing **as** that
business is strictly worse. An invented opening time is wrong in the customer's
own voice, on their own domain, and *they* carry the consequences — somebody
turns up at 8pm because the site Atlas wrote said the shop was open.

Two mechanisms, different in kind:

**Facts carry a source, and there is no source meaning "a model wrote it."**
`FactSource` has `OPERATOR`, `CUSTOMER`, `BUSINESS_RECORD`, `OBSERVED` — and no
`GENERATED`. That does not stop a determined caller attributing an invention to
the operator, and is not meant to: it makes every fact **attributable**, so a
wrong one leads back to its source instead of dissolving into the output.

**Absent facts are absent from the page.** No placeholders, no "Call us today!",
no filler where a phone number should be. This is the mechanism that does the
work, because the tempting failure is not inventing an address — it is padding a
thin page with confident copy that asserts nothing anyone supplied. A business
that supplied its weekday hours publishes its weekday hours; the weekend is not
guessed, and not rendered as "Closed".

`Prose` is a separate type from `Fact`. Prose may be written; it is rendered
where prose belongs and cannot become the opening hours by being written
confidently.

### An honest consequence

A site carrying one fact **fails Atlas's own detector on thin content**, and is
refused. That is correct rather than a bug: a page with twenty characters of text
will not rank, and the remedy is to get more content from the customer — a
conversation, not a code change. Atlas will not pad a page to get it past its own
gate.

### The vulnerability the tests found

A test asserting content cannot inject markup failed on the first run, and the
hole was real: **JSON escaping does not escape `</script>`**. A business name
containing one would close the structured-data block, and everything after it
would be parsed as markup — cross-site scripting on the customer's own domain,
published by Atlas, in their name.

`html.escape` is not the fix: the contents of a `<script>` element are not parsed
as HTML, so escaped entities would arrive literally and break the JSON. The three
characters are escaped as JSON `\u003c` / `\u003e` / `\u0026`, which keeps the
payload valid and makes the sequence unrepresentable. Both properties are now
regression-tested.

## Proven end to end, 2026-08-04

Run against a real remote server, not a mock. `infra/phase_a_proof.py` reproduces
it; `infra/atlas-sites.Caddyfile` is the serving config.

| # | Criterion | Evidence |
|---|---|---|
| 1 | Atlas builds an artifact | fingerprint `7515fdcebd8f79a5` |
| 2 | Atlas stores it permanently | read back from Postgres in a fresh repository |
| 3 | Atlas deploys it | version `d78c9b1791d9589f` on the remote box |
| 4 | Atlas promotes it | fetched over verified TLS, correct content |
| 5 | Atlas can redeploy | second build live, content changed |
| 6 | Atlas rolls back from its own artifact | **the old version was deleted from the server first** |

Criterion 6 is the one that matters. The previous version was removed from the
host before the rollback, so a rollback leaning on provider history would have
failed. Atlas republished from its own stored build and promoted it.

### How the environment was set up, and what was refused

The box runs 49 production containers behind a **single bind-mounted Caddyfile**.
Adding a vhost there means restarting the proxy in front of live businesses, so
that was not done to prove a pipeline. Instead:

- A **separate Caddy container** on a spare port with its own config, sharing
  nothing with the production proxy.
- **Bound to loopback and reached over an SSH tunnel**, so no firewall rule was
  opened on a production server.
- **Real TLS with real verification** — Caddy's internal CA, with the root
  fetched and passed to the client. Not `verify=False`; the gate checking a
  connection it did not validate would be theatre.

Three things went wrong on the way, each worth keeping:

**`auto_https off` disables certificate provisioning entirely**, so the first
attempt served a TLS handshake with no certificate to offer. `local_certs` is the
option that means "internal CA", not that one.

**A client connecting by IP sends no SNI**, so Caddy had no site to match and
aborted the handshake. `default_sni` names the site to assume.

**The web server must serve `<slug>/current/`, not `<slug>/`.** The first run
deployed, promoted and rolled back correctly at the file level — the `current`
symlink pointed exactly where it should — while every HTTP check failed, because
Caddy was serving the directory holding `versions/` and the link rather than the
link itself. The adapter moves files and swaps a symlink; deciding that `current`
is the document root is the server's half of the arrangement, and it is now in
`infra/atlas-sites.Caddyfile`.

---

## The invariants

Everything else here is ordinary code. These are load-bearing and enforced by
tests rather than by review.

### 1. Atlas owns the artifact, not the host

A `SiteBuild` stores the files **byte for byte** in Atlas's database. A provider
is handed a copy and is never the place the site exists.

Four things follow, and each is a design decision rather than a sentiment:

| | |
|---|---|
| **Atlas holds the artifact** | `atlas_site_builds.files` is the build, not a path to it |
| **Atlas holds the deployment state** | What is live is `atlas_site_deployments`, never read back from a provider's API — an answer that depends on an account that can be closed is not an answer |
| **Rollback comes from Atlas's artifacts** | `rollback()` republishes from the stored build rather than asking the host to revert |
| **Changing host is publish + promote** | The same build deployed to a second target is a normal operation, not a migration |

Rollback is slower this way than promoting a version the provider still holds.
That is the trade being made: a rollback depending on a provider's retention is
a provider feature wearing Atlas's name, and it fails silently the day the
provider prunes an old deployment or is swapped. Doing it from Atlas's own
artifact also means the provider-independence claim is exercised **every time
anyone reverts**, rather than the first time somebody tries to move a customer.

### 2. Rebuild from Business memory

Delete the build output, delete the working directory, and the site comes back
from the record alone. `rebuild_from_memory()` recomputes the fingerprint and
compares it against the one stored at save time — storing *and* recomputing is
redundant by design, and the redundancy is the check. It catches both an altered
record and non-deterministic rendering.

### 3. Nothing is promoted that Atlas would flag on a stranger's site

The M014 detector runs against every deployment **before promotion** and a
finding blocks it. Selling a business a fix for a missing viewport tag and
shipping them a site without one would be indefensible.

The gate runs against the **published-but-not-live URL**, not the build
directory. That is what publish-then-promote buys: the artifact is reachable at
the real host over real TLS and no visitor is being served it, so the gate
inspects exactly what they would get. A gate reading files off disk cannot catch
a web server pointed at the wrong directory, which is a real way to ship a broken
site.

The detector is **imported** from the Opportunity Factory, not copied or
extracted. Copying would let the two drift silently and in the worst direction —
Atlas would keep selling against a defect it had stopped checking in its own
work. Extracting it would mean reshaping frozen M014 for a second consumer's
convenience. If a third consumer appears, that is when it moves.

### 4. One customer entity

A `Site` references `business_id` and nothing else. There is no `WebsiteClient`,
enforced by `tests/test_one_customer_entity.py`. Every build, deploy, rollback
and check lands on the shared `BusinessEvent` timeline under `factory="website"`,
so one company has one history.

---

## Publish, then promote

The deployment interface is `publish` a versioned artifact, then `promote` it.
That shape was chosen by designing against two hosts at once:

| | Cloudflare Pages | Hetzner |
|---|---|---|
| Publish | upload a bundle, host invents an id | copy a versioned directory |
| Activate | promote that deployment id | swap a symlink, atomically |
| Rollback | promote an earlier id | swap the symlink back |
| TLS | automatic | Caddy / ACME |

An interface phrased as *"copy these files to this path"* encodes Hetzner and
Cloudflare cannot satisfy it. One phrased as *"upload and give me a deployment
id"* encodes Cloudflare and Hetzner cannot. Publish-then-promote is what they
have in common.

**Both adapters exist**, and that is the point: an interface validated by one
implementation is validated by nobody. `LocalDirectoryTarget` derives its own
version id from content and promotes by renaming a symlink;
`CloudflarePagesTarget` has no filesystem, accepts an id the host invents, and
promotes over HTTP. Everything the first relies on is absent from the second and
the interface is unchanged.

**Honest limitation:** the Cloudflare adapter is written against the documented
API and exercised through a controlled transport, because no credentials exist
yet. The request *shapes* are verified; the API's real behaviour is not. The
first real deployment will find whatever is wrong — the interface it is written
against will not be the thing that is wrong.

---

## The pipeline

```
record_build  → the artifact enters the durable record
publish       → reachable at the host, serving nobody
gate          → M014 detector against the preview URL; a finding stops here
promote       → visitors get it
verify        → fetch the live URL; a deploy tool's exit code is not evidence
```

Order is the design. Publication precedes the gate so the gate sees what is
served. Promotion follows it so nobody is served something that failed.
Verification follows promotion because a successful upload and a loadable page
are different claims — a site answering 500 has deployed successfully by every
measure except the one that matters.

Nothing supersedes the previous deployment until verification passes, so there
is never a window with no recorded live version.

**There is no method that builds, deploys and promotes without the gate.** The
gate is not optional and there is no fast path around it.

---

## What Phase A deliberately does not do

- **No generation.** Builds are authored. `Site.content` exists and is stored,
  and Phase B fills it in rather than reshaping a model deployments already
  reference.
- **No binary assets.** `files` is text. A hand-authored HTML and CSS site is
  tens of kilobytes and belongs in the database; real images go to the asset
  system, and building that now would be an abstraction with no user.
- **No retention policy.** Old versions are what rollback promotes. A target
  deciding retention for itself would put policy in an adapter.
- **No health checks on a schedule.** `check_live()` exists as the building
  block; scheduling it is Phase C.
- **The local target does not run a web server.** It assumes one in front of the
  root, because that is what a real deployment is. A target that ran its own
  server would be a different thing in production than in a test, and the whole
  value of a local target is that it is the same thing.

---

## Something the gate caught immediately

On its first run the gate rejected the test suite's own preview URLs, because
they were `http://`. That was correct: a customer site served over plain HTTP is
one of the defects M014 sells against.

Exempting `NO_HTTPS` for preview URLs would have made the tests pass and
weakened the gate. The tests were changed instead — real preview URLs are HTTPS
on both hosts anyway.

Worth recording because it is the gate working as intended on day one, against
its own author.
