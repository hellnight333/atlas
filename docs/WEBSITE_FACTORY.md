# Website Factory (M015)

Builds, deploys and maintains real websites for real customers. Scope, phases and
non-goals live in [`M015.md`](../M015.md); this describes what exists and why it
is shaped this way.

**Phase A is implemented: publish, gate, promote, verify, roll back.** Phase B
(generation from `Site` content) and Phase C (health checks and redeploy on
change) are not.

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
